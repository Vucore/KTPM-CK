from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from cinema.booking import api as booking_api
from cinema.booking.auth import AuthService, BookingViewer
from cinema.catalog import api as catalog_api
from cinema.common import Settings
from cinema.payment import api as payment_api
from tests.test_checkout import checkout, simulate, system, wait_for  # noqa: F401


class FakeCursor:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def execute(self, query, params=None):
        text = str(query).strip()
        if "clock_timestamp() AS now" in text:
            return FakeCursor([{"now": datetime.now(UTC)}])
        if text == "SELECT 1":
            return FakeCursor([{"?column?": 1}])
        return FakeCursor([])


class FakeDatabase:
    def __init__(self, dsn: str = ""):
        self.dsn = dsn
        self.pool = SimpleNamespace(open=lambda: None, close=lambda: None)

    @contextmanager
    def transaction(self):
        yield FakeConnection()

    def ping(self):
        return None


class InMemoryAccountRepo:
    def __init__(self):
        self.accounts: dict[UUID, dict] = {}
        self.sessions: dict[str, UUID] = {}
        self.attempts: dict[str, int] = {}

    def add_seed_account(self, username: str, password_hash: str, role: str, points: int = 100) -> dict:
        account_id = uuid4()
        row = {
            "id": account_id,
            "username": username,
            "password_hash": password_hash,
            "full_name": username.title(),
            "email": f"{username}@example.com",
            "phone": "0900000000",
            "birth_date": None,
            "points": points,
            "total_spent": 0,
            "role": role,
            "created_at": datetime.now(UTC),
        }
        self.accounts[account_id] = row
        return row

    def register(self, connection, account_id, username, password_hash):
        if any(acc["username"] == username for acc in self.accounts.values()):
            return None
        row = {
            "id": account_id,
            "username": username,
            "password_hash": password_hash,
            "full_name": None,
            "email": None,
            "phone": None,
            "birth_date": None,
            "points": 0,
            "total_spent": 0,
            "role": "USER",
            "created_at": datetime.now(UTC),
        }
        self.accounts[account_id] = row
        return {"id": account_id, "username": username, "role": "USER"}

    def find(self, connection, username):
        for acc in self.accounts.values():
            if acc["username"] == username:
                return dict(acc)
        return None

    def find_by_id(self, connection, account_id):
        acc = self.accounts.get(account_id)
        return dict(acc) if acc else None

    def lock_account(self, connection, account_id):
        acc = self.accounts.get(account_id)
        if not acc:
            return None
        return {
            "id": acc["id"],
            "username": acc["username"],
            "points": acc["points"],
            "total_spent": acc["total_spent"],
            "role": acc["role"],
        }

    def update_profile(self, connection, account_id, full_name, email, phone, birth_date):
        acc = self.accounts.get(account_id)
        if not acc:
            return None
        acc.update({"full_name": full_name, "email": email, "phone": phone, "birth_date": birth_date})
        return {k: v for k, v in acc.items() if k != "password_hash"}

    def list_accounts(self, connection):
        return [{k: v for k, v in acc.items() if k != "password_hash"} for acc in self.accounts.values()]

    def admin_ids_for_update(self, connection):
        return [acc["id"] for acc in self.accounts.values() if acc["role"] == "ADMIN"]

    def update_role(self, connection, account_id, role):
        acc = self.accounts.get(account_id)
        if not acc:
            return None
        acc["role"] = role
        return {k: v for k, v in acc.items() if k != "password_hash"}

    def point_history(self, connection, account_id):
        return []

    def record_point_transaction(self, connection, account_id, booking_id, kind, points_delta, description):
        acc = self.accounts.get(account_id)
        if acc:
            acc["points"] = max(0, acc["points"] + points_delta)
        return True

    def add_spent_and_earn(self, connection, account_id, booking_id, amount, description):
        return 0

    def update_password_hash(self, connection, account_id, previous, password_hash):
        acc = self.accounts.get(account_id)
        if acc and acc["password_hash"] == previous:
            acc["password_hash"] = password_hash

    def start_session(self, connection, account_id, token_hash, lifetime):
        self.sessions[token_hash] = account_id

    def session_account(self, connection, token_hash):
        account_id = self.sessions.get(token_hash)
        if not account_id:
            return None
        acc = self.accounts.get(account_id)
        return {k: v for k, v in acc.items() if k != "password_hash"} if acc else None

    def revoke_session(self, connection, token_hash):
        self.sessions.pop(token_hash, None)

    def record_attempt(self, connection, subject, lifetime, limit):
        count = min(self.attempts.get(subject, 0) + 1, limit + 1)
        self.attempts[subject] = count
        return {"attempts": count, "retry_after": 60}


