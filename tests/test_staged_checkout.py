from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg

from tests.test_checkout import simulate, system, wait_for  # noqa: F401


def test_hold_quote_payment_and_late_confirmation(system):  # noqa: F811
    web = system.web
    web.get("/")
    payload = {"screening_id": system.screening, "seats": ["A1"]}
    hold = web.post("/api/holds", json=payload, headers={"Idempotency-Key": str(uuid4())}).json()
    path = f"/api/bookings/{hold['id']}"
    assert hold["checkout_phase"] == "DRAFT"
    assert web.get(path + "/payment").status_code == 404
    conflict = web.post("/api/holds", json=payload, headers={"Idempotency-Key": str(uuid4())})
    assert conflict.status_code == 409 and "A1" in conflict.json()["detail"]

    options = {"concessions": [{"id": "combo-1-big", "quantity": 1}]}
    quote = web.post(path + "/quote", json=options).json()
    assert quote["amount"] == hold["amount"] + quote["concessions_amount"]
    with ThreadPoolExecutor(max_workers=2) as callers:
        responses = list(callers.map(lambda _: web.post(path + "/prepare", json=options), range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["payment"]["id"] for response in responses}) == 1
    ready = web.get(path).json()
    assert ready["amount"] == quote["amount"] and ready["expires_at"] == hold["expires_at"]
    assert web.post(path + "/prepare", json={}).status_code == 409

    with psycopg.connect(system.dsn) as connection:
        for table in ("bookings", "screening_seats"):
            column = "id" if table == "bookings" else "booking_id"
            connection.execute(
                f"UPDATE cinema_booking.{table} SET expires_at = clock_timestamp() + interval '2 seconds' WHERE {column} = %s",
                (hold["id"],),
            )
    system.broker.online = False
    assert simulate(system, hold["id"], delay=3).status_code == 202
    # The browser can be closed and the delivery delayed beyond the customer's original deadline.
    confirmed = wait_for(lambda: web.get(path).json(), lambda row: row["status"] == "CONFIRMED")
    assert len(confirmed["tickets"]) == 1
