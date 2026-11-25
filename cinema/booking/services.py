import hashlib
import json
from datetime import datetime, timedelta
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import HTTPException

from cinema.booking.auth import BookingViewer
from cinema.booking.auth_repository import AccountRepository
from cinema.booking.domain import (
    STATES,
    BookingConfirmed,
    BookingObservers,
    Pricing,
    TicketBuilder,
    calculate_discount,
)
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

    def home(self):
        return self.service.request("GET", f"{self.base_url}/catalog/home")

    def movie(self, movie_id: str):
        return self.service.request("GET", f"{self.base_url}/movies/{quote(movie_id, safe='')}")

    def checkout_options(self):
        return self.service.request("GET", f"{self.base_url}/catalog/checkout-options")


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
        accounts: AccountRepository | None = None,
    ):
        self.db = db
        self.bookings = bookings
        self.seats = seats
        self.pricing = pricing
        self.catalog = catalog
        self.hold_duration = timedelta(seconds=hold_seconds)
        self.accounts = accounts or AccountRepository()

    def execute(self, request: CheckoutRequest, key: UUID, viewer: BookingViewer):
        labels = sorted(set(request.seats))
        if len(labels) != len(request.seats):
            raise HTTPException(422, "Danh sách ghế bị trùng")
        customer = (request.customer_name or "").strip() or None
        promo_code = (request.promo_code or "").strip().upper() or None
        concession_requests = sorted(
            [(item.id, item.quantity) for item in request.concessions],
            key=lambda entry: entry[0],
        )
        if len({cid for cid, _ in concession_requests}) != len(concession_requests):
            raise HTTPException(422, "Danh sách bắp nước bị trùng")
        if request.redeem_points > 0 and not viewer.account_id:
            raise HTTPException(401, "Vui lòng đăng nhập để sử dụng điểm D-Star.")

        fingerprint_parts = [request.screening_id, labels, customer]
        if concession_requests or promo_code or request.redeem_points:
            fingerprint_parts.extend([concession_requests, promo_code, request.redeem_points])
        data = json.dumps(fingerprint_parts, ensure_ascii=False)
        fingerprint = hashlib.sha256(data.encode()).hexdigest()

        with self.db.transaction() as connection:
            if existing := self._existing(connection, key, fingerprint, viewer):
                return existing

        screening = self.catalog.screening(request.screening_id)
        options = (
            self.catalog.checkout_options()
            if (concession_requests or promo_code)
            else {"concessions": [], "promotions": []}
        )

        concession_map = {item["id"]: item for item in options["concessions"]}
        concession_items = []
        concessions_amount = 0
        for cid, quantity in concession_requests:
            item = concession_map.get(cid)
            if not item:
                raise HTTPException(422, f"Không tìm thấy sản phẩm bắp nước: {cid}")
            line_total = item["price"] * quantity
            concessions_amount += line_total
            concession_items.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "price": item["price"],
                    "quantity": quantity,
                    "total": line_total,
                }
            )

        promo = None
        if promo_code:
            promo = next(
                (item for item in options["promotions"] if item["code"].upper() == promo_code),
                None,
            )
            if not promo:
                raise HTTPException(422, "Mã khuyến mãi không tồn tại hoặc đã hết hạn.")

        with self.db.transaction() as connection:
            self.bookings.lock_key(connection, key)
            if existing := self._existing(connection, key, fingerprint, viewer):
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

            seat_amount = self.pricing.total(screening["starts_at"], screening["base_price"], rows)
            subtotal = seat_amount + concessions_amount
            available_points = 0
            if viewer.account_id and request.redeem_points > 0:
                account = self.accounts.lock_account(connection, viewer.account_id)
                available_points = account["points"] if account else 0

            try:
                discount_amount, points_used = calculate_discount(
                    subtotal, promo, request.redeem_points, available_points
                )
            except ValueError as error:
                raise HTTPException(422, str(error)) from error

            final_amount = subtotal - discount_amount
            booking_id = uuid4()
            booking = {
                "id": booking_id,
                "request_key": key,
                "request_hash": fingerprint,
                "account_id": viewer.account_id,
                "screening_id": screening["id"],
                "movie_title": screening["title"],
                "starts_at": screening["starts_at"],
                "auditorium": screening["auditorium"],
                "cinema_name": screening.get("cinema_name", "DUT Nguyễn Du"),
                "screening_format": screening.get("format", "2D Phụ đề"),
                "seats": labels,
                "customer_name": customer,
                "concessions": concession_items,
                "concessions_amount": concessions_amount,
                "discount_amount": discount_amount,
                "promo_code": promo_code,
                "points_redeemed": points_used,
                "amount": final_amount,
                "expires_at": min(now + self.hold_duration, screening["starts_at"]),
            }
            self.bookings.insert(connection, booking)
            self.seats.hold(connection, booking)
            if viewer.account_id and points_used > 0:
                self.accounts.record_point_transaction(
                    connection,
                    viewer.account_id,
                    booking_id,
                    "REDEEM",
                    -points_used,
                    f"Đổi {points_used} Star cho đơn {screening['title']}",
                )
            if viewer.history_key:
                self.bookings.save(connection, viewer.history_key, booking["id"])
            return self.bookings.detail(connection, booking["id"], viewer)

    def _existing(self, connection, key, fingerprint, viewer):
        existing = self.bookings.by_key(connection, key)
        if existing:
            if existing["account_id"] and existing["account_id"] != viewer.account_id:
                raise HTTPException(404, "Không tìm thấy đơn")
            if existing["request_hash"] != fingerprint:
                raise HTTPException(409, "Idempotency-Key đã được dùng cho một yêu cầu khác")
            booking = self.bookings.detail(connection, existing["id"], viewer)
            if not booking:
                raise HTTPException(404, "Không tìm thấy đơn")
            return booking
        return None


