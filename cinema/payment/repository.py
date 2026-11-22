from uuid import uuid4


class PaymentRepository:
    def create(self, connection, booking_id, amount):
        connection.execute(
            """
            INSERT INTO cinema_payment.payments (id, booking_id, amount)
            VALUES (%s, %s, %s) ON CONFLICT (booking_id) DO NOTHING
        """,
            (uuid4(), booking_id, amount),
        )
        return self.find(connection, booking_id)

    def find(self, connection, booking_id, *, lock=False):
        return connection.execute(
            """
            SELECT * FROM cinema_payment.payments WHERE booking_id = %s
        """
            + (" FOR UPDATE" if lock else ""),
            (booking_id,),
        ).fetchone()

    def attempt(self, connection, payment_id, key):
        return connection.execute(
            """
            SELECT * FROM cinema_payment.attempts WHERE payment_id = %s AND request_key = %s
        """,
            (payment_id, key),
        ).fetchone()

    def schedule(self, connection, payment_id, key, request):
        connection.execute(
            """
            INSERT INTO cinema_payment.attempts (payment_id, request_key, outcome, delay_seconds, due_at)
            VALUES (%s, %s, %s, %s, clock_timestamp() + make_interval(secs => %s))
        """,
            (payment_id, key, request.outcome, request.delay_seconds, request.delay_seconds),
        )
        return connection.execute(
            """
            UPDATE cinema_payment.payments SET status = 'PROCESSING' WHERE id = %s RETURNING *
        """,
            (payment_id,),
        ).fetchone()

    def next_due(self, connection):
        return connection.execute("""
            SELECT p.id, p.booking_id, p.amount, a.request_key, a.outcome
            FROM cinema_payment.attempts a JOIN cinema_payment.payments p ON p.id = a.payment_id
            WHERE a.finished_at IS NULL AND a.due_at <= statement_timestamp() AND p.status = 'PROCESSING'
            ORDER BY a.due_at LIMIT 1 FOR UPDATE OF p SKIP LOCKED
        """).fetchone()

    def finish(self, connection, payment, result):
        connection.execute(
            """
            UPDATE cinema_payment.attempts SET finished_at = clock_timestamp()
            WHERE payment_id = %s AND request_key = %s
        """,
            (payment["id"], payment["request_key"]),
        )
        connection.execute(
            """
            UPDATE cinema_payment.payments SET status = %s, provider_reference = %s WHERE id = %s
        """,
            ("SUCCEEDED" if result.approved else "DECLINED", result.reference, payment["id"]),
        )

    def refund(self, connection, payment_id, reference):
        connection.execute(
            """
            INSERT INTO cinema_payment.refunds (payment_id, provider_reference) VALUES (%s, %s)
        """,
            (payment_id, reference),
        )
        connection.execute(
            """
            UPDATE cinema_payment.payments SET status = 'REFUNDED' WHERE id = %s
        """,
            (payment_id,),
        )
