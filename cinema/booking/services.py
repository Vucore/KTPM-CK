import hashlib
import json
from datetime import datetime, timedelta
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

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
from cinema.contracts import BookingOptions, CheckoutRequest, PaymentEvent, SimulatePayment
from cinema.messaging import Outbox, RejectedEvent


class CatalogClient:
    def __init__(self, service: ServiceClient, base_url: str, internal_key: str = ""):
        self.service = service
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Internal-Key": internal_key} if internal_key else {}

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

    def admin_snapshot(self):
        return self.service.request("GET", f"{self.base_url}/admin/catalog", headers=self.headers)

    def save_movie(self, payload, movie_id: str | None = None):
        method = "PUT" if movie_id else "POST"
        suffix = f"/{quote(movie_id, safe='')}" if movie_id else ""
        return self.service.request(
            method,
            f"{self.base_url}/admin/movies{suffix}",
            headers=self.headers,
            json=payload.model_dump(mode="json"),
        )

    def delete_movie(self, movie_id: str):
        return self.service.request(
            "DELETE",
            f"{self.base_url}/admin/movies/{quote(movie_id, safe='')}",
            headers=self.headers,
        )

    def save_cinema(self, payload, cinema_id: str | None = None):
        method = "PUT" if cinema_id else "POST"
        suffix = f"/{quote(cinema_id, safe='')}" if cinema_id else ""
        return self.service.request(
            method,
            f"{self.base_url}/admin/cinemas{suffix}",
            headers=self.headers,
            json=payload.model_dump(mode="json"),
        )

    def save_auditorium(self, payload):
        return self.service.request(
            "POST",
            f"{self.base_url}/admin/auditoriums",
            headers=self.headers,
            json=payload.model_dump(mode="json"),
        )

    def save_screening(self, payload, screening_id: str | None = None):
        method = "PUT" if screening_id else "POST"
        suffix = f"/{quote(screening_id, safe='')}" if screening_id else ""
        return self.service.request(
            method,
            f"{self.base_url}/admin/screenings{suffix}",
            headers=self.headers,
            json=payload.model_dump(mode="json"),
        )

    def delete_screening(self, screening_id: str):
        return self.service.request(
            "DELETE",
            f"{self.base_url}/admin/screenings/{quote(screening_id, safe='')}",
            headers=self.headers,
        )

    def save_concession(self, payload, concession_id: str | None = None):
        method = "PUT" if concession_id else "POST"
        suffix = f"/{quote(concession_id, safe='')}" if concession_id else ""
        return self.service.request(
            method,
            f"{self.base_url}/admin/concessions{suffix}",
            headers=self.headers,
            json=payload.model_dump(mode="json"),
        )

    def delete_concession(self, concession_id: str):
        return self.service.request(
            "DELETE",
            f"{self.base_url}/admin/concessions/{quote(concession_id, safe='')}",
            headers=self.headers,
        )

    def save_promotion(self, payload, promotion_id: str | None = None):
        method = "PUT" if promotion_id else "POST"
        suffix = f"/{quote(promotion_id, safe='')}" if promotion_id else ""
        return self.service.request(
            method,
            f"{self.base_url}/admin/promotions{suffix}",
            headers=self.headers,
            json=payload.model_dump(mode="json"),
        )

    def delete_promotion(self, promotion_id: str):
        return self.service.request(
            "DELETE",
            f"{self.base_url}/admin/promotions/{quote(promotion_id, safe='')}",
            headers=self.headers,
        )

    def save_blog_post(self, payload, post_id: str | None = None):
        method = "PUT" if post_id else "POST"
        suffix = f"/{quote(post_id, safe='')}" if post_id else ""
        return self.service.request(
            method,
            f"{self.base_url}/admin/blog-posts{suffix}",
            headers=self.headers,
            json=payload.model_dump(mode="json"),
        )

    def delete_blog_post(self, post_id: str):
        return self.service.request(
            "DELETE",
            f"{self.base_url}/admin/blog-posts/{quote(post_id, safe='')}",
            headers=self.headers,
        )


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


