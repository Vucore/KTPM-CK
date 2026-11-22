import hashlib
import json
from datetime import datetime, timedelta
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import HTTPException

from cinema.booking.domain import STATES, BookingConfirmed, BookingObservers, Pricing, TicketBuilder
from cinema.booking.repositories import BookingRepository, ScreeningSeatRepository, TicketRepository
from cinema.common import Database, ServiceClient
from cinema.contracts import CheckoutRequest, PaymentEvent, SimulatePayment
from cinema.messaging import Outbox, RejectedEvent


class CatalogClient:
    def __init__(self, service: ServiceClient, base_url: str):
        self.service = service
        self.base_url = base_url.rstrip("/")

    def upcoming(self):
        return self.service.request("GET", f"{self.base_url}/screenings")

    def screening(self, screening_id: str):
        screening = self.service.request("GET", f"{self.base_url}/screenings/{quote(screening_id, safe='')}")
        screening["starts_at"] = datetime.fromisoformat(screening["starts_at"])
        return screening


class PaymentClient:
    def __init__(self, service: ServiceClient, base_url: str, internal_key: str):
        self.service = service
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Internal-Key": internal_key}

    def create(self, booking_id: UUID, amount: int):
        return self.service.request(
            "POST",
            f"{self.base_url}/payments",
            headers=self.headers,
            json={"booking_id": str(booking_id), "amount": amount},
        )

    def find(self, booking_id: UUID):
        return self.service.request("GET", f"{self.base_url}/payments/{booking_id}", headers=self.headers)

    def simulate(self, booking_id: UUID, key: UUID, request: SimulatePayment):
        return self.service.request(
            "POST",
            f"{self.base_url}/payments/{booking_id}/simulate",
            headers={**self.headers, "Idempotency-Key": str(key)},
            json=request.model_dump(),
        )


def database_time(connection):
    return connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]


class HoldSeatsUseCase:
    def __init__(
        self,
        db: Database,
        bookings: BookingRepository,
        seats: ScreeningSeatRepository,
        pricing: Pricing,
        catalog: CatalogClient,
        hold_seconds: int,
    ):
        self.db = db
        self.bookings = bookings
        self.seats = seats
        self.pricing = pricing
        self.catalog = catalog
        self.hold_duration = timedelta(seconds=hold_seconds)

    def execute(self, request: CheckoutRequest, key: UUID):
        labels = sorted(set(request.seats))
        if len(labels) != len(request.seats):
            raise HTTPException(422, "Danh sách ghế bị trùng")
        customer = (request.customer_name or "").strip() or None
        data = json.dumps([request.screening_id, labels, customer], ensure_ascii=False)
        fingerprint = hashlib.sha256(data.encode()).hexdigest()
        with self.db.transaction() as connection:
            if existing := self._existing(connection, key, fingerprint):
                return existing
        screening = self.catalog.screening(request.screening_id)

        with self.db.transaction() as connection:
            self.bookings.lock_key(connection, key)
            if existing := self._existing(connection, key, fingerprint):
                return existing
            self.seats.sync(connection, screening)
            rows = self.seats.lock(connection, screening["id"], labels)
            now = database_time(connection)
            if screening["starts_at"] <= now:
                raise HTTPException(409, "Suất chiếu đã bắt đầu")
            if len(rows) != len(labels):
                raise HTTPException(422, "Có ghế không thuộc suất chiếu này")
            if any(
                seat["status"] == "SOLD" or (seat["status"] == "HELD" and seat["expires_at"] > now)
                for seat in rows
            ):
                raise HTTPException(409, "Một hoặc nhiều ghế vừa được giữ hoặc bán")

            booking = {
                "id": uuid4(),
                "request_key": key,
                "request_hash": fingerprint,
                "screening_id": screening["id"],
                "movie_title": screening["title"],
                "starts_at": screening["starts_at"],
                "auditorium": screening["auditorium"],
                "seats": labels,
                "customer_name": customer,
                "amount": self.pricing.total(screening["starts_at"], screening["base_price"], rows),
                "expires_at": min(now + self.hold_duration, screening["starts_at"]),
            }
            self.bookings.insert(connection, booking)
            self.seats.hold(connection, booking)
            return self.bookings.detail(connection, booking["id"])

    def _existing(self, connection, key, fingerprint):
        existing = self.bookings.by_key(connection, key)
        if existing:
            if existing["request_hash"] != fingerprint:
                raise HTTPException(409, "Idempotency-Key đã được dùng cho một yêu cầu khác")
            return self.bookings.detail(connection, existing["id"])
        return None