class CheckoutFacade:
    def __init__(self, hold: HoldSeatsUseCase, payment: PaymentClient):
        self.hold = hold
        self.payment = payment

    def start(self, request: CheckoutRequest, key: UUID, viewer: BookingViewer):
        booking = self.hold.execute(request, key, viewer)
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
        accounts: AccountRepository | None = None,
    ):
        self.db = db
        self.bookings = bookings
        self.seats = seats
        self.tickets = tickets
        self.outbox = outbox
        self.observers = observers
        self.accounts = accounts or AccountRepository()

    def seat_map(self, screening):
        with self.db.transaction() as connection:
            self.seats.sync(connection, screening)
            return self.seats.list(connection, screening["id"])

    def _accessible_booking(self, connection, booking_id, viewer):
        booking = self.bookings.detail(connection, booking_id, viewer)
        if not booking:
            raise HTTPException(404, "Không tìm thấy đơn")
        return booking

    def detail(self, booking_id: UUID, viewer: BookingViewer):
        with self.db.transaction() as connection:
            booking = self._accessible_booking(connection, booking_id, viewer)
            booking["tickets"] = (
                self.tickets.list(connection, booking_id) if booking["status"] == "CONFIRMED" else []
            )
            return booking

    def require_access(self, booking_id: UUID, viewer: BookingViewer):
        with self.db.transaction() as connection:
            self._accessible_booking(connection, booking_id, viewer)

    def saved_bookings(self, viewer: BookingViewer):
        with self.db.transaction() as connection:
            return self.bookings.saved_list(connection, viewer)

    def save_booking(self, booking_id: UUID, viewer: BookingViewer):
        with self.db.transaction() as connection:
            self._accessible_booking(connection, booking_id, viewer)
            self.bookings.save(connection, viewer.history_key, booking_id)

    def forget_booking(self, booking_id: UUID, viewer: BookingViewer):
        with self.db.transaction() as connection:
            self.bookings.forget(connection, viewer.history_key, booking_id)

    def cancel(self, booking_id: UUID, viewer: BookingViewer, payment_client: PaymentClient):
        self.require_access(booking_id, viewer)
        payment = payment_client.find(booking_id)
        if payment["status"] not in {"PENDING", "DECLINED"}:
            raise HTTPException(409, "Không thể hủy đơn khi giao dịch thanh toán đang xử lý hoặc đã hoàn tất.")
        with self.db.transaction() as connection:
            booking = self.bookings.lock(connection, booking_id)
            if not booking or (booking["account_id"] and booking["account_id"] != viewer.account_id):
                raise HTTPException(404, "Không tìm thấy đơn")
            if booking["status"] != "HELD":
                raise HTTPException(409, "Đơn này không còn ở trạng thái giữ ghế.")
            self.seats.lock(connection, booking["screening_id"], booking["seats"])
            self.seats.release(connection, booking)
            self.bookings.cancel(connection, booking["id"])
            self._restore_points(connection, booking)
            return self.bookings.detail(connection, booking["id"], viewer)

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
        self._restore_points(connection, booking)

    def _restore_points(self, connection, booking):
        if booking.get("account_id") and booking.get("points_redeemed", 0) > 0:
            self.accounts.record_point_transaction(
                connection,
                booking["account_id"],
                booking["id"],
                "RESTORE",
                booking["points_redeemed"],
                f"Hoàn {booking['points_redeemed']} Star do hủy/hết hạn giữ ghế",
            )

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
                self._restore_points(connection, booking)
                self.outbox.add(connection, "payment.refund_requested", event)
            if action == "confirm":
                if self.seats.sell(connection, booking) != len(booking["seats"]):
                    raise RuntimeError("Booking no longer owns all held seats")
                self.bookings.confirm(connection, booking["id"], event.payment_id)
                for seat in booking["seats"]:
                    ticket = TicketBuilder(booking["id"], booking["screening_id"], seat)
                    self.tickets.insert(connection, ticket.for_customer(booking["customer_name"]).build())
                if booking.get("account_id"):
                    self.accounts.add_spent_and_earn(
                        connection,
                        booking["account_id"],
                        booking["id"],
                        booking["amount"],
                        f"Tích điểm vé {booking['movie_title']}",
                    )
                confirmation = BookingConfirmed(booking["id"], booking["screening_id"], len(booking["seats"]))
        if confirmation:
            self.observers.notify(confirmation)