PAYMENT_GRACE = timedelta(seconds=60)


def database_time(connection):
    return connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]


def require_owner(row, viewer):
    if not row or (row["account_id"] and row["account_id"] != viewer.account_id):
        raise HTTPException(404, "Không tìm thấy đơn")
    if row["hold_owner"] and row["hold_owner"] != viewer.history_key:
        raise HTTPException(404, "Không tìm thấy đơn")


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

    def execute(self, request: CheckoutRequest, key: UUID, viewer: BookingViewer, *, draft=False):
        labels = sorted(set(request.seats))
        if len(labels) != len(request.seats):
            raise HTTPException(422, "Danh sách ghế bị trùng")
        customer = (request.customer_name or "").strip() or None
        promo_code, concession_requests = self._normalize(request, viewer)
        fingerprint_parts = [request.screening_id, labels, customer]
        if concession_requests or promo_code or request.redeem_points:
            fingerprint_parts.extend([concession_requests, promo_code, request.redeem_points])
        if draft:
            fingerprint_parts.append("seat-hold")
        data = json.dumps(fingerprint_parts, ensure_ascii=False)
        fingerprint = hashlib.sha256(data.encode()).hexdigest()

        with self.db.transaction() as connection:
            if existing := self._existing(connection, key, fingerprint, viewer):
                return existing

        screening = self.catalog.screening(request.screening_id)
        items = self._items(promo_code, concession_requests)
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
            conflicts = [
                seat["label"]
                for seat in rows
                if seat["status"] == "SOLD" or (seat["status"] == "HELD" and seat["expires_at"] > now)
            ]
            if conflicts:
                raise HTTPException(409, f"Ghế {', '.join(conflicts)} vừa được giữ hoặc bán.")

            seat_amount = self.pricing.total(screening["starts_at"], screening["base_price"], rows)
            quote = self._price(connection, seat_amount, items, request, viewer)
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
                **quote,
                "hold_owner": viewer.history_key if draft else None,
                "checkout_phase": "DRAFT" if draft else "LEGACY",
                "expires_at": min(now + self.hold_duration, screening["starts_at"]),
            }
            self.bookings.insert(connection, booking)
            self.seats.hold(connection, booking)
            self._redeem(connection, viewer, booking_id, quote["points_redeemed"], screening["title"])
            if viewer.history_key:
                self.bookings.save(connection, viewer.history_key, booking["id"])
            return self.bookings.detail(connection, booking["id"], viewer)

    def _normalize(self, request, viewer):
        promo_code = (request.promo_code or "").strip().upper() or None
        concession_requests = sorted(
            [(item.id, item.quantity) for item in request.concessions],
            key=lambda entry: entry[0],
        )
        if len({cid for cid, _ in concession_requests}) != len(concession_requests):
            raise HTTPException(422, "Danh sách bắp nước bị trùng")
        if request.redeem_points > 0 and not viewer.account_id:
            raise HTTPException(401, "Vui lòng đăng nhập để sử dụng điểm D-Star.")

        return promo_code, concession_requests

    def _items(self, promo_code, concession_requests):
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

        return concession_items, concessions_amount, promo, promo_code

    def _price(self, connection, seat_amount, items, request, viewer):
        concession_items, concessions_amount, promo, promo_code = items
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
        return {
            "concessions": concession_items,
            "concessions_amount": concessions_amount,
            "discount_amount": discount_amount,
            "promo_code": promo_code,
            "points_redeemed": points_used,
            "amount": final_amount,
        }

    def _redeem(self, connection, viewer, booking_id, points_used, title):
        if viewer.account_id and points_used > 0:
            self.accounts.record_point_transaction(
                connection,
                viewer.account_id,
                booking_id,
                "REDEEM",
                -points_used,
                f"Đổi {points_used} Star cho đơn {title}",
            )

    def options(self, booking_id, options: BookingOptions, viewer, *, commit):
        promo_code, concessions = self._normalize(options, viewer)
        signature = hashlib.sha256(
            json.dumps([concessions, promo_code, options.redeem_points]).encode()
        ).hexdigest()

        def check(connection):
            row = self.bookings.lock(connection, booking_id)
            require_owner(row, viewer)
            if row["status"] != "HELD" or row["expires_at"] <= database_time(connection):
                raise HTTPException(409, "Đơn đã hết thời hạn giữ ghế.")
            if row["checkout_phase"] != "DRAFT" and not (
                commit and row["checkout_phase"] == "READY" and row["options_hash"] == signature
            ):
                raise HTTPException(409, "Đơn đã chốt giá. Hãy mở lại đơn để tiếp tục.")
            return row

        with self.db.transaction() as connection:
            row = check(connection)
            if row["checkout_phase"] == "READY":
                return self.bookings.detail(connection, booking_id, viewer)
        items = self._items(promo_code, concessions)
        with self.db.transaction() as connection:
            row = check(connection)
            if row["checkout_phase"] == "READY":
                return self.bookings.detail(connection, booking_id, viewer)
            quote = self._price(connection, row["amount"], items, options, viewer)
            if not commit:
                return quote
            self._redeem(connection, viewer, booking_id, quote["points_redeemed"], row["movie_title"])
            connection.execute(
                """
                UPDATE cinema_booking.bookings SET checkout_phase = 'READY', options_hash = %(signature)s,
                    amount = %(amount)s, concessions = %(concessions)s, concessions_amount = %(concessions_amount)s,
                    discount_amount = %(discount_amount)s, promo_code = %(promo_code)s,
                    points_redeemed = %(points_redeemed)s WHERE id = %(id)s
            """,
                {
                    **quote,
                    "id": booking_id,
                    "signature": signature,
                    "concessions": Jsonb(quote["concessions"]),
                },
            )
            return self.bookings.detail(connection, booking_id, viewer)

    def _existing(self, connection, key, fingerprint, viewer):
        existing = self.bookings.by_key(connection, key)
        if existing:
            require_owner(existing, viewer)
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
        with self.db.transaction() as connection:
            booking = self.bookings.lock(connection, booking_id)
            require_owner(booking, viewer)
            if booking["checkout_phase"] == "LEGACY" or booking["attempt_key"]:
                payment = payment_client.find(booking_id)
                if payment["status"] not in {"PENDING", "DECLINED"} or (
                    booking["attempt_key"] and payment["last_attempt"] != str(booking["attempt_key"])
                ):
                    raise HTTPException(409, "Giao dịch thanh toán đang xử lý hoặc đã hoàn tất.")
            if booking["status"] != "HELD":
                raise HTTPException(409, "Đơn này không còn ở trạng thái giữ ghế.")
            self.seats.lock(connection, booking["screening_id"], booking["seats"])
            self.seats.release(connection, booking)
            self.bookings.cancel(connection, booking["id"])
            self._restore_points(connection, booking)
            return self.bookings.detail(connection, booking["id"], viewer)

    def payment_session(self, booking_id, viewer, payment_client):
        with self.db.transaction() as connection:
            row = self.bookings.lock(connection, booking_id)
            require_owner(row, viewer)
            if (
                row["checkout_phase"] != "READY"
                or row["status"] != "HELD"
                or row["expires_at"] <= database_time(connection)
            ):
                raise HTTPException(409, "Đơn chưa sẵn sàng để thanh toán.")
            amount = row["amount"]
        return payment_client.create(booking_id, amount)

    def begin_payment(self, booking_id, key, request, viewer, payment_client):
        with self.db.transaction() as connection:
            row = self.bookings.lock(connection, booking_id)
            require_owner(row, viewer)
            if row["checkout_phase"] == "LEGACY":
                return payment_client.simulate(booking_id, key, request)
            seats = self.seats.lock(connection, row["screening_id"], row["seats"])
            now = database_time(connection)
            if row["checkout_phase"] != "READY":
                raise HTTPException(409, "Hãy chốt giá trước khi thanh toán.")
            if (
                row["status"] != "HELD"
                or row["expires_at"] <= now
                or any(seat["booking_id"] != booking_id for seat in seats)
            ):
                raise HTTPException(409, "Đơn không còn giữ ghế.")
            pay_by = row["pay_by"] or row["expires_at"]
            if row["attempt_key"] != key and now >= pay_by:
                raise HTTPException(409, "Đã hết thời gian bắt đầu thanh toán.")
            # Reserve the confirmation window once, even when the client retries.
            if row["attempt_key"] != key:
                if row["attempt_key"]:
                    previous = payment_client.find(booking_id)
                    if previous["status"] != "DECLINED" or previous["last_attempt"] != str(
                        row["attempt_key"]
                    ):
                        raise HTTPException(409, "Đang chờ kết quả lần thanh toán trước.")
                deadline = min(row["starts_at"], pay_by + PAYMENT_GRACE)
                connection.execute(
                    """
                    UPDATE cinema_booking.bookings SET attempt_key = %s, pay_by = %s, expires_at = %s
                    WHERE id = %s
                """,
                    (key, pay_by, deadline, booking_id),
                )
                connection.execute(
                    """
                    UPDATE cinema_booking.screening_seats SET expires_at = %s
                    WHERE booking_id = %s AND status = 'HELD'
                """,
                    (deadline, booking_id),
                )
        # A lost response can be retried with the same key against the same session.
        return payment_client.simulate(booking_id, key, request)

    def ticket(self, code: UUID):
        with self.db.transaction() as connection:
            ticket = self.tickets.find(connection, code)
            if not ticket:
                raise HTTPException(404, "Không tìm thấy vé")
            return ticket

    def check_in_ticket(self, code: UUID, staff_account_id: UUID):
        with self.db.transaction() as connection:
            ticket = self.tickets.lock_ticket(connection, code)
            if not ticket:
                raise HTTPException(404, "Không tìm thấy mã vé này.")
            if ticket["checked_in_at"] is not None:
                raise HTTPException(409, "Vé này đã được soát vào rạp trước đó.")
            stamped = self.tickets.mark_checked_in(connection, code, staff_account_id)
            ticket["checked_in_at"] = stamped["checked_in_at"]
            return ticket

    def admin_overview(self):
        with self.db.transaction() as connection:
            return self.bookings.admin_overview(connection)

    def admin_bookings(self, status_filter: str | None = None, query: str | None = None):
        with self.db.transaction() as connection:
            return self.bookings.admin_bookings(connection, status_filter, query)

    def ensure_screening_deletable(self, screening_id: str):
        with self.db.transaction() as connection:
            if self.bookings.has_active_bookings_for_screening(connection, screening_id):
                raise HTTPException(
                    409,
                    "Không thể xóa suất chiếu đang giữ ghế hoặc đã bán vé.",
                )

    def reconcile_payments(self, payment_client):
        # Check near-deadline payments even when the browser is closed or the event is delayed.
        with self.db.transaction() as connection:
            pending = connection.execute("""
                SELECT id FROM cinema_booking.bookings WHERE status = 'HELD' AND attempt_key IS NOT NULL
                    AND pay_by <= statement_timestamp() AND expires_at > statement_timestamp()
            """).fetchall()
        for row in pending:
            try:
                payment = payment_client.find(row["id"])
            except HTTPException:
                continue
            if payment["status"] == "SUCCEEDED":
                self.payment_succeeded(
                    PaymentEvent(
                        booking_id=row["id"],
                        payment_id=payment["id"],
                        amount=payment["amount"],
                    )
                )
        return False

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