class CheckoutFacade:
    def __init__(self, hold: HoldSeatsUseCase, payment: PaymentClient):
        self.hold = hold
        self.payment = payment

    def start(self, request: CheckoutRequest, key: UUID):
        booking = self.hold.execute(request, key)
        if booking["status"] == "HELD":
            payment = self.payment.create(booking["id"], booking["amount"])
        else:
            try:
                payment = self.payment.find(booking["id"])
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                raise HTTPException(409, "Đơn đã hết hạn trước khi tạo phiên thanh toán") from error
        return {"booking": booking, "payment": payment}


class BookingService:
    def __init__(
        self,
        db: Database,
        bookings: BookingRepository,
        seats: ScreeningSeatRepository,
        tickets: TicketRepository,
        outbox: Outbox,
        observers: BookingObservers,
    ):
        self.db = db
        self.bookings = bookings
        self.seats = seats
        self.tickets = tickets
        self.outbox = outbox
        self.observers = observers

    def seat_map(self, screening):
        with self.db.transaction() as connection:
            self.seats.sync(connection, screening)
            return self.seats.list(connection, screening["id"])

    def detail(self, booking_id: UUID):
        with self.db.transaction() as connection:
            booking = self.bookings.detail(connection, booking_id)
            if not booking:
                raise HTTPException(404, "Không tìm thấy đơn")
            booking["tickets"] = (
                self.tickets.list(connection, booking_id) if booking["status"] == "CONFIRMED" else []
            )
            return booking

    def ticket(self, code: UUID):
        with self.db.transaction() as connection:
            ticket = self.tickets.find(connection, code)
            if not ticket:
                raise HTTPException(404, "Không tìm thấy vé")
            return ticket

    def expire_one(self):
        with self.db.transaction() as connection:
            booking = self.bookings.next_expired(connection)
            if not booking:
                return False
            self.seats.lock(connection, booking["screening_id"], booking["seats"])
            self._expire(connection, booking)
            return True

    def _expire(self, connection, booking):
        self.seats.release(connection, booking)
        self.bookings.expire(connection, booking["id"])

    def payment_succeeded(self, event: PaymentEvent):
        confirmation = None
        with self.db.transaction() as connection:
            booking = self.bookings.lock(connection, event.booking_id)
            if not booking or booking["amount"] != event.amount:
                raise RejectedEvent("Payment does not match booking")
            if booking["status"] == "HELD":
                self.seats.lock(connection, booking["screening_id"], booking["seats"])
            action = STATES[booking["status"]].payment_action(
                booking, event.payment_id, database_time(connection)
            )

            if action == "expire_and_refund":
                self._expire(connection, booking)
            if action in {"expire_and_refund", "refund"}:
                self.outbox.add(connection, "payment.refund_requested", event)
            if action == "confirm":
                if self.seats.sell(connection, booking) != len(booking["seats"]):
                    raise RuntimeError("Booking no longer owns all held seats")
                self.bookings.confirm(connection, booking["id"], event.payment_id)
                for seat in booking["seats"]:
                    ticket = TicketBuilder(booking["id"], booking["screening_id"], seat)
                    self.tickets.insert(connection, ticket.for_customer(booking["customer_name"]).build())
                confirmation = BookingConfirmed(booking["id"], booking["screening_id"], len(booking["seats"]))
        if confirmation:
            self.observers.notify(confirmation)