class InMemorySeatRepo:
    def __init__(self):
        self.seats: dict[tuple[str, str], dict] = {}

    def sync(self, connection, screening):
        for seat in screening["seats"]:
            key = (screening["id"], seat["label"])
            self.seats.setdefault(
                key,
                {
                    "label": seat["label"],
                    "seat_type": seat["seat_type"],
                    "status": "AVAILABLE",
                    "expires_at": None,
                    "booking_id": None,
                },
            )

    def list(self, connection, screening_id):
        return [
            {
                "label": s["label"],
                "seat_type": s["seat_type"],
                "status": "AVAILABLE"
                if s["status"] == "HELD" and s["expires_at"] <= datetime.now(UTC)
                else s["status"],
            }
            for (sid, _), s in sorted(self.seats.items())
            if sid == screening_id
        ]

    def lock(self, connection, screening_id, labels):
        return [
            dict(self.seats[(screening_id, label)])
            for label in labels
            if (screening_id, label) in self.seats
        ]

    def hold(self, connection, booking):
        for label in booking["seats"]:
            seat = self.seats[(booking["screening_id"], label)]
            seat["status"] = "HELD"
            seat["booking_id"] = booking["id"]
            seat["expires_at"] = booking["expires_at"]

    def release(self, connection, booking):
        for label in booking["seats"]:
            seat = self.seats[(booking["screening_id"], label)]
            if seat["booking_id"] == booking["id"] and seat["status"] == "HELD":
                seat["status"] = "AVAILABLE"
                seat["booking_id"] = None
                seat["expires_at"] = None

    def sell(self, connection, booking):
        count = 0
        for label in booking["seats"]:
            seat = self.seats[(booking["screening_id"], label)]
            if seat["booking_id"] == booking["id"] and seat["status"] == "HELD":
                seat["status"] = "SOLD"
                seat["expires_at"] = None
                count += 1
        return count


