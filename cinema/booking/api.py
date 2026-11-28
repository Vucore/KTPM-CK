import asyncio
import io
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_hex
from typing import Annotated
from uuid import UUID

import httpx
import qrcode
import qrcode.image.svg
from argon2 import PasswordHasher
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from cinema.booking.auth import (
    SESSION_LIFETIME,
    AuthService,
    BookingViewer,
    Credentials,
    PasswordChange,
    ProfileUpdate,
    SignUp,
    token_digest,
)
from cinema.booking.auth_repository import AccountRepository
from cinema.booking.domain import (
    BookingObservers,
    Pricing,
    SeatMapObserver,
    WeekdayPricing,
    WeekendPricing,
    log_confirmation,
)
from cinema.booking.repositories import BookingRepository, ScreeningSeatRepository, TicketRepository
from cinema.booking.seat_updates import SeatChangeListener
from cinema.booking.services import (
    BookingService,
    CatalogClient,
    CheckoutFacade,
    HoldSeatsUseCase,
    PaymentClient,
)
from cinema.common import Database, ServiceClient, Settings, configure_http
from cinema.contracts import (
    AdminAuditoriumInput,
    AdminBlogPostInput,
    AdminCinemaInput,
    AdminConcessionInput,
    AdminMovieInput,
    AdminPromotionInput,
    AdminRoleUpdate,
    AdminScreeningInput,
    BookingOptions,
    CheckoutRequest,
    SeatHold,
    SimulatePayment,
)
from cinema.messaging import Background, Outbox, RabbitWorker

WEB = Path(__file__).resolve().parent.parent / "web"
RequestKey = Annotated[UUID, Header(alias="Idempotency-Key")]
ACCOUNT_COOKIE = "chon_suat_session"
BROWSER_COOKIE = "chon_suat_browser"


def cookie_token(request: Request, name: str) -> str | None:
    value = request.cookies.get(name, "")
    return value if re.fullmatch(r"[0-9a-f]{64}", value) else None


def set_cookie(request: Request, response: Response, name: str, token: str, lifetime: int):
    response.set_cookie(
        name, token, max_age=lifetime, secure=request.url.scheme == "https", httponly=True, samesite="lax",
    )


def browser_token(request: Request, response: Response) -> str:
    if token := cookie_token(request, BROWSER_COOKIE):
        return token
    token = token_hex(32)
    request.state.new_browser_token = token
    set_cookie(request, response, BROWSER_COOKIE, token, 365 * 24 * 60 * 60)
    return token


def require_same_origin(request: Request):
    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Yêu cầu phải đến từ cùng địa chỉ website")


