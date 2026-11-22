from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from uuid import uuid4

import pika
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from cinema.common import Database
from cinema.contracts import PaymentEvent

LOGGER = logging.getLogger(__name__)
QUEUES = {
    "payment.succeeded": "cinema.v1.booking.payment_succeeded",
    "payment.refund_requested": "cinema.v1.payment.refund_requested",
}


class RejectedEvent(ValueError):
    pass


class Outbox:
    def __init__(self, db: Database, schema: str):
        self.db = db
        self.table = sql.Identifier(schema, "outbox")

    def add(self, connection, kind: str, event: PaymentEvent):
        connection.execute(
            sql.SQL("""
                INSERT INTO {} (id, kind, correlation_id, payload)
                VALUES (%s, %s, %s, %s) ON CONFLICT (kind, correlation_id) DO NOTHING
            """).format(self.table),
            (uuid4(), kind, event.payment_id, Jsonb(event.model_dump(mode="json"))),
        )

    def publish_next(self, channel) -> bool:
        with self.db.transaction() as connection:
            event = connection.execute(
                sql.SQL("""
                    SELECT id, kind, payload FROM {} WHERE published_at IS NULL
                    ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
                """).format(self.table)
            ).fetchone()
            if event is None:
                return False
            channel.basic_publish(
                exchange="",
                routing_key=QUEUES[event["kind"]],
                body=json.dumps(event["payload"]).encode(),
                properties=pika.BasicProperties(
                    delivery_mode=2, message_id=str(event["id"]), content_type="application/json"
                ),
                mandatory=True,
            )
            connection.execute(
                sql.SQL("UPDATE {} SET published_at = clock_timestamp() WHERE id = %s").format(self.table),
                (event["id"],),
            )
        return True


class Background:
    def __init__(
        self, name: str, tick: Callable[[], bool], cleanup: Callable[[], None] | None = None,
        *, idle_delay: float = 0.5,
    ):
        self.stop = threading.Event()
        self.idle_delay = idle_delay
        self.thread = threading.Thread(target=self.run, args=(tick, cleanup), name=name, daemon=True)

    def run(self, tick, cleanup):
        try:
            while not self.stop.is_set():
                try:
                    if not tick():
                        self.stop.wait(self.idle_delay)
                except Exception:
                    LOGGER.exception("Background task failed")
                    self.stop.wait(2)
        finally:
            if cleanup:
                cleanup()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=10)


class RabbitWorker:
    def __init__(self, url: str, incoming: str, outbox: Outbox, handle: Callable[[PaymentEvent], None]):
        self.url = url
        self.queue = QUEUES[incoming]
        self.outbox = outbox
        self.handle = handle
        self.connection = None
        self.channel = None

    def open(self):
        config = pika.URLParameters(self.url)
        config.socket_timeout = 3
        config.stack_timeout = 5
        config.blocked_connection_timeout = 5
        self.connection = pika.BlockingConnection(config)
        self.channel = self.connection.channel()
        for queue in QUEUES.values():
            dead_queue = f"{queue}.dead"
            self.channel.queue_declare(dead_queue, durable=True)
            self.channel.queue_declare(
                queue,
                durable=True,
                arguments={"x-dead-letter-exchange": "", "x-dead-letter-routing-key": dead_queue},
            )
        self.channel.confirm_delivery()

    def close(self):
        try:
            if self.connection and self.connection.is_open:
                self.connection.close()
        except pika.exceptions.AMQPError:
            LOGGER.warning("RabbitMQ connection closed")
        finally:
            self.connection = self.channel = None

    def run(self):
        try:
            if self.channel is None:
                self.open()
            self.connection.process_data_events(time_limit=0)
            method, _, body = self.channel.basic_get(self.queue, auto_ack=False)
            if method:
                try:
                    self.handle(PaymentEvent.model_validate_json(body))
                except (ValidationError, RejectedEvent):
                    LOGGER.warning("Rejected message on %s", self.queue)
                    self.channel.basic_nack(method.delivery_tag, requeue=False)
                else:
                    self.channel.basic_ack(method.delivery_tag)
            return self.outbox.publish_next(self.channel) or bool(method)
        except Exception:
            self.close()  # Closing the channel requeues unacknowledged deliveries.
            raise

    def background(self):
        # RabbitMQ's blocking connection must be closed on its owning thread.
        return Background(self.queue, self.run, self.close)
