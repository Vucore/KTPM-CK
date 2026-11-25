from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

SeatLabel = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,2}[1-9][0-9]?$")]


class ConcessionOrderItem(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=20)


class CheckoutRequest(BaseModel):
    screening_id: str = Field(min_length=1, max_length=100)
    seats: list[SeatLabel] = Field(min_length=1, max_length=8)
    customer_name: str | None = Field(default=None, max_length=80)
    concessions: list[ConcessionOrderItem] = Field(default_factory=list, max_length=20)
    promo_code: str | None = Field(default=None, max_length=32)
    redeem_points: int = Field(default=0, ge=0, le=5000)


class CreatePayment(BaseModel):
    booking_id: UUID
    amount: int = Field(gt=0, le=2147483647)


class SimulatePayment(BaseModel):
    outcome: Literal["success", "decline"]
    delay_seconds: int = Field(default=0, ge=0, le=120)


class PaymentEvent(CreatePayment):
    payment_id: UUID
