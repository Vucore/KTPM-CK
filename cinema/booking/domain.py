from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)
LOCAL_TIME = ZoneInfo("Asia/Ho_Chi_Minh")
MIN_PAYABLE_AMOUNT = 10000
POINT_VALUE_VND = 1000


class PricingStrategy:
    def price(self, base_price: int, seats: list[dict]) -> int:
        total = 0
        standard = self.standard_price(base_price)
        for seat in seats:
            seat_type = seat["seat_type"]
            if seat_type == "COUPLE":
                total += standard * 2 + 15000
            elif seat_type == "PREMIUM":
                total += standard + 20000
            else:
                total += standard
        return total

    def standard_price(self, base_price: int) -> int:
        raise NotImplementedError


class WeekdayPricing(PricingStrategy):
    def standard_price(self, base_price: int) -> int:
        return base_price


class WeekendPricing(PricingStrategy):
    def standard_price(self, base_price: int) -> int:
        return base_price + 15000


class Pricing:
    def __init__(self, weekday: PricingStrategy, weekend: PricingStrategy):
        self.weekday = weekday
        self.weekend = weekend

    def total(self, starts_at: datetime, base_price: int, seats: list[dict]):
        strategy = self.weekend if starts_at.astimezone(LOCAL_TIME).weekday() >= 5 else self.weekday
        return strategy.price(base_price, seats)


def member_tier(total_spent: int) -> dict:
    if total_spent >= 4_000_000:
        return {"name": "X-Star", "next_tier": None, "remaining": 0, "progress": 100}
    if total_spent >= 1_500_000:
        remaining = 4_000_000 - total_spent
        progress = int((total_spent - 1_500_000) * 100 / 2_500_000)
        return {"name": "D-Star", "next_tier": "X-Star", "remaining": remaining, "progress": progress}
    remaining = 1_500_000 - total_spent
    progress = int(total_spent * 100 / 1_500_000)
    return {"name": "Member", "next_tier": "D-Star", "remaining": remaining, "progress": progress}


def calculate_discount(
    subtotal: int,
    promo: dict | None,
    redeem_points: int,
    available_points: int,
) -> tuple[int, int]:
    discount = 0
    if promo:
        if subtotal < promo["min_amount"]:
            raise ValueError(f"Mã ưu đãi áp dụng cho đơn từ {promo['min_amount']:,} ₫.".replace(",", "."))
        if promo["discount_type"] == "PERCENT":
            discount += (subtotal * promo["discount_value"]) // 100
        elif promo["discount_type"] == "FIXED":
            discount += promo["discount_value"]

    points_used = 0
    if redeem_points > 0:
        if redeem_points > available_points:
            raise ValueError("Số điểm D-Star hiện tại không đủ để quy đổi.")
        points_used = redeem_points
        discount += points_used * POINT_VALUE_VND

    max_discount = max(0, subtotal - MIN_PAYABLE_AMOUNT)
    discount = min(discount, max_discount)
    return discount, points_used


class HeldState:
    def payment_action(self, booking: dict, payment_id: UUID, now: datetime):
        return "confirm" if now < booking["expires_at"] else "expire_and_refund"


class ConfirmedState:
    def payment_action(self, booking: dict, payment_id: UUID, now: datetime):
        return "ignore" if booking["payment_id"] == payment_id else "refund"


class ExpiredState:
    def payment_action(self, booking: dict, payment_id: UUID, now: datetime):
        return "refund"


class CancelledState:
    def payment_action(self, booking: dict, payment_id: UUID, now: datetime):
        return "refund"


STATES = {
    "HELD": HeldState(),
    "CONFIRMED": ConfirmedState(),
    "EXPIRED": ExpiredState(),
    "CANCELLED": CancelledState(),
}


class TicketBuilder:
    def __init__(self, booking_id: UUID, screening_id: str, seat: str):
        self.booking_id = booking_id
        self.screening_id = screening_id
        self.seat = seat
        self.customer_name = None

    def for_customer(self, name: str | None) -> TicketBuilder:
        self.customer_name = name
        return self

    def build(self):
        return {
            "code": uuid4(),
            "booking_id": self.booking_id,
            "screening_id": self.screening_id,
            "seat": self.seat,
            "customer_name": self.customer_name,
        }


@dataclass(frozen=True)
class BookingConfirmed:
    booking_id: UUID
    screening_id: str
    seat_count: int


class BookingObservers:
    def __init__(self, listeners):
        self.listeners = tuple(listeners)

    def notify(self, event: BookingConfirmed):
        for listener in self.listeners:
            try:
                listener(event)
            except Exception:
                LOGGER.exception("Booking observer failed after commit")


class SeatMapObserver:
    def __init__(self):
        self.versions: dict[str, int] = {}
        self.lock = Lock()

    def __call__(self, event: BookingConfirmed):
        with self.lock:
            self.versions[event.screening_id] = self.versions.get(event.screening_id, 0) + 1

    def revision(self, screening_id: str):
        with self.lock:
            return self.versions.get(screening_id, 0)


def log_confirmation(event: BookingConfirmed):
    logging.getLogger("uvicorn.error.cinema").info(
        "booking_confirmed screening=%s seats=%s",
        event.screening_id,
        event.seat_count,
    )