def create_app(settings: Settings | None = None, downstream: httpx.BaseTransport | None = None):
    settings = settings or Settings.load("booking")
    db = Database(settings.database_url)
    http = httpx.Client(timeout=8, trust_env=False, transport=downstream)
    transport = ServiceClient(http)
    catalog = CatalogClient(transport, settings.catalog_url, settings.internal_key)
    payment = PaymentClient(transport, settings.payment_url, settings.internal_key)
    accounts_repo = AccountRepository()
    auth = AuthService(db, accounts_repo, PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1))
    bookings, seats, tickets = BookingRepository(), ScreeningSeatRepository(), TicketRepository()
    seat_updates = SeatMapObserver()
    hold = HoldSeatsUseCase(
        db,
        bookings,
        seats,
        Pricing(WeekdayPricing(), WeekendPricing()),
        catalog,
        settings.hold_seconds,
        accounts_repo,
    )
    checkout = CheckoutFacade(hold, payment)
    outbox = Outbox(db, "cinema_booking")
    service = BookingService(
        db, bookings, seats, tickets, outbox, BookingObservers([log_confirmation]), accounts_repo
    )
    worker = RabbitWorker(settings.rabbitmq_url, "payment.succeeded", outbox, service.payment_succeeded)

    @asynccontextmanager
    async def lifespan(app):
        db.pool.open()
        try:
            with (
                worker.background(),
                SeatChangeListener(settings.database_url, seat_updates).background(),
                Background("expire-bookings", service.expire_one),
                Background("check-payments", lambda: service.reconcile_payments(payment), idle_delay=3),
                Background("expire-auth", auth.expire, idle_delay=3600),
            ):
                yield
        finally:
            http.close()
            db.pool.close()

    app = FastAPI(title="Booking Service", lifespan=lifespan)
    configure_http(app, db)
    app.mount("/assets", StaticFiles(directory=WEB), name="assets")

    @app.middleware("http")
    async def persist_browser_cookie(request: Request, call_next):
        response = await call_next(request)
        if pending := getattr(request.state, "new_browser_token", None):
            existing = response.headers.getlist("set-cookie")
            if not any(header.startswith(f"{BROWSER_COOKIE}=") for header in existing):
                set_cookie(request, response, BROWSER_COOKIE, pending, 365 * 24 * 60 * 60)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        if request.url.path in {"/api/auth/login", "/api/auth/register"}:
            return JSONResponse(
                {"detail": "Hãy kiểm tra định dạng tên đăng nhập và độ dài mật khẩu."},
                status_code=422,
            )
        return await request_validation_exception_handler(request, error)

    def viewer(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        raw_browser = cookie_token(request, BROWSER_COOKIE)
        browser_key = f"browser:{token_digest(raw_browser)}" if raw_browser else None
        account = auth.current_account(cookie_token(request, ACCOUNT_COOKIE))
        if account:
            return BookingViewer(
                account["id"], f"account:{account['id']}", account.get("role", "USER"), browser_key
            )
        key = f"browser:{token_digest(browser_token(request, response))}"
        return BookingViewer(history_key=key, browser_key=key)

    def signed_in_account(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        account = auth.current_account(cookie_token(request, ACCOUNT_COOKIE))
        if not account:
            raise HTTPException(401, "Vui lòng đăng nhập để thực hiện thao tác này.")
        return account

    def staff_account(account: Annotated[dict, Depends(signed_in_account)]):
        if account.get("role") not in {"STAFF", "ADMIN"}:
            raise HTTPException(403, "Chức năng này chỉ dành cho Nhân viên soát vé hoặc Quản trị viên.")
        return account

    def admin_account(account: Annotated[dict, Depends(signed_in_account)]):
        if account.get("role") != "ADMIN":
            raise HTTPException(403, "Chức năng này chỉ dành cho Quản trị viên (ADMIN).")
        return account

    Viewer = Annotated[BookingViewer, Depends(viewer)]
    Account = Annotated[dict, Depends(signed_in_account)]
    StaffAccount = Annotated[dict, Depends(staff_account)]
    AdminAccount = Annotated[dict, Depends(admin_account)]
    same_origin = [Depends(require_same_origin)]

    def sign_in(authenticate, credentials, request, response):
        source = request.client.host if request.client else "unknown"
        account, token = authenticate(credentials, source, cookie_token(request, ACCOUNT_COOKIE))
        set_cookie(request, response, ACCOUNT_COOKIE, token, int(SESSION_LIFETIME.total_seconds()))
        response.headers["Cache-Control"] = "no-store"
        return {"account": account}

    @app.get("/", include_in_schema=False)
    def home(request: Request):
        response = FileResponse(
            WEB / "index.html", headers={"Cache-Control": "private, no-cache", "Referrer-Policy": "same-origin"},
        )
        browser_token(request, response)
        return response

    @app.post("/api/auth/register", status_code=201, dependencies=same_origin)
    def register(credentials: SignUp, request: Request, response: Response):
        return sign_in(auth.register, credentials, request, response)

    @app.post("/api/auth/login", dependencies=same_origin)
    def login(credentials: Credentials, request: Request, response: Response):
        return sign_in(auth.login, credentials, request, response)

    @app.get("/api/auth/session")
    def session(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return {"account": auth.current_account(cookie_token(request, ACCOUNT_COOKIE))}

    @app.get("/api/account/profile")
    def account_profile(account: Account):
        return auth.profile(account["id"])

    @app.patch("/api/account/profile", dependencies=same_origin)
    def update_profile(payload: ProfileUpdate, account: Account):
        return auth.update_profile(account["id"], payload)

    @app.post("/api/account/password", status_code=204, dependencies=same_origin)
    def change_password(payload: PasswordChange, request: Request, account: Account):
        source = request.client.host if request.client else "unknown"
        auth.change_password(
            account["id"],
            payload,
            source=source,
            current_token=cookie_token(request, ACCOUNT_COOKIE),
        )

    @app.post("/api/auth/logout", status_code=204, dependencies=same_origin)
    def logout(request: Request, response: Response):
        auth.logout(cookie_token(request, ACCOUNT_COOKIE))
        response.delete_cookie(ACCOUNT_COOKIE, secure=request.url.scheme == "https", httponly=True, samesite="lax")
        response.headers["Cache-Control"] = "no-store"

    @app.get("/api/screenings")
    def screenings():
        return catalog.upcoming()

    @app.get("/api/catalog/home")
    def catalog_home():
        return catalog.home()

    @app.get("/api/movies/{movie_id}")
    def movie_detail(movie_id: str):
        return catalog.movie(movie_id)

    @app.get("/api/screenings/{screening_id}/seats")
    def seat_map(screening_id: str):
        return service.seat_map(catalog.screening(screening_id))

    @app.get("/api/screenings/{screening_id}/updates")
    async def updates(screening_id: str, request: Request):
        async def stream():
            previous = None
            while not await request.is_disconnected():
                revision = seat_updates.revision(screening_id)
                if revision != previous:
                    yield f"data: {json.dumps(revision)}\n\n"
                    previous = revision
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.post("/api/holds", status_code=201, dependencies=same_origin)
    def reserve_seats(payload: SeatHold, key: RequestKey, current: Viewer):
        return hold.execute(CheckoutRequest(**payload.model_dump()), key, current, draft=True)

    @app.post("/api/bookings/{booking_id}/quote", dependencies=same_origin)
    def preview_options(booking_id: UUID, payload: BookingOptions, current: Viewer):
        return hold.options(booking_id, payload, current, commit=False)

    @app.post("/api/bookings/{booking_id}/prepare", dependencies=same_origin)
    def finalize_options(booking_id: UUID, payload: BookingOptions, current: Viewer):
        booking = hold.options(booking_id, payload, current, commit=True)
        return {"booking": booking, "payment": payment.create(booking_id, booking["amount"])}

    @app.post("/api/checkout", status_code=201, dependencies=same_origin)
    def start_checkout(payload: CheckoutRequest, key: RequestKey, current: Viewer):
        return checkout.start(payload, key, current)

    @app.get("/api/my-bookings")
    def my_bookings(current: Viewer):
        return {"scope": "account" if current.account_id else "browser", "bookings": service.saved_bookings(current)}

    @app.put("/api/my-bookings/{booking_id}", status_code=204, dependencies=same_origin)
    def save_booking(booking_id: UUID, current: Viewer):
        service.save_booking(booking_id, current)

    @app.delete("/api/my-bookings/{booking_id}", status_code=204, dependencies=same_origin)
    def forget_booking(booking_id: UUID, current: Viewer):
        service.forget_booking(booking_id, current)

    @app.get("/api/bookings/{booking_id}")
    def booking_detail(booking_id: UUID, current: Viewer):
        return service.detail(booking_id, current)

    @app.post("/api/bookings/{booking_id}/cancel", dependencies=same_origin)
    def cancel_booking(booking_id: UUID, current: Viewer):
        return service.cancel(booking_id, current, payment)

    @app.post("/api/bookings/{booking_id}/payment", dependencies=same_origin)
    def resume_payment(booking_id: UUID, current: Viewer):
        return service.payment_session(booking_id, current, payment)

    @app.get("/api/bookings/{booking_id}/payment")
    def payment_status(booking_id: UUID, current: Viewer):
        service.require_access(booking_id, current)
        return payment.find(booking_id)

    @app.post("/api/bookings/{booking_id}/payment/simulate", status_code=202, dependencies=same_origin)
    def simulate_payment(booking_id: UUID, request: SimulatePayment, key: RequestKey, current: Viewer):
        return service.begin_payment(booking_id, key, request, current, payment)

    @app.get("/api/tickets/{code}/qr.svg")
    def ticket_qr(code: UUID, current: Viewer):
        service.ticket(code, current)
        qr = qrcode.make(str(code), image_factory=qrcode.image.svg.SvgPathImage)
        buffer = io.BytesIO()
        qr.save(buffer)
        return Response(buffer.getvalue(), media_type="image/svg+xml")

    @app.get("/api/tickets/{code}")
    def ticket_detail(code: UUID, current: Viewer):
        return service.ticket(code, current)

    # ---------------- ADMIN & STAFF ENDPOINTS ----------------
    @app.get("/api/admin/overview")
    def admin_overview(admin: AdminAccount):
        return service.admin_overview()

    @app.get("/api/admin/bookings")
    def admin_bookings(staff: StaffAccount, status: str | None = None, q: str | None = None):
        return service.admin_bookings(status, q)

    @app.post("/api/admin/tickets/{code}/check-in", dependencies=same_origin)
    def admin_check_in_ticket(code: UUID, staff: StaffAccount):
        return service.check_in_ticket(code, staff["id"])

    @app.get("/api/admin/catalog")
    def admin_catalog(admin: AdminAccount):
        return catalog.admin_snapshot()

    @app.post("/api/admin/movies", status_code=201, dependencies=same_origin)
    def admin_create_movie(payload: AdminMovieInput, admin: AdminAccount):
        return catalog.save_movie(payload)

    @app.put("/api/admin/movies/{movie_id}", dependencies=same_origin)
    def admin_update_movie(movie_id: str, payload: AdminMovieInput, admin: AdminAccount):
        return catalog.save_movie(payload, movie_id)

    @app.delete("/api/admin/movies/{movie_id}", status_code=204, dependencies=same_origin)
    def admin_delete_movie(movie_id: str, admin: AdminAccount):
        catalog.delete_movie(movie_id)

    @app.post("/api/admin/cinemas", status_code=201, dependencies=same_origin)
    def admin_create_cinema(payload: AdminCinemaInput, admin: AdminAccount):
        return catalog.save_cinema(payload)

    @app.put("/api/admin/cinemas/{cinema_id}", dependencies=same_origin)
    def admin_update_cinema(cinema_id: str, payload: AdminCinemaInput, admin: AdminAccount):
        return catalog.save_cinema(payload, cinema_id)

    @app.post("/api/admin/auditoriums", status_code=201, dependencies=same_origin)
    def admin_create_auditorium(payload: AdminAuditoriumInput, admin: AdminAccount):
        return catalog.save_auditorium(payload)

    @app.post("/api/admin/screenings", status_code=201, dependencies=same_origin)
    def admin_create_screening(payload: AdminScreeningInput, admin: AdminAccount):
        return catalog.save_screening(payload)

    @app.put("/api/admin/screenings/{screening_id}", dependencies=same_origin)
    def admin_update_screening(screening_id: str, payload: AdminScreeningInput, admin: AdminAccount):
        return catalog.save_screening(payload, screening_id)

    @app.delete("/api/admin/screenings/{screening_id}", status_code=204, dependencies=same_origin)
    def admin_delete_screening(screening_id: str, admin: AdminAccount):
        service.ensure_screening_deletable(screening_id)
        catalog.delete_screening(screening_id)

    @app.post("/api/admin/concessions", status_code=201, dependencies=same_origin)
    def admin_create_concession(payload: AdminConcessionInput, admin: AdminAccount):
        return catalog.save_concession(payload)

    @app.put("/api/admin/concessions/{concession_id}", dependencies=same_origin)
    def admin_update_concession(concession_id: str, payload: AdminConcessionInput, admin: AdminAccount):
        return catalog.save_concession(payload, concession_id)

    @app.delete("/api/admin/concessions/{concession_id}", status_code=204, dependencies=same_origin)
    def admin_delete_concession(concession_id: str, admin: AdminAccount):
        catalog.delete_concession(concession_id)

    @app.post("/api/admin/promotions", status_code=201, dependencies=same_origin)
    def admin_create_promotion(payload: AdminPromotionInput, admin: AdminAccount):
        return catalog.save_promotion(payload)

    @app.put("/api/admin/promotions/{promotion_id}", dependencies=same_origin)
    def admin_update_promotion(promotion_id: str, payload: AdminPromotionInput, admin: AdminAccount):
        return catalog.save_promotion(payload, promotion_id)

    @app.delete("/api/admin/promotions/{promotion_id}", status_code=204, dependencies=same_origin)
    def admin_delete_promotion(promotion_id: str, admin: AdminAccount):
        catalog.delete_promotion(promotion_id)

    @app.post("/api/admin/blog-posts", status_code=201, dependencies=same_origin)
    def admin_create_blog_post(payload: AdminBlogPostInput, admin: AdminAccount):
        return catalog.save_blog_post(payload)

    @app.put("/api/admin/blog-posts/{post_id}", dependencies=same_origin)
    def admin_update_blog_post(post_id: str, payload: AdminBlogPostInput, admin: AdminAccount):
        return catalog.save_blog_post(payload, post_id)

    @app.delete("/api/admin/blog-posts/{post_id}", status_code=204, dependencies=same_origin)
    def admin_delete_blog_post(post_id: str, admin: AdminAccount):
        catalog.delete_blog_post(post_id)

    @app.get("/api/admin/accounts")
    def admin_list_accounts(admin: AdminAccount):
        return auth.list_accounts()

    @app.patch("/api/admin/accounts/{account_id}/role", dependencies=same_origin)
    def admin_update_role(account_id: UUID, payload: AdminRoleUpdate, admin: AdminAccount):
        return auth.update_role(admin["id"], account_id, payload.role)

    return app
