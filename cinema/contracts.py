from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

SeatLabel = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,2}[1-9][0-9]?$")]
SlugId = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")]


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


class AdminMovieInput(BaseModel):
    id: SlugId
    title: str = Field(min_length=1, max_length=140)
    genre: str = Field(min_length=1, max_length=100)
    duration_minutes: int = Field(gt=0, le=600)
    synopsis: str = Field(min_length=1, max_length=2000)
    release_status: Literal["NOW_SHOWING", "COMING_SOON"] = "NOW_SHOWING"
    age_rating: Literal["P", "K", "T13", "T16", "T18"] = "P"
    rating: float = Field(default=8.5, ge=0.0, le=10.0)
    release_date: date | None = None
    director: str = Field(default="", max_length=140)
    cast_list: str = Field(default="", max_length=300)
    country: str = Field(default="Việt Nam", max_length=80)
    trailer_url: str = Field(default="", max_length=300)
    poster_url: str = Field(default="", max_length=300)
    is_imax: bool = False


class AdminCinemaInput(BaseModel):
    id: SlugId
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=60)
    address: str = Field(min_length=1, max_length=240)
    hotline: str = Field(default="1900 2224", max_length=40)
    formats: list[str] = Field(default_factory=lambda: ["2D"])
    opening_hours: str = Field(default="08:30 - 23:30", max_length=60)


class AdminAuditoriumInput(BaseModel):
    id: SlugId
    name: str = Field(min_length=1, max_length=120)
    cinema_id: str = Field(min_length=1, max_length=64)
    screen_format: str = Field(default="2D Phụ đề", max_length=60)
    standard_rows: int = Field(default=3, ge=1, le=10)
    vip_rows: int = Field(default=1, ge=0, le=6)
    couple_seats: int = Field(default=4, ge=0, le=8)
    seats_per_row: int = Field(default=8, ge=4, le=16)


class AdminScreeningInput(BaseModel):
    id: str | None = Field(default=None, max_length=100)
    movie_id: str = Field(min_length=1, max_length=64)
    auditorium_id: str = Field(min_length=1, max_length=64)
    starts_at: datetime
    base_price: int = Field(gt=0, le=2_000_000)
    format: str = Field(default="2D Phụ đề", max_length=60)
    is_special: bool = False


class AdminConcessionInput(BaseModel):
    id: SlugId
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=300)
    price: int = Field(gt=0, le=2_000_000)
    category: str = Field(default="Combo", max_length=60)
    badge: str | None = Field(default=None, max_length=40)
    active: bool = True
    sort_order: int = 0


class AdminPromotionInput(BaseModel):
    id: SlugId
    title: str = Field(min_length=1, max_length=180)
    tag: str = Field(min_length=1, max_length=60)
    summary: str = Field(min_length=1, max_length=400)
    code: str | None = Field(default=None, max_length=32)
    discount_type: Literal["PERCENT", "FIXED", "INFO"] = "FIXED"
    discount_value: int = Field(default=0, ge=0, le=1_000_000)
    min_amount: int = Field(default=0, ge=0, le=10_000_000)
    valid_until: str = Field(default="31/12/2026", max_length=80)
    details: str = Field(default="", max_length=1000)
    active: bool = True
    sort_order: int = 0

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        if isinstance(value, str):
            cleaned = value.strip().upper()
            return cleaned or None
        return value


class AdminBlogPostInput(BaseModel):
    id: SlugId
    category: Literal["review", "blog"] = "review"
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=5000)
    author: str = Field(default="Ban Biên Tập DUT Cinema", max_length=100)
    published_label: str = Field(default="Vừa xong", max_length=60)
    movie_id: str | None = Field(default=None, max_length=64)
    views: int = Field(default=100, ge=0)
    sort_order: int = 0

    @field_validator("movie_id", mode="before")
    @classmethod
    def clean_movie_id(cls, value):
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class AdminRoleUpdate(BaseModel):
    role: Literal["USER", "STAFF", "ADMIN"]
