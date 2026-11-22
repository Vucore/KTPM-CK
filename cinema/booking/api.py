import asyncio
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

import httpx
import qrcode
import qrcode.image.svg
from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from cinema.booking.domain import (
    BookingObservers,
    Pricing,
    SeatMapObserver,
    WeekdayPricing,
    WeekendPricing,
    log_confirmation,
)
from cinema.booking.repositories import BookingRepository, ScreeningSeatRepository, TicketRepository
from cinema.booking.services import (
    BookingService,
    CatalogClient,
    CheckoutFacade,
    HoldSeatsUseCase,
    PaymentClient,
)
from cinema.common import Database, ServiceClient, Settings, configure_http
from cinema.contracts import CheckoutRequest, SimulatePayment
from cinema.messaging import Background, Outbox, RabbitWorker

WEB = Path(__file__).resolve().parent.parent / "web"
RequestKey = Annotated[UUID, Header(alias="Idempotency-Key")]


def create_app(settings: Settings | None = None, downstream: httpx.BaseTransport | None = None):
    settings = settings or Settings.load("booking")
    db = Database(settings.database_url)
    http = httpx.Client(timeout=8, trust_env=False, transport=downstream)
    transport = ServiceClient(http)
    catalog = CatalogClient(transport, settings.catalog_url)
    payment = PaymentClient(transport, settings.payment_url, settings.internal_key)
    bookings, seats, tickets = BookingRepository(), ScreeningSeatRepository(), TicketRepository()
    hold = HoldSeatsUseCase(
        db,
        bookings,
        seats,
        Pricing(WeekdayPricing(), WeekendPricing()),
        catalog,
        settings.hold_seconds,
    )
    checkout = CheckoutFacade(hold, payment)
    seat_updates = SeatMapObserver()
    outbox = Outbox(db, "cinema_booking")
    service = BookingService(
        db, bookings, seats, tickets, outbox, BookingObservers([seat_updates, log_confirmation])
    )
    worker = RabbitWorker(settings.rabbitmq_url, "payment.succeeded", outbox, service.payment_succeeded)

    @asynccontextmanager
    async def lifespan(app):
        db.pool.open()
        try:
            with worker.background(), Background("expire-bookings", service.expire_one):
                yield
        finally:
            http.close()
            db.pool.close()

    app = FastAPI(title="Booking Service", lifespan=lifespan)
    configure_http(app, db)
    app.mount("/assets", StaticFiles(directory=WEB), name="assets")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(WEB / "index.html")

    @app.get("/api/screenings")
    def screenings():
        return catalog.upcoming()

    @app.get("/api/screenings/{screening_id}/seats")
    def seat_map(screening_id: str):
        return service.seat_map(catalog.screening(screening_id))

    @app.get("/api/screenings/{screening_id}/updates")
    async def updates(screening_id: str, request: Request):
        async def stream():
            previous = None
            while not await request.is_disconnected():
                revision = seat_updates.revision(screening_id)
                if revision != previous:
                    yield f"data: {json.dumps(revision)}\n\n"
                    previous = revision
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.post("/api/checkout", status_code=201)
    def start_checkout(request: CheckoutRequest, key: RequestKey):
        return checkout.start(request, key)

    app.get("/api/bookings/{booking_id}")(service.detail)

    @app.get("/api/bookings/{booking_id}/payment")
    def payment_status(booking_id: UUID):
        return payment.find(booking_id)

    @app.post("/api/bookings/{booking_id}/payment/simulate", status_code=202)
    def simulate_payment(booking_id: UUID, request: SimulatePayment, key: RequestKey):
        return payment.simulate(booking_id, key, request)

    @app.get("/api/tickets/{code}/qr.svg")
    def ticket_qr(code: UUID):
        service.ticket(code)
        qr = qrcode.make(str(code), image_factory=qrcode.image.svg.SvgPathImage)
        buffer = io.BytesIO()
        qr.save(buffer)
        return Response(buffer.getvalue(), media_type="image/svg+xml")

    app.get("/api/tickets/{code}")(service.ticket)
    return app
