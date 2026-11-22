import json
import os
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pika
import psycopg
import pytest
from fastapi.testclient import TestClient

from cinema.booking import api as booking_api
from cinema.catalog import api as catalog_api
from cinema.common import Settings
from cinema.messaging import QUEUES
from cinema.payment import api as payment_api
from cinema.setup import migrate, seed


class TestBroker:
    __test__ = False

    def __init__(self):
        self.online = True
        self.messages = defaultdict(deque)

    def connection(self, config):
        return TestChannel(self)


class TestChannel:
    __test__ = False
    is_open = True

    def __init__(self, broker):
        self.broker = broker
        self.delivery = None

    def channel(self):
        return self

    def queue_declare(self, queue, **kwargs):
        pass

    def confirm_delivery(self):
        pass

    def process_data_events(self, **kwargs):
        pass

    def basic_get(self, queue, **kwargs):
        if not self.broker.online:
            raise pika.exceptions.AMQPConnectionError("test broker offline")
        try:
            body = self.broker.messages[queue].popleft()
        except IndexError:
            return None, None, None
        self.delivery = (queue, body)
        return SimpleNamespace(delivery_tag=1), None, body

    def basic_publish(self, routing_key, body, **kwargs):
        if not self.broker.online:
            raise pika.exceptions.AMQPConnectionError("test broker offline")
        self.broker.messages[routing_key].append(body)

    def basic_ack(self, delivery_tag):
        self.delivery = None

    def basic_nack(self, delivery_tag, requeue):
        if requeue:
            self.close()
        self.delivery = None

    def close(self):
        if self.delivery:
            queue, body = self.delivery
            self.broker.messages[queue].appendleft(body)
            self.delivery = None
        self.is_open = False


@pytest.fixture
def system(monkeypatch):
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated test PostgreSQL database")
    screening_id = "test-" + uuid4().hex
    with psycopg.connect(dsn) as connection:
        migrate(connection)
        seed(connection)
        connection.execute(
            """
            INSERT INTO cinema_catalog.screenings
            VALUES (%s, 'saigon', 'room-1', clock_timestamp() + interval '1 day', 90000)
        """,
            (screening_id,),
        )
    broker = TestBroker()
    network = SimpleNamespace(payment_online=True)
    monkeypatch.setattr(pika, "BlockingConnection", broker.connection)
    settings = Settings(dsn, internal_key="test-key-that-is-long-enough", hold_seconds=30)
    with ExitStack() as clients:
        catalog = clients.enter_context(TestClient(catalog_api.create_app(settings)))
        payment = clients.enter_context(TestClient(payment_api.create_app(settings)))

        def downstream(http_request):
            target = catalog if http_request.url.port == 8001 else payment
            if target is payment and not network.payment_online:
                raise httpx.ConnectError("test payment API offline", request=http_request)
            return target.request(
                http_request.method,
                http_request.url.raw_path.decode(),
                headers=http_request.headers,
                content=http_request.content,
            )

        booking = clients.enter_context(
            TestClient(booking_api.create_app(settings, httpx.MockTransport(downstream)))
        )
        yield SimpleNamespace(web=booking, dsn=dsn, screening=screening_id, broker=broker, network=network)


