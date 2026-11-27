from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from cinema.booking.domain import (
    BookingConfirmed,
    BookingObservers,
    CancelledState,
    ConfirmedState,
    ExpiredState,
    HeldState,
    Pricing,
    SeatMapObserver,
    TicketBuilder,
    WeekdayPricing,
    WeekendPricing,
    calculate_discount,
    member_tier,
)
from cinema.contracts import AdminBlogPostInput, AdminMovieInput, AdminPromotionInput
from cinema.payment.gateway import DemoPaymentAdapter, DemoProcessor


def test_pricing_uses_local_day_and_seat_type():
    pricing = Pricing(WeekdayPricing(), WeekendPricing())
    seats = [{"seat_type": "STANDARD"}, {"seat_type": "PREMIUM"}]
    friday_at_six_pm_utc = datetime(2026, 11, 20, 18, tzinfo=UTC)
    assert pricing.total(friday_at_six_pm_utc, 90000, seats) == 230000
    assert pricing.total(friday_at_six_pm_utc - timedelta(days=1), 90000, seats) == 200000

    couple_seats = [{"seat_type": "COUPLE"}]
    assert pricing.total(friday_at_six_pm_utc - timedelta(days=1), 90000, couple_seats) == 195000
    assert pricing.total(friday_at_six_pm_utc, 90000, couple_seats) == 225000


def test_state_decides_late_payment_at_exact_deadline():
    expiry = datetime.now(UTC)
    payment = uuid4()
    assert HeldState().payment_action({"expires_at": expiry}, payment, expiry) == "expire_and_refund"
    assert (
        HeldState().payment_action({"expires_at": expiry}, payment, expiry - timedelta(seconds=1))
        == "confirm"
    )
    assert ExpiredState().payment_action({}, payment, expiry) == "refund"
    assert CancelledState().payment_action({}, payment, expiry) == "refund"
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


def test_calculate_discount_and_member_tiers():
    promo_percent = {"discount_type": "PERCENT", "discount_value": 20, "min_amount": 100000}
    discount, used = calculate_discount(200000, promo_percent, 10, 50)
    assert discount == 50000
    assert used == 10

    promo_fixed = {"discount_type": "FIXED", "discount_value": 25000, "min_amount": 75000}
    assert calculate_discount(100000, promo_fixed, 0, 0) == (25000, 0)

    # Cap ensures final payable amount remains >= 10,000 VND
    assert calculate_discount(80000, promo_fixed, 100, 100) == (70000, 45)

    with pytest.raises(ValueError):
        calculate_discount(50000, promo_fixed, 0, 0)
    with pytest.raises(ValueError):
        calculate_discount(100000, None, 10, 5)

    assert member_tier(0)["name"] == "Member"
    assert member_tier(1_500_000)["name"] == "D-Star"
    assert member_tier(4_000_000)["name"] == "X-Star"


def test_admin_contract_validators():
    promo = AdminPromotionInput(
        id="promo-test",
        title="Ưu đãi thử nghiệm",
        tag="Test",
        summary="Giảm 20k",
        code="  dut20test ",
    )
    assert promo.code == "DUT20TEST"

    info_promo = AdminPromotionInput(
        id="promo-info",
        title="Tin tức",
        tag="Info",
        summary="Không mã",
        code="   ",
        discount_type="INFO",
    )
    assert info_promo.code is None

    blog = AdminBlogPostInput(
        id="blog-test",
        title="Bài viết mới",
        summary="Tóm tắt",
        content="Nội dung",
        movie_id="  ",
    )
    assert blog.movie_id is None

    movie = AdminMovieInput(
        id="new-film",
        title="Phim Mới",
        genre="Hành động",
        duration_minutes=120,
        synopsis="Nội dung phim mới",
        age_rating="T16",
    )
    assert movie.id == "new-film"

