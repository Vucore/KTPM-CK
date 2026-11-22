from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ChargeResult:
    approved: bool
    reference: str


class PaymentGateway(Protocol):
    def charge(self, payment_id: UUID, request_key: UUID, amount: int, outcome: str) -> ChargeResult: ...

    def refund(self, payment_id: UUID, provider_reference: str, amount: int) -> str: ...


class DemoProcessor:
    def capture(self, record: dict):
        return {"code": "00" if record["approved"] else "05", "receipt": f"DEMO-{record['order']}"}

    def reverse(self, record: dict):
        return {"credit_note": f"REFUND-{record['receipt']}"}


class DemoPaymentAdapter:
    def __init__(self, processor: DemoProcessor):
        self.processor = processor

    def charge(self, payment_id: UUID, request_key: UUID, amount: int, outcome: str):
        reply = self.processor.capture(
            {
                "order": str(payment_id),
                "attempt": str(request_key),
                "value": amount,
                "approved": outcome == "success",
            }
        )
        return ChargeResult(reply["code"] == "00", reply["receipt"])

    def refund(self, payment_id: UUID, provider_reference: str, amount: int):
        return self.processor.reverse(
            {
                "order": str(payment_id),
                "receipt": provider_reference,
                "value": amount,
            }
        )["credit_note"]
