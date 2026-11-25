from uuid import uuid4

from tests.test_checkout import simulate, system, wait_for  # noqa: F401


def test_dut_cinema_catalog_home_movie_detail_and_cancel_flow(system):  # noqa: F811
    home = system.web.get("/api/catalog/home")
    assert home.status_code == 200
    data = home.json()
    assert len(data["cinemas"]) >= 4
    assert len(data["concessions"]) >= 4
    assert len(data["promotions"]) >= 4
    assert len(data["blog_posts"]) >= 4
    assert len(data["coming_soon"]) >= 1

    movie = system.web.get("/api/movies/saigon")
    assert movie.status_code == 200
    assert movie.json()["age_rating"] == "T13"

    # Checkout with concessions + promo code, then cancel hold
    res = system.web.post(
        "/api/checkout",
        json={
            "screening_id": system.screening,
            "seats": ["E1"],
            "concessions": [{"id": "combo-1-big", "quantity": 1}],
            "promo_code": "DUT20",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert res.status_code == 201, res.text
    booking = res.json()["booking"]
    assert booking["promo_code"] == "DUT20"
    assert booking["discount_amount"] > 0
    assert len(booking["concessions"]) == 1

    cancelled = system.web.post(f"/api/bookings/{booking['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    seats = system.web.get(f"/api/screenings/{system.screening}/seats").json()
    assert {s["label"]: s["status"] for s in seats}["E1"] == "AVAILABLE"


def test_gstar_profile_and_points_earned_on_confirmation(system):  # noqa: F811
    creds = {"username": f"gstar-{uuid4().hex[:10]}", "password": "Mot cum tu dai cho gstar"}
    assert system.web.post("/api/auth/register", json=creds).status_code == 201

    updated = system.web.patch(
        "/api/account/profile",
        json={"full_name": "Nguyễn Minh", "email": "minh@example.com", "phone": "0901234567"},
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Nguyễn Minh"

    res = system.web.post(
        "/api/checkout",
        json={"screening_id": system.screening, "seats": ["A3"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert res.status_code == 201
    booking_id = res.json()["booking"]["id"]
    assert simulate(system, booking_id).status_code == 202
    wait_for(lambda: system.web.get(f"/api/bookings/{booking_id}").json(), lambda row: row["status"] == "CONFIRMED")

    profile = system.web.get("/api/account/profile").json()
    assert profile["points"] > 0
    assert profile["total_spent"] > 0
    assert len(profile["point_history"]) == 1
