from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cinema.booking.domain import (
    BookingConfirmed,
    BookingObservers,
    ConfirmedState,
    ExpiredState,
    HeldState,
    Pricing,
    SeatMapObserver,
    TicketBuilder,
    WeekdayPricing,
    WeekendPricing,
)
from cinema.payment.gateway import DemoPaymentAdapter, DemoProcessor


def test_pricing_uses_local_day_and_seat_type():
    pricing = Pricing(WeekdayPricing(), WeekendPricing())
    seats = [{"seat_type": "STANDARD"}, {"seat_type": "PREMIUM"}]
    friday_at_six_pm_utc = datetime(2026, 11, 20, 18, tzinfo=UTC)
    assert pricing.total(friday_at_six_pm_utc, 90000, seats) == 230000
    assert pricing.total(friday_at_six_pm_utc - timedelta(days=1), 90000, seats) == 200000


def test_state_decides_late_payment_at_exact_deadline():
    expiry = datetime.now(UTC)
    payment = uuid4()
    assert HeldState().payment_action({"expires_at": expiry}, payment, expiry) == "expire_and_refund"
    assert (
        HeldState().payment_action({"expires_at": expiry}, payment, expiry - timedelta(seconds=1))
        == "confirm"
    )
    assert ExpiredState().payment_action({}, payment, expiry) == "refund"
    assert ConfirmedState().payment_action({"payment_id": payment}, payment, expiry) == "ignore"


def test_builder_and_independent_observers():
    booking_id = uuid4()
    ticket = TicketBuilder(booking_id, "screening", "A5").for_customer("Minh").build()
    assert ticket["booking_id"] == booking_id
    assert ticket["customer_name"] == "Minh"
    assert TicketBuilder(booking_id, "screening", "A6").build()["customer_name"] is None

    seat_updates = SeatMapObserver()
    events = []
    event = BookingConfirmed(booking_id, "screening", 2)
    BookingObservers([seat_updates, events.append]).notify(event)
    assert seat_updates.revision("screening") == 1
    assert events == [event]


def test_adapter_maps_provider_codes():
    gateway = DemoPaymentAdapter(DemoProcessor())
    payment, attempt = uuid4(), uuid4()
    approved = gateway.charge(payment, attempt, 90000, "success")
    declined = gateway.charge(payment, attempt, 90000, "decline")
    assert approved.approved
    assert not declined.approved
    assert gateway.refund(payment, approved.reference, 90000).startswith("REFUND-")