class InMemoryBookingRepo:
    def __init__(self):
        self.bookings: dict[UUID, dict] = {}
        self.saved: set[tuple[str, UUID]] = set()

    def by_key(self, connection, key):
        for b in self.bookings.values():
            if b["request_key"] == key:
                return dict(b)
        return None

    def lock_key(self, connection, key):
        return None

    def insert(self, connection, booking):
        self.bookings[booking["id"]] = {
            **booking,
            "status": "HELD",
            "pay_by": booking["expires_at"],
            "attempt_key": None,
            "payment_id": None,
            "options_hash": None,
        }

    def lock(self, connection, booking_id):
        row = self.bookings.get(booking_id)
        return dict(row) if row else None

    def detail(self, connection, booking_id, viewer: BookingViewer):
        b = self.bookings.get(booking_id)
        if not b:
            return None
        if b["account_id"] is not None and b["account_id"] != viewer.account_id:
            return None
        status = "EXPIRED" if b["status"] == "HELD" and b["expires_at"] <= datetime.now(UTC) else b["status"]
        return {
            "id": b["id"],
            "screening_id": b["screening_id"],
            "movie_title": b["movie_title"],
            "starts_at": b["starts_at"],
            "auditorium": b["auditorium"],
            "seats": list(b["seats"]),
            "customer_name": b["customer_name"],
            "amount": b["amount"],
            "expires_at": b["expires_at"],
            "cinema_name": b["cinema_name"],
            "screening_format": b["screening_format"],
            "concessions": list(b.get("concessions", [])),
            "concessions_amount": b.get("concessions_amount", 0),
            "discount_amount": b.get("discount_amount", 0),
            "promo_code": b.get("promo_code"),
            "points_redeemed": b.get("points_redeemed", 0),
            "checkout_phase": b["checkout_phase"],
            "pay_by": b.get("pay_by"),
            "server_now": datetime.now(UTC),
            "status": status,
            "saved": (viewer.history_key, b["id"]) in self.saved,
        }

    def saved_list(self, connection, viewer: BookingViewer):
        rows = []
        for b in self.bookings.values():
            if (viewer.history_key, b["id"]) in self.saved and (
                b["account_id"] is None or b["account_id"] == viewer.account_id
            ):
                rows.append(
                    {
                        "id": b["id"],
                        "movie_title": b["movie_title"],
                        "starts_at": b["starts_at"],
                        "auditorium": b["auditorium"],
                        "seats": list(b["seats"]),
                        "cinema_name": b["cinema_name"],
                        "screening_format": b["screening_format"],
                        "amount": b["amount"],
                        "status": b["status"],
                    }
                )
        return rows

    def save(self, connection, history_key, booking_id):
        if history_key:
            self.saved.add((history_key, booking_id))

    def forget(self, connection, history_key, booking_id):
        if history_key:
            self.saved.discard((history_key, booking_id))

    def cancel(self, connection, booking_id):
        if booking_id in self.bookings:
            self.bookings[booking_id]["status"] = "CANCELLED"

    def confirm(self, connection, booking_id, payment_id):
        if booking_id in self.bookings:
            self.bookings[booking_id]["status"] = "CONFIRMED"
            self.bookings[booking_id]["payment_id"] = payment_id

    def admin_overview(self, connection):
        return {
            "kpi": {
                "total_revenue": 0,
                "confirmed_bookings": 0,
                "tickets_sold": 0,
                "tickets_checked_in": 0,
                "held_bookings": 0,
                "total_accounts": 0,
            },
            "by_movie": [],
            "by_cinema": [],
        }

    def admin_bookings(self, connection, status_filter=None, query=None):
        return [
            {
                "id": b["id"],
                "screening_id": b["screening_id"],
                "movie_title": b["movie_title"],
                "starts_at": b["starts_at"],
                "auditorium": b["auditorium"],
                "cinema_name": b["cinema_name"],
                "screening_format": b["screening_format"],
                "seats": list(b["seats"]),
                "customer_name": b["customer_name"],
                "amount": b["amount"],
                "status": b["status"],
            }
            for b in self.bookings.values()
        ]

    def has_active_bookings_for_screening(self, connection, screening_id: str) -> bool:
        return False


class InMemoryTicketRepo:
    def __init__(self, booking_repo: InMemoryBookingRepo):
        self.tickets: dict[UUID, dict] = {}
        self.booking_repo = booking_repo

    def insert(self, connection, ticket):
        self.tickets[ticket["code"]] = {**ticket, "checked_in_at": None, "checked_in_by": None}

    def list(self, connection, booking_id):
        return [
            {
                "code": t["code"],
                "seat": t["seat"],
                "customer_name": t["customer_name"],
                "checked_in_at": t["checked_in_at"],
            }
            for t in self.tickets.values()
            if t["booking_id"] == booking_id
        ]

    def find(self, connection, code):
        t = self.tickets.get(code)
        if not t:
            return None
        b = self.booking_repo.bookings.get(t["booking_id"])
        if not b:
            return None
        return {
            "code": t["code"],
            "seat": t["seat"],
            "customer_name": t["customer_name"],
            "checked_in_at": t["checked_in_at"],
            "account_id": b["account_id"],
            "hold_owner": b["hold_owner"],
            "movie_title": b["movie_title"],
            "auditorium": b["auditorium"],
            "cinema_name": b["cinema_name"],
            "screening_format": b["screening_format"],
            "starts_at": b["starts_at"],
        }

    def lock_ticket(self, connection, code):
        t = self.tickets.get(code)
        if not t:
            return None
        b = self.booking_repo.bookings.get(t["booking_id"])
        if not b:
            return None
        return {
            "code": t["code"],
            "seat": t["seat"],
            "customer_name": t["customer_name"],
            "checked_in_at": t["checked_in_at"],
            "booking_id": b["id"],
            "movie_title": b["movie_title"],
            "auditorium": b["auditorium"],
            "cinema_name": b["cinema_name"],
            "screening_format": b["screening_format"],
            "starts_at": b["starts_at"],
        }

    def mark_checked_in(self, connection, code, staff_account_id):
        t = self.tickets[code]
        t["checked_in_at"] = datetime.now(UTC)
        t["checked_in_by"] = staff_account_id
        return {"checked_in_at": t["checked_in_at"]}