def checkout(system, seats, key=None):
    return system.web.post(
        "/api/checkout",
        json={"screening_id": system.screening, "seats": seats},
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def simulate(system, booking_id, outcome="success", delay=0, key=None):
    return system.web.post(
        f"/api/bookings/{booking_id}/payment/simulate",
        json={"outcome": outcome, "delay_seconds": delay},
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def wait_for(operation, condition, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = operation()
        if condition(result):
            return result
        time.sleep(0.1)
    pytest.fail(f"Timed out. Last result: {result}")


def test_concurrent_hold_and_all_or_nothing(system):
    with ThreadPoolExecutor(max_workers=2) as callers:
        requests = [callers.submit(checkout, system, ["A5"]) for _ in range(2)]
        assert sorted(result.result().status_code for result in requests) == [201, 409]
    assert checkout(system, ["A4", "A5"]).status_code == 409
    seats = system.web.get(f"/api/screenings/{system.screening}/seats").json()
    assert {seat["label"]: seat["status"] for seat in seats}["A4"] == "AVAILABLE"


def test_checkout_retry_decline_and_ticket_qr(system):
    assert system.web.get("/").status_code == 200
    assert system.screening in [screening["id"] for screening in system.web.get("/api/screenings").json()]
    key = uuid4()
    result = checkout(system, ["A1", "D2"], key)
    assert result.status_code == 201, result.text
    booking, payment = (result.json()[name] for name in ("booking", "payment"))
    assert checkout(system, ["D2", "A1"], key).json()["payment"]["id"] == payment["id"]
    assert checkout(system, ["A2"], key).status_code == 409
    path = f"/api/bookings/{booking['id']}"
    assert simulate(system, booking["id"], "decline").status_code == 202
    wait_for(lambda: system.web.get(path + "/payment").json(), lambda row: row["status"] == "DECLINED")
    key = uuid4()
    assert simulate(system, booking["id"], key=key).status_code == 202
    assert simulate(system, booking["id"], key=key).status_code == 202
    assert simulate(system, booking["id"], "decline", key=key).status_code == 409
    confirmed = wait_for(lambda: system.web.get(path).json(), lambda row: row["status"] == "CONFIRMED")
    assert [ticket["seat"] for ticket in confirmed["tickets"]] == ["A1", "D2"]
    code = confirmed["tickets"][0]["code"]
    qr = system.web.get(f"/api/tickets/{code}/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"] == "image/svg+xml"
    assert system.web.get(f"/api/tickets/{code}").json()["seat"] == "A1"
    assert checkout(system, ["A1"]).status_code == 409


def test_late_payment_refunds_once_and_preserves_reallocated_seat(system):
    result = checkout(system, ["A1"]).json()
    booking, payment = result["booking"], result["payment"]
    path = f"/api/bookings/{booking['id']}"
    # Advance this hold's deadline without shortening the replacement booking's TTL.
    with psycopg.connect(system.dsn) as connection:
        connection.execute(
            "UPDATE cinema_booking.bookings SET expires_at = clock_timestamp() WHERE id = %s",
            (booking["id"],),
        )
        connection.execute(
            "UPDATE cinema_booking.screening_seats SET expires_at = clock_timestamp() WHERE booking_id = %s",
            (booking["id"],),
        )
    assert system.web.get(path).json()["status"] == "EXPIRED"
    replacement = checkout(system, ["A1"])
    assert replacement.status_code == 201
    assert simulate(system, booking["id"]).status_code == 202
    wait_for(lambda: system.web.get(path + "/payment").json(), lambda row: row["status"] == "REFUNDED")
    event = {"payment_id": payment["id"], "booking_id": booking["id"], "amount": booking["amount"]}
    queue = system.broker.messages[QUEUES["payment.succeeded"]]
    queue.append(json.dumps(event).encode())
    wait_for(lambda: len(queue), lambda size: size == 0)
    assert system.web.get(path).json()["tickets"] == []
    seats = system.web.get(f"/api/screenings/{system.screening}/seats").json()
    assert {seat["label"]: seat["status"] for seat in seats}["A1"] == "HELD"
    with psycopg.connect(system.dsn) as connection:
        owner = connection.execute(
            "SELECT booking_id FROM cinema_booking.screening_seats WHERE screening_id = %s AND label = 'A1'",
            (system.screening,),
        ).fetchone()[0]
        assert str(owner) == replacement.json()["booking"]["id"]
        assert (
            connection.execute(
                "SELECT count(*) FROM cinema_payment.refunds WHERE payment_id = %s", (payment["id"],)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM cinema_booking.outbox WHERE correlation_id = %s", (payment["id"],)
            ).fetchone()[0]
            == 1
        )


def test_checkout_resumes_when_payment_api_recovers(system):
    system.network.payment_online = False
    key = uuid4()
    assert checkout(system, ["A2"], key).status_code == 503
    assert checkout(system, ["A2"]).status_code == 409
    system.network.payment_online = True
    response = checkout(system, ["A2"], key)
    assert response.status_code == 201
    assert response.json()["payment"]["booking_id"] == response.json()["booking"]["id"]
    assert checkout(system, ["A2"], key).json()["payment"]["id"] == response.json()["payment"]["id"]


def test_outbox_survives_broker_stop(system):
    result = checkout(system, ["B4"]).json()
    booking, payment = result["booking"], result["payment"]
    path = f"/api/bookings/{booking['id']}"
    system.broker.online = False
    assert simulate(system, booking["id"]).status_code == 202
    wait_for(lambda: system.web.get(path + "/payment").json(), lambda row: row["status"] == "SUCCEEDED")
    with psycopg.connect(system.dsn) as connection:
        row = connection.execute(
            "SELECT published_at FROM cinema_payment.outbox WHERE correlation_id = %s", (payment["id"],)
        ).fetchone()
        assert row == (None,)
    assert system.web.get(path).json()["status"] == "HELD"
    system.broker.online = True
    confirmed = wait_for(lambda: system.web.get(path).json(), lambda row: row["status"] == "CONFIRMED")
    assert len(confirmed["tickets"]) == 1


def test_account_history_isolated_during_concurrent_checkout_and_on_another_device(system):
    credentials = [
        {"username": f"cinema-{uuid4().hex[:12]}", "password": "Mot cum tu dai cho dat ve"},
        {"username": f"cinema-{uuid4().hex[:12]}", "password": "Mot cum tu khac cho dat ve"},
    ]
    with (
        closing(TestClient(system.web.app)) as second,
        closing(TestClient(system.web.app)) as other_device,
        ThreadPoolExecutor(max_workers=2) as callers,
    ):
        browsers = [system.web, second]
        for browser, data in zip(browsers, credentials):
            response = browser.post("/api/auth/register", json=data)
            assert response.status_code == 201, response.text
            assert "HttpOnly" in response.headers["set-cookie"]
            assert response.json()["account"]["username"] == data["username"]
            assert "password_hash" not in response.json()["account"]

        calls = [
            callers.submit(checkout, SimpleNamespace(web=browser, screening=system.screening), ["A1", "D3"])
            for browser in browsers
        ]
        outcomes = [call.result() for call in calls]
        assert sorted(result.status_code for result in outcomes) == [201, 409]
        winner = next(index for index, result in enumerate(outcomes) if result.status_code == 201)
        owner, stranger = browsers[winner], browsers[1 - winner]
        order = outcomes[winner].json()["booking"]
        assert order["saved"] is True
        detail = f"/api/bookings/{order['id']}"
        saved = f"/api/my-bookings/{order['id']}"
        assert stranger.get(detail).status_code == 404
        assert stranger.get(detail + "/payment").status_code == 404
        assert stranger.put(saved).status_code == 404
        assert stranger.delete(saved).status_code == 204
        assert stranger.get("/api/my-bookings").json() == {"scope": "account", "bookings": []}

        assert other_device.get(detail).status_code == 404
        response = other_device.post("/api/auth/login", json=credentials[winner])
        assert response.status_code == 200, response.text
        assert other_device.get("/api/my-bookings").json()["bookings"][0]["id"] == order["id"]
        assert other_device.get(detail).json()["seats"] == ["A1", "D3"]
        status = simulate(SimpleNamespace(web=owner), order["id"])
        assert status.status_code == 202
        confirmed = wait_for(lambda: other_device.get(detail).json(), lambda row: row["status"] == "CONFIRMED")
        assert len(confirmed["tickets"]) == 2
        assert other_device.post("/api/auth/logout").status_code == 204
        assert other_device.get(detail).status_code == 404
        assert other_device.get("/api/auth/session").json() == {"account": None}

        assert owner.delete(saved).status_code == 204
        assert owner.get(detail).json()["saved"] is False
        assert owner.get(detail).json()["tickets"] == confirmed["tickets"]


def test_guest_history_is_private_to_browser_and_known_codes_can_be_saved(system):
    booking = checkout(system, ["B2"]).json()["booking"]
    assert booking["saved"] is True
    assert system.web.get("/api/my-bookings").json()["bookings"][0]["id"] == booking["id"]
    with closing(TestClient(system.web.app)) as other:
        assert other.get("/api/my-bookings").json() == {"scope": "browser", "bookings": []}
        detail = f"/api/bookings/{booking['id']}"
        saved = f"/api/my-bookings/{booking['id']}"
        assert other.get(detail).json()["saved"] is False
        assert other.put(saved).status_code == 204
        assert other.put(saved).status_code == 204
        assert len(other.get("/api/my-bookings").json()["bookings"]) == 1
        assert other.delete(saved).status_code == 204
        assert system.web.get(detail).json()["saved"] is True


def test_login_limits_repeated_attempts_and_rejects_cross_origin(system):
    username = f"limit-{uuid4().hex[:12]}"
    data = {"username": username, "password": "Thu sai mat khau nhieu lan"}
    cross_origin = system.web.post("/api/auth/login", json=data, headers={"Origin": "https://other.example"})
    assert cross_origin.status_code == 403
    short_password = "abcd-kin"
    invalid = system.web.post("/api/auth/register", json={"username": username, "password": short_password})
    assert invalid.status_code == 422 and short_password not in invalid.text
    for _ in range(8):
        assert system.web.post("/api/auth/login", json=data).status_code == 401
    limited = system.web.post("/api/auth/login", json=data)
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["Retry-After"]) <= 600
