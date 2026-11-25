from psycopg.types.json import Jsonb


class ScreeningSeatRepository:
    def sync(self, connection, screening):
        connection.execute(
            """
            INSERT INTO cinema_booking.screening_seats (screening_id, label, seat_type)
            SELECT %s, seat.label, seat.seat_type
            FROM jsonb_to_recordset(%s) AS seat(label text, seat_type text)
            ON CONFLICT (screening_id, label) DO NOTHING
        """,
            (screening["id"], Jsonb(screening["seats"])),
        )

    def list(self, connection, screening_id):
        return connection.execute(
            """
            SELECT label, seat_type,
                   CASE WHEN status = 'HELD' AND expires_at <= statement_timestamp()
                        THEN 'AVAILABLE' ELSE status END AS status
            FROM cinema_booking.screening_seats
            WHERE screening_id = %s ORDER BY label
        """,
            (screening_id,),
        ).fetchall()

    def lock(self, connection, screening_id, seats):
        return connection.execute(
            """
            SELECT label, status, seat_type, expires_at, booking_id
            FROM cinema_booking.screening_seats WHERE screening_id = %s AND label = ANY(%s)
            ORDER BY label FOR UPDATE
        """,
            (screening_id, seats),
        ).fetchall()

    def hold(self, connection, booking):
        connection.execute(
            """
            UPDATE cinema_booking.screening_seats
            SET status = 'HELD', booking_id = %(id)s, expires_at = %(expires_at)s
            WHERE screening_id = %(screening_id)s AND label = ANY(%(seats)s)
        """,
            booking,
        )

    def release(self, connection, booking):
        connection.execute(
            """
            UPDATE cinema_booking.screening_seats
            SET status = 'AVAILABLE', booking_id = NULL, expires_at = NULL
            WHERE screening_id = %(screening_id)s AND label = ANY(%(seats)s)
              AND booking_id = %(id)s AND status = 'HELD'
        """,
            booking,
        )

    def sell(self, connection, booking):
        return connection.execute(
            """
            UPDATE cinema_booking.screening_seats SET status = 'SOLD', expires_at = NULL
            WHERE screening_id = %(screening_id)s AND label = ANY(%(seats)s)
              AND booking_id = %(id)s AND status = 'HELD'
        """,
            booking,
        ).rowcount


