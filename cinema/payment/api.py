from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header

from cinema.common import Database, Settings, configure_http, require_key
from cinema.contracts import CreatePayment, SimulatePayment
from cinema.messaging import Background, Outbox, RabbitWorker
from cinema.payment.gateway import DemoPaymentAdapter, DemoProcessor
from cinema.payment.repository import PaymentRepository
from cinema.payment.service import PaymentService

RequestKey = Annotated[UUID, Header(alias="Idempotency-Key")]


def create_app(settings: Settings | None = None):
    settings = settings or Settings.load("payment")
    db = Database(settings.database_url)
    outbox = Outbox(db, "cinema_payment")
    service = PaymentService(db, PaymentRepository(), DemoPaymentAdapter(DemoProcessor()), outbox)
    worker = RabbitWorker(settings.rabbitmq_url, "payment.refund_requested", outbox, service.refund)

    def authorize(x_internal_key: Annotated[str, Header()] = ""):
        require_key(x_internal_key, settings.internal_key)

    @asynccontextmanager
    async def lifespan(app):
        db.pool.open()
        try:
            with worker.background(), Background("process-payments", service.process_one):
                yield
        finally:
            db.pool.close()

    app = FastAPI(title="Payment Service", lifespan=lifespan)
    configure_http(app, db)
    protected = [Depends(authorize)]

    @app.post("/payments", status_code=201, dependencies=protected)
    def create_payment(request: CreatePayment):
        return service.create(request)

    @app.get("/payments/{booking_id}", dependencies=protected)
    def get_payment(booking_id: UUID):
        return service.find(booking_id)

    @app.post("/payments/{booking_id}/simulate", status_code=202, dependencies=protected)
    def simulate(booking_id: UUID, request: SimulatePayment, key: RequestKey):
        return service.simulate(booking_id, key, request)

    return app
