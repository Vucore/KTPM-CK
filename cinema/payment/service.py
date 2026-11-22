from fastapi import HTTPException

from cinema.common import Database
from cinema.contracts import PaymentEvent
from cinema.messaging import Outbox, RejectedEvent
from cinema.payment.gateway import PaymentGateway
from cinema.payment.repository import PaymentRepository


class PaymentService:
    def __init__(self, db: Database, repository: PaymentRepository, gateway: PaymentGateway, outbox: Outbox):
        self.db = db
        self.repository = repository
        self.gateway = gateway
        self.outbox = outbox

    def create(self, request):
        with self.db.transaction() as connection:
            payment = self.repository.create(connection, request.booking_id, request.amount)
            if payment["amount"] != request.amount:
                raise HTTPException(409, "Số tiền không khớp với phiên thanh toán")
            return payment

    def find(self, booking_id):
        with self.db.transaction() as connection:
            return self._find(connection, booking_id)

    def _find(self, connection, booking_id, *, lock=False):
        payment = self.repository.find(connection, booking_id, lock=lock)
        if not payment:
            raise HTTPException(404, "Không tìm thấy phiên thanh toán")
        return payment

    def simulate(self, booking_id, key, request):
        with self.db.transaction() as connection:
            payment = self._find(connection, booking_id, lock=True)
            previous = self.repository.attempt(connection, payment["id"], key)
            if previous:
                if (
                    previous["outcome"] != request.outcome
                    or previous["delay_seconds"] != request.delay_seconds
                ):
                    raise HTTPException(409, "Idempotency-Key đã được dùng với kết quả hoặc độ trễ khác")
                return payment
            if payment["status"] not in {"PENDING", "DECLINED"}:
                raise HTTPException(409, "Phiên thanh toán đang xử lý hoặc đã kết thúc")
            return self.repository.schedule(connection, payment["id"], key, request)

    def process_one(self):
        with self.db.transaction() as connection:
            payment = self.repository.next_due(connection)
            if not payment:
                return False
            result = self.gateway.charge(
                payment["id"],
                payment["request_key"],
                payment["amount"],
                payment["outcome"],
            )
            self.repository.finish(connection, payment, result)
            if result.approved:
                self.outbox.add(
                    connection,
                    "payment.succeeded",
                    PaymentEvent(
                        payment_id=payment["id"],
                        booking_id=payment["booking_id"],
                        amount=payment["amount"],
                    ),
                )
            return True

    def refund(self, event: PaymentEvent):
        with self.db.transaction() as connection:
            payment = self.repository.find(connection, event.booking_id, lock=True)
            if not payment or payment["id"] != event.payment_id or payment["amount"] != event.amount:
                raise RejectedEvent("Refund does not match payment")
            if payment["status"] == "REFUNDED":
                return
            if payment["status"] != "SUCCEEDED":
                raise RejectedEvent("Payment is not eligible for refund")
            reference = self.gateway.refund(payment["id"], payment["provider_reference"], payment["amount"])
            self.repository.refund(connection, payment["id"], reference)
