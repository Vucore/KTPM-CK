from contextlib import closing
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.test_checkout import checkout, simulate, system, wait_for  # noqa: F401


def test_admin_rbac_crud_overlap_and_ticket_checkin(system):  # noqa: F811
    # Guest is rejected with 401
    assert system.web.get("/api/admin/overview").status_code == 401

    # Regular USER is rejected with 403
    user_creds = {"username": f"user-{uuid4().hex[:8]}", "password": "Mot mat khau dai cho user"}
    with closing(TestClient(system.web.app)) as user_client:
        assert user_client.post("/api/auth/register", json=user_creds).status_code == 201
        assert user_client.get("/api/admin/overview").status_code == 403
        assert user_client.get("/api/admin/bookings").status_code == 403

    # Create and confirm a booking to test QR ticket check-in
    res = checkout(system, ["A6"])
    assert res.status_code == 201
    booking_id = res.json()["booking"]["id"]
    assert simulate(system, booking_id).status_code == 202
    confirmed = wait_for(
        lambda: system.web.get(f"/api/bookings/{booking_id}").json(),
        lambda row: row["status"] == "CONFIRMED",
    )
    ticket_code = confirmed["tickets"][0]["code"]

    # STAFF can view bookings and check-in a ticket once, but cannot access ADMIN CRUD
    with closing(TestClient(system.web.app)) as staff_client:
        login = staff_client.post(
            "/api/auth/login",
            json={"username": "staff", "password": "dut-cinema-staff-2026"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["account"]["role"] == "STAFF"
        assert staff_client.get("/api/admin/bookings").status_code == 200
        assert staff_client.get("/api/admin/overview").status_code == 403

        first_checkin = staff_client.post(f"/api/admin/tickets/{ticket_code}/check-in")
        assert first_checkin.status_code == 200
        assert first_checkin.json()["checked_in_at"] is not None

        second_checkin = staff_client.post(f"/api/admin/tickets/{ticket_code}/check-in")
        assert second_checkin.status_code == 409

    # ADMIN has full access to overview, catalog CRUD, screening overlap check, and role management
    with closing(TestClient(system.web.app)) as admin_client:
        login = admin_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "dut-cinema-admin-2026"},
        )
        assert login.status_code == 200, login.text
        admin_id = login.json()["account"]["id"]
        assert login.json()["account"]["role"] == "ADMIN"

        overview = admin_client.get("/api/admin/overview")
        assert overview.status_code == 200
        assert overview.json()["kpi"]["tickets_checked_in"] >= 1

        # Cannot downgrade own ADMIN role
        assert (
            admin_client.patch(f"/api/admin/accounts/{admin_id}/role", json={"role": "USER"}).status_code
            == 409
        )

        # Movie CRUD
        movie_id = f"dut-film-{uuid4().hex[:6]}"
        created_movie = admin_client.post(
            "/api/admin/movies",
            json={
                "id": movie_id,
                "title": "Đêm Đà Nẵng",
                "genre": "Tâm lý",
                "duration_minutes": 100,
                "synopsis": "Câu chuyện bên cầu Rồng.",
                "release_status": "NOW_SHOWING",
                "age_rating": "T13",
                "rating": 9.0,
            },
        )
        assert created_movie.status_code == 201

        # Auditorium creation + Screening overlap check
        room_id = f"room-{uuid4().hex[:6]}"
        created_room = admin_client.post(
            "/api/admin/auditoriums",
            json={
                "id": room_id,
                "name": "Phòng Test",
                "cinema_id": "dut-danang",
                "screen_format": "2D Phụ đề",
                "standard_rows": 2,
                "vip_rows": 1,
                "couple_seats": 2,
                "seats_per_row": 6,
            },
        )
        assert created_room.status_code == 201
        assert created_room.json()["seat_count"] == 20

        starts_at = (datetime.now(UTC) + timedelta(days=5)).replace(microsecond=0)
        sc1 = admin_client.post(
            "/api/admin/screenings",
            json={
                "movie_id": movie_id,
                "auditorium_id": room_id,
                "starts_at": starts_at.isoformat(),
                "base_price": 80000,
                "format": "2D Phụ đề",
            },
        )
        assert sc1.status_code == 201
        sc1_id = sc1.json()["id"]

        # Overlapping screening in same room within movie duration + 15m turnaround -> 409
        overlap = admin_client.post(
            "/api/admin/screenings",
            json={
                "movie_id": movie_id,
                "auditorium_id": room_id,
                "starts_at": (starts_at + timedelta(minutes=30)).isoformat(),
                "base_price": 80000,
                "format": "2D Phụ đề",
            },
        )
        assert overlap.status_code == 409

        # Cannot delete movie while it still has screenings -> 409
        assert admin_client.delete(f"/api/admin/movies/{movie_id}").status_code == 409

        # Delete screening then delete movie -> 204
        assert admin_client.delete(f"/api/admin/screenings/{sc1_id}").status_code == 204
        assert admin_client.delete(f"/api/admin/movies/{movie_id}").status_code == 204