@pytest.fixture
def authz_harness(monkeypatch):
    account_repo = InMemoryAccountRepo()
    seat_repo = InMemorySeatRepo()
    booking_repo = InMemoryBookingRepo()
    ticket_repo = InMemoryTicketRepo(booking_repo)
    payments: dict[UUID, dict] = {}
    starts_at = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0)

    def downstream(request: httpx.Request):
        path = request.url.path
        if request.url.port == 8001:
            if path == "/screenings":
                return httpx.Response(200, json=[{"id": "scr-1", "title": "Sài Gòn Sau Mưa"}])
            if path == "/screenings/scr-1":
                return httpx.Response(
                    200,
                    json={
                        "id": "scr-1",
                        "title": "Sài Gòn Sau Mưa",
                        "starts_at": starts_at.isoformat(),
                        "auditorium": "Phòng 1",
                        "cinema_name": "DUT Nguyễn Du",
                        "format": "2D Phụ đề",
                        "base_price": 90000,
                        "seats": [
                            {"label": f"A{i}", "seat_type": "STANDARD"} for i in range(1, 7)
                        ],
                    },
                )
            if path == "/catalog/home":
                return httpx.Response(200, json={"cinemas": [], "concessions": [], "promotions": []})
            if path == "/catalog/checkout-options":
                return httpx.Response(
                    200,
                    json={
                        "concessions": [
                            {"id": "combo-1-big", "name": "Combo 1 Big", "price": 89000},
                        ],
                        "promotions": [
                            {
                                "id": "promo-dut20",
                                "code": "DUT20",
                                "discount_type": "PERCENT",
                                "discount_value": 20,
                                "min_amount": 50000,
                            }
                        ],
                    },
                )
            if path.startswith("/movies/"):
                return httpx.Response(200, json={"id": "saigon", "title": "Sài Gòn Sau Mưa"})
            if path == "/admin/catalog":
                return httpx.Response(200, json={"movies": [], "screenings": []})
            if path.startswith("/admin/"):
                status = 204 if request.method == "DELETE" else (201 if request.method == "POST" else 200)
                return httpx.Response(status, json={} if status != 204 else None)
            return httpx.Response(404, json={"detail": "Not found"})

        # Payment service (port 8002)
        if path == "/payments" and request.method == "POST":
            body = httpx.Response(200, content=request.content).json()
            bid = UUID(body["booking_id"])
            record = payments.setdefault(
                bid,
                {
                    "id": str(uuid4()),
                    "booking_id": str(bid),
                    "amount": body["amount"],
                    "status": "PENDING",
                    "last_attempt": None,
                },
            )
            return httpx.Response(201, json=record)
        if path.startswith("/payments/") and path.endswith("/simulate") and request.method == "POST":
            bid = UUID(path.split("/")[2])
            record = payments[bid]
            record["status"] = "SUCCEEDED"
            record["last_attempt"] = request.headers.get("Idempotency-Key")
            return httpx.Response(202, json=record)
        if path.startswith("/payments/") and request.method == "GET":
            bid = UUID(path.split("/")[2])
            if bid not in payments:
                return httpx.Response(404, json={"detail": "Not found"})
            return httpx.Response(200, json=payments[bid])
        return httpx.Response(404, json={"detail": "Not found"})

    monkeypatch.setattr(booking_api, "Database", FakeDatabase)
    monkeypatch.setattr(booking_api, "AccountRepository", lambda: account_repo)
    monkeypatch.setattr(booking_api, "BookingRepository", lambda: booking_repo)
    monkeypatch.setattr(booking_api, "ScreeningSeatRepository", lambda: seat_repo)
    monkeypatch.setattr(booking_api, "TicketRepository", lambda: ticket_repo)

    settings = Settings(
        database_url="postgresql://unused",
        internal_key="test-key-that-is-long-enough",
        hold_seconds=300,
    )
    app = booking_api.create_app(settings, httpx.MockTransport(downstream))
    password = "Mat khau an toan du 15 ky tu"
    pw_hash = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1).hash(password)
    admin1 = account_repo.add_seed_account("admin1", pw_hash, "ADMIN")
    admin2 = account_repo.add_seed_account("admin2", pw_hash, "ADMIN")
    staff = account_repo.add_seed_account("staff1", pw_hash, "STAFF")
    user_a = account_repo.add_seed_account("usera", pw_hash, "USER", points=20)
    user_b = account_repo.add_seed_account("userb", pw_hash, "USER", points=20)

    def login_client(username: str) -> TestClient:
        client = TestClient(app)
        res = client.post("/api/auth/login", json={"username": username, "password": password})
        assert res.status_code == 200, res.text
        return client

    return SimpleNamespace(
        app=app,
        account_repo=account_repo,
        booking_repo=booking_repo,
        ticket_repo=ticket_repo,
        admin1=admin1,
        admin2=admin2,
        staff=staff,
        user_a=user_a,
        user_b=user_b,
        new_guest=lambda: TestClient(app),
        login=login_client,
    )


