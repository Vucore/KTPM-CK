from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)
LOCAL_TIME = ZoneInfo("Asia/Ho_Chi_Minh")


class PricingStrategy:
    def price(self, base_price: int, seats: list[dict]) -> int:
        return sum(
            self.standard_price(base_price) + (20000 if seat["seat_type"] == "PREMIUM" else 0)
            for seat in seats
        )

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


class HeldState:
    def payment_action(self, booking: dict, payment_id: UUID, now: datetime):
        return "confirm" if now < booking["expires_at"] else "expire_and_refund"


class ConfirmedState:
    def payment_action(self, booking: dict, payment_id: UUID, now: datetime):
        return "ignore" if booking["payment_id"] == payment_id else "refund"


class ExpiredState:
    def payment_action(self, booking: dict, payment_id: UUID, now: datetime):
        return "refund"


STATES = {"HELD": HeldState(), "CONFIRMED": ConfirmedState(), "EXPIRED": ExpiredState()}


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