class BookingRepository:
    def by_key(self, connection, key):
        return connection.execute(
            """
            SELECT * FROM cinema_booking.bookings WHERE request_key = %s
        """,
            (key,),
        ).fetchone()

    def lock_key(self, connection, key):
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(key),))

    def insert(self, connection, booking):
        row = {**booking, "concessions": Jsonb(booking.get("concessions", []))}
        connection.execute(
            """
            INSERT INTO cinema_booking.bookings
                (id, request_key, request_hash, screening_id, movie_title, starts_at, auditorium,
                 seats, customer_name, amount, status, expires_at, account_id,
                 cinema_name, screening_format, concessions, concessions_amount,
                 discount_amount, promo_code, points_redeemed)
            VALUES (%(id)s, %(request_key)s, %(request_hash)s, %(screening_id)s, %(movie_title)s, %(starts_at)s,
                    %(auditorium)s, %(seats)s, %(customer_name)s, %(amount)s, 'HELD', %(expires_at)s, %(account_id)s,
                    %(cinema_name)s, %(screening_format)s, %(concessions)s, %(concessions_amount)s,
                    %(discount_amount)s, %(promo_code)s, %(points_redeemed)s)
        """,
            row,
        )

    def lock(self, connection, booking_id):
        return connection.execute(
            """
            SELECT * FROM cinema_booking.bookings WHERE id = %s FOR UPDATE
        """,
            (booking_id,),
        ).fetchone()

    def next_expired(self, connection):
        return connection.execute("""
            SELECT * FROM cinema_booking.bookings
            WHERE status = 'HELD' AND expires_at <= statement_timestamp()
            ORDER BY expires_at LIMIT 1 FOR UPDATE SKIP LOCKED
        """).fetchone()

    def expire(self, connection, booking_id):
        connection.execute(
            "UPDATE cinema_booking.bookings SET status = 'EXPIRED' WHERE id = %s", (booking_id,)
        )

    def cancel(self, connection, booking_id):
        connection.execute(
            "UPDATE cinema_booking.bookings SET status = 'CANCELLED' WHERE id = %s AND status = 'HELD'",
            (booking_id,),
        )

    def confirm(self, connection, booking_id, payment_id):
        connection.execute(
            """
            UPDATE cinema_booking.bookings SET status = 'CONFIRMED', payment_id = %s WHERE id = %s
        """,
            (payment_id, booking_id),
        )

    def detail(self, connection, booking_id, viewer):
        return connection.execute(
            """
            SELECT id, screening_id, movie_title, starts_at, auditorium, seats, customer_name, amount, expires_at,
                   cinema_name, screening_format, concessions, concessions_amount,
                   discount_amount, promo_code, points_redeemed,
                   statement_timestamp() AS server_now,
                   CASE WHEN status = 'HELD' AND expires_at <= statement_timestamp()
                        THEN 'EXPIRED' ELSE status END AS status,
                   EXISTS (SELECT 1 FROM cinema_booking.saved_bookings AS saved
                           WHERE saved.owner_key = %s AND saved.booking_id = booking.id) AS saved
            FROM cinema_booking.bookings AS booking
            WHERE id = %s AND (account_id IS NULL OR account_id = %s)
        """,
            (viewer.history_key, booking_id, viewer.account_id),
        ).fetchone()

    def saved_list(self, connection, viewer):
        return connection.execute(
            """
            SELECT booking.id, booking.movie_title, booking.starts_at, booking.auditorium, booking.seats,
                   booking.cinema_name, booking.screening_format, booking.amount,
                   CASE WHEN booking.status = 'HELD' AND booking.expires_at <= statement_timestamp()
                        THEN 'EXPIRED' ELSE booking.status END AS status
            FROM cinema_booking.saved_bookings AS saved
            JOIN cinema_booking.bookings AS booking ON booking.id = saved.booking_id
            WHERE saved.owner_key = %s AND (booking.account_id IS NULL OR booking.account_id = %s)
            ORDER BY saved.saved_at DESC, saved.booking_id
            """,
            (viewer.history_key, viewer.account_id),
        ).fetchall()

    def save(self, connection, history_key, booking_id):
        connection.execute(
            """
            INSERT INTO cinema_booking.saved_bookings (owner_key, booking_id)
            VALUES (%s, %s)
            ON CONFLICT (owner_key, booking_id) DO NOTHING
            """,
            (history_key, booking_id),
        )

    def forget(self, connection, history_key, booking_id):
        connection.execute(
            """
            DELETE FROM cinema_booking.saved_bookings WHERE owner_key = %s AND booking_id = %s
            """,
            (history_key, booking_id),
        )


class TicketRepository:
    def insert(self, connection, ticket):
        connection.execute(
            """
            INSERT INTO cinema_booking.tickets (code, booking_id, screening_id, seat, customer_name)
            VALUES (%(code)s, %(booking_id)s, %(screening_id)s, %(seat)s, %(customer_name)s)
        """,
            ticket,
        )

    def list(self, connection, booking_id):
        return connection.execute(
            """
            SELECT code, seat, customer_name FROM cinema_booking.tickets WHERE booking_id = %s ORDER BY seat
        """,
            (booking_id,),
        ).fetchall()

    def find(self, connection, code):
        return connection.execute(
            """
            SELECT t.code, t.seat, b.movie_title, b.auditorium, b.cinema_name, b.screening_format, b.starts_at
            FROM cinema_booking.tickets t JOIN cinema_booking.bookings b ON b.id = t.booking_id
            WHERE t.code = %s
        """,
            (code,),
        ).fetchone()