def test_auth_and_guest_vs_protected_routes(authz_harness):
    with authz_harness.new_guest() as guest:
        # AUTH-001..004: public catalog & seat map
        assert guest.get("/").status_code == 200
        assert guest.get("/api/screenings").status_code == 200
        assert guest.get("/api/catalog/home").status_code == 200
        assert guest.get("/api/movies/saigon").status_code == 200
        assert guest.get("/api/screenings/scr-1/seats").status_code == 200

        # AUTH-008..012: unauthenticated protected endpoints return 401
        assert guest.get("/api/account/profile").status_code == 401
        assert guest.patch("/api/account/profile", json={"full_name": "Guest"}).status_code == 401
        assert guest.get("/api/admin/overview").status_code == 401
        assert guest.get("/api/admin/bookings").status_code == 401
        assert guest.get("/api/admin/catalog").status_code == 401
        assert guest.get("/api/admin/accounts").status_code == 401
        assert guest.post("/api/admin/movies", json={"id": "m1", "title": "M", "genre": "G", "duration_minutes": 90, "synopsis": "S"}).status_code == 401
        assert guest.post(f"/api/admin/tickets/{uuid4()}/check-in").status_code == 401

        # Guest cannot redeem member points (BOOK-009 / auth requirement)
        redeem_res = guest.post(
            "/api/checkout",
            json={"screening_id": "scr-1", "seats": ["A1"], "redeem_points": 5},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert redeem_res.status_code == 401


def test_user_and_staff_rbac_across_all_admin_routes(authz_harness):
    movie_payload = {
        "id": "film-test",
        "title": "Phim Test",
        "genre": "Tâm lý",
        "duration_minutes": 100,
        "synopsis": "Mô tả",
    }
    cinema_payload = {
        "id": "cinema-test",
        "name": "DUT Test",
        "city": "Đà Nẵng",
        "address": "123 Đường Test",
    }
    auditorium_payload = {
        "id": "room-test",
        "name": "Phòng Test",
        "cinema_id": "dut-nguyen-du",
    }
    screening_payload = {
        "movie_id": "saigon",
        "auditorium_id": "room-1",
        "starts_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
        "base_price": 85000,
    }
    concession_payload = {
        "id": "combo-test",
        "name": "Combo Test",
        "description": "Mô tả",
        "price": 50000,
    }
    promo_payload = {
        "id": "promo-test",
        "title": "KM Test",
        "tag": "Tag",
        "summary": "Tóm tắt",
    }
    blog_payload = {
        "id": "blog-test",
        "title": "Bài Test",
        "summary": "Tóm tắt",
        "content": "Nội dung",
    }

    admin_only_requests = [
        ("GET", "/api/admin/overview", None),
        ("GET", "/api/admin/catalog", None),
        ("GET", "/api/admin/accounts", None),
        ("PATCH", f"/api/admin/accounts/{authz_harness.user_a['id']}/role", {"role": "ADMIN"}),
        ("POST", "/api/admin/movies", movie_payload),
        ("PUT", "/api/admin/movies/saigon", movie_payload),
        ("DELETE", "/api/admin/movies/saigon", None),
        ("POST", "/api/admin/cinemas", cinema_payload),
        ("PUT", "/api/admin/cinemas/dut-nguyen-du", cinema_payload),
        ("POST", "/api/admin/auditoriums", auditorium_payload),
        ("POST", "/api/admin/screenings", screening_payload),
        ("PUT", "/api/admin/screenings/scr-1", screening_payload),
        ("DELETE", "/api/admin/screenings/scr-1", None),
        ("POST", "/api/admin/concessions", concession_payload),
        ("PUT", "/api/admin/concessions/combo-1-big", concession_payload),
        ("DELETE", "/api/admin/concessions/combo-1-big", None),
        ("POST", "/api/admin/promotions", promo_payload),
        ("PUT", "/api/admin/promotions/promo-dut20", promo_payload),
        ("DELETE", "/api/admin/promotions/promo-dut20", None),
        ("POST", "/api/admin/blog-posts", blog_payload),
        ("PUT", "/api/admin/blog-posts/review-saigon", blog_payload),
        ("DELETE", "/api/admin/blog-posts/review-saigon", None),
    ]

    # USER-012..018: Regular USER gets 403 on every staff/admin endpoint & method
    with authz_harness.login("usera") as user_client:
        assert user_client.get("/api/admin/bookings").status_code == 403
        assert user_client.post(f"/api/admin/tickets/{uuid4()}/check-in").status_code == 403
        for method, path, payload in admin_only_requests:
            res = user_client.request(method, path, json=payload)
            assert res.status_code == 403, f"USER unexpectedly allowed on {method} {path}: {res.status_code}"

    # STAFF-004..013: STAFF can list bookings & check-in, but gets 403 on all ADMIN endpoints
    with authz_harness.login("staff1") as staff_client:
        assert staff_client.get("/api/admin/bookings").status_code == 200
        for method, path, payload in admin_only_requests:
            res = staff_client.request(method, path, json=payload)
            assert res.status_code == 403, f"STAFF unexpectedly allowed on {method} {path}: {res.status_code}"


def test_admin_role_management_and_last_admin_protection(authz_harness):
    with authz_harness.login("admin1") as admin_client:
        accounts = admin_client.get("/api/admin/accounts")
        assert accounts.status_code == 200
        assert len(accounts.json()) == 5

        # Self-downgrade is blocked (409)
        self_downgrade = admin_client.patch(
            f"/api/admin/accounts/{authz_harness.admin1['id']}/role",
            json={"role": "USER"},
        )
        assert self_downgrade.status_code == 409

        # Admin1 can downgrade Admin2 because Admin1 remains
        downgrade_second = admin_client.patch(
            f"/api/admin/accounts/{authz_harness.admin2['id']}/role",
            json={"role": "STAFF"},
        )
        assert downgrade_second.status_code == 200
        assert downgrade_second.json()["role"] == "STAFF"

        # Now only Admin1 remains ADMIN; even another actor cannot downgrade the last ADMIN
        with pytest.raises(booking_api.HTTPException) as exc:
            service = AuthService(
                FakeDatabase(),
                authz_harness.account_repo,
                PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1),
            )
            service.update_role(authz_harness.admin2["id"], authz_harness.admin1["id"], "USER")
        assert exc.value.status_code == 409


def test_idor_for_bookings_checkout_and_tickets(authz_harness):
    with (
        authz_harness.login("usera") as user_a,
        authz_harness.login("userb") as user_b,
        authz_harness.login("staff1") as staff,
        authz_harness.new_guest() as guest_owner,
        authz_harness.new_guest() as guest_stranger,
    ):
        # 1. Account booking + ticket IDOR isolation
        hold_res = user_a.post(
            "/api/holds",
            json={"screening_id": "scr-1", "seats": ["A1"]},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert hold_res.status_code == 201
        user_booking_id = UUID(hold_res.json()["id"])

        for bad_actor in (user_b, guest_stranger, staff):
            assert bad_actor.get(f"/api/bookings/{user_booking_id}").status_code == 404
            assert bad_actor.post(f"/api/bookings/{user_booking_id}/quote", json={}).status_code == 404
            assert bad_actor.post(f"/api/bookings/{user_booking_id}/prepare", json={}).status_code == 404
            assert bad_actor.post(f"/api/bookings/{user_booking_id}/cancel").status_code == 404
            assert bad_actor.post(
                f"/api/bookings/{user_booking_id}/payment/simulate",
                json={"outcome": "success"},
                headers={"Idempotency-Key": str(uuid4())},
            ).status_code == 404

        # Insert a confirmed ticket for User A's booking
        user_ticket_code = uuid4()
        authz_harness.ticket_repo.insert(
            FakeConnection(),
            {
                "code": user_ticket_code,
                "booking_id": user_booking_id,
                "screening_id": "scr-1",
                "seat": "A1",
                "customer_name": "Nguyen Van A",
            },
        )
        owner_ticket = user_a.get(f"/api/tickets/{user_ticket_code}")
        assert owner_ticket.status_code == 200
        assert "booking_id" not in owner_ticket.json()
        assert user_a.get(f"/api/tickets/{user_ticket_code}/qr.svg").status_code == 200

        # STAFF can inspect and check in User A's ticket
        assert staff.get(f"/api/tickets/{user_ticket_code}").status_code == 200
        assert staff.post(f"/api/admin/tickets/{user_ticket_code}/check-in").status_code == 200

        # Another USER or stranger Guest cannot read User A's ticket or QR
        assert user_b.get(f"/api/tickets/{user_ticket_code}").status_code == 404
        assert user_b.get(f"/api/tickets/{user_ticket_code}/qr.svg").status_code == 404
        assert guest_stranger.get(f"/api/tickets/{user_ticket_code}").status_code == 404

        # 2. Guest legacy /api/checkout binds hold_owner so strangers cannot cancel or simulate payment
        guest_checkout = guest_owner.post(
            "/api/checkout",
            json={"screening_id": "scr-1", "seats": ["A2"]},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert guest_checkout.status_code == 201
        guest_booking_id = UUID(guest_checkout.json()["booking"]["id"])
        assert authz_harness.booking_repo.bookings[guest_booking_id]["hold_owner"] is not None

        assert guest_stranger.post(f"/api/bookings/{guest_booking_id}/cancel").status_code == 404
        assert (
            guest_stranger.post(
                f"/api/bookings/{guest_booking_id}/payment/simulate",
                json={"outcome": "success"},
                headers={"Idempotency-Key": str(uuid4())},
            ).status_code
            == 404
        )
        assert user_b.post(f"/api/bookings/{guest_booking_id}/cancel").status_code == 404

        guest_ticket_code = uuid4()
        authz_harness.ticket_repo.insert(
            FakeConnection(),
            {
                "code": guest_ticket_code,
                "booking_id": guest_booking_id,
                "screening_id": "scr-1",
                "seat": "A2",
                "customer_name": "Khach A",
            },
        )
        assert guest_owner.get(f"/api/tickets/{guest_ticket_code}").status_code == 200
        assert guest_stranger.get(f"/api/tickets/{guest_ticket_code}").status_code == 404
        assert user_b.get(f"/api/tickets/{guest_ticket_code}").status_code == 404


def test_server_side_pricing_csrf_origin_and_http_methods(authz_harness):
    with authz_harness.login("usera") as user_a:
        # Cross-origin mutation rejected with 403
        assert (
            user_a.post(
                "/api/holds",
                json={"screening_id": "scr-1", "seats": ["A3"]},
                headers={"Idempotency-Key": str(uuid4()), "Origin": "https://attacker.example"},
            ).status_code
            == 403
        )

        # Unsupported HTTP methods rejected with 405
        assert user_a.delete("/api/auth/login").status_code == 405
        assert user_a.post("/api/admin/overview").status_code == 405
        assert user_a.patch("/api/admin/movies").status_code == 405

        # BOOK-009: Client cannot tamper seat/concession price or total via extra payload fields
        res = user_a.post(
            "/api/checkout",
            json={
                "screening_id": "scr-1",
                "seats": ["A4"],
                "concessions": [{"id": "combo-1-big", "quantity": 1, "price": 1}],
                "amount": 1,
                "discount_amount": 999999,
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert res.status_code == 201
        booking = res.json()["booking"]
        assert booking["concessions_amount"] == 89000
        assert booking["amount"] > 89000


def test_internal_service_key_boundaries(monkeypatch):
    # Catalog & Payment services must reject missing/invalid X-Internal-Key on internal routes
    settings = Settings("postgresql://unused", internal_key="test-key-that-is-long-enough")
    catalog_app = catalog_api.create_app(settings)
    payment_app = payment_api.create_app(settings)

    catalog_client = TestClient(catalog_app)
    payment_client = TestClient(payment_app)

    for method, path in [
        ("GET", "/admin/catalog"),
        ("POST", "/admin/movies"),
        ("PUT", "/admin/movies/saigon"),
        ("DELETE", "/admin/movies/saigon"),
        ("POST", "/admin/screenings"),
        ("DELETE", "/admin/screenings/scr-1"),
        ("POST", "/admin/promotions"),
        ("DELETE", "/admin/promotions/p1"),
    ]:
        assert catalog_client.request(method, path).status_code == 403
        assert catalog_client.request(method, path, headers={"X-Internal-Key": "wrong-key"}).status_code == 403

    for method, path in [
        ("POST", "/payments"),
        ("GET", f"/payments/{uuid4()}"),
        ("POST", f"/payments/{uuid4()}/simulate"),
    ]:
        assert payment_client.request(method, path).status_code == 403
        assert payment_client.request(method, path, headers={"X-Internal-Key": "wrong-key"}).status_code == 403

    # Settings.load("catalog") enforces non-empty >=24 char INTERNAL_API_KEY
    monkeypatch.setenv("CATALOG_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("INTERNAL_API_KEY", "short")
    with pytest.raises(RuntimeError):
        Settings.load("catalog")


def test_live_authorization_matrix(system):  # noqa: F811
    """End-to-end PostgreSQL authorization checks when TEST_DATABASE_URL is configured."""
    # Guest creates legacy checkout booking -> stranger cannot cancel or read its ticket
    guest_res = checkout(system, ["C1"])
    assert guest_res.status_code == 201
    booking_id = guest_res.json()["booking"]["id"]
    assert simulate(system, booking_id).status_code == 202
    confirmed = wait_for(
        lambda: system.web.get(f"/api/bookings/{booking_id}").json(),
        lambda row: row["status"] == "CONFIRMED",
    )
    ticket_code = confirmed["tickets"][0]["code"]
    assert system.web.get(f"/api/tickets/{ticket_code}").status_code == 200
    assert "booking_id" not in system.web.get(f"/api/tickets/{ticket_code}").json()

    with closing(TestClient(system.web.app)) as stranger:
        assert stranger.post(f"/api/bookings/{booking_id}/cancel").status_code == 404
        assert stranger.get(f"/api/tickets/{ticket_code}").status_code == 404
        assert stranger.get(f"/api/tickets/{ticket_code}/qr.svg").status_code == 404

    with closing(TestClient(system.web.app)) as staff_client:
        assert (
            staff_client.post(
                "/api/auth/login",
                json={"username": "staff", "password": "dut-cinema-staff-2026"},
            ).status_code
            == 200
        )
        assert staff_client.get(f"/api/tickets/{ticket_code}").status_code == 200
        assert staff_client.patch(
            f"/api/admin/accounts/{uuid4()}/role",
            json={"role": "ADMIN"},
        ).status_code == 403
