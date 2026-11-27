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

    def notify_change(self, connection, screening_id):
        # PostgreSQL delivers NOTIFY only after the surrounding transaction commits.
        connection.execute("SELECT pg_notify('cinema_seat_changes', %s)", (screening_id,))

    def hold(self, connection, booking):
        connection.execute(
            """
            UPDATE cinema_booking.screening_seats
            SET status = 'HELD', booking_id = %(id)s, expires_at = %(expires_at)s
            WHERE screening_id = %(screening_id)s AND label = ANY(%(seats)s)
        """,
            booking,
        )

        self.notify_change(connection, booking["screening_id"])

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

        self.notify_change(connection, booking["screening_id"])

    def sell(self, connection, booking):
        sold = connection.execute(
            """
            UPDATE cinema_booking.screening_seats SET status = 'SOLD', expires_at = NULL
            WHERE screening_id = %(screening_id)s AND label = ANY(%(seats)s)
              AND booking_id = %(id)s AND status = 'HELD'
        """,
            booking,
        ).rowcount
        self.notify_change(connection, booking["screening_id"])
        return sold


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
                 discount_amount, promo_code, points_redeemed, checkout_phase, hold_owner)
            VALUES (%(id)s, %(request_key)s, %(request_hash)s, %(screening_id)s, %(movie_title)s, %(starts_at)s,
                    %(auditorium)s, %(seats)s, %(customer_name)s, %(amount)s, 'HELD', %(expires_at)s, %(account_id)s,
                    %(cinema_name)s, %(screening_format)s, %(concessions)s, %(concessions_amount)s,
                    %(discount_amount)s, %(promo_code)s, %(points_redeemed)s, %(checkout_phase)s, %(hold_owner)s)
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
                   discount_amount, promo_code, points_redeemed, checkout_phase, pay_by,
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

    def has_active_bookings_for_screening(self, connection, screening_id: str) -> bool:
        row = connection.execute(
            """
            SELECT 1 FROM cinema_booking.bookings
            WHERE screening_id = %s
              AND (status = 'CONFIRMED' OR (status = 'HELD' AND expires_at > statement_timestamp()))
            LIMIT 1
            """,
            (screening_id,),
        ).fetchone()
        return bool(row)

    def admin_overview(self, connection):
        kpi = connection.execute(
            """
            SELECT
                COALESCE(SUM(amount) FILTER (WHERE status = 'CONFIRMED'), 0)::int AS total_revenue,
                COALESCE(SUM(concessions_amount) FILTER (WHERE status = 'CONFIRMED'), 0)::int AS concessions_revenue,
                COALESCE(SUM(discount_amount) FILTER (WHERE status = 'CONFIRMED'), 0)::int AS discount_total,
                COUNT(*) FILTER (WHERE status = 'CONFIRMED')::int AS confirmed_bookings,
                COUNT(*) FILTER (WHERE status = 'HELD' AND expires_at > statement_timestamp())::int AS held_bookings,
                COUNT(*) FILTER (
                    WHERE status = 'EXPIRED' OR (status = 'HELD' AND expires_at <= statement_timestamp())
                )::int AS expired_bookings,
                COUNT(*) FILTER (WHERE status = 'CANCELLED')::int AS cancelled_bookings,
                (SELECT COUNT(*)::int FROM cinema_booking.tickets) AS tickets_sold,
                (SELECT COUNT(*)::int FROM cinema_booking.tickets WHERE checked_in_at IS NOT NULL) AS tickets_checked_in,
                (SELECT COUNT(*)::int FROM cinema_booking.accounts) AS total_members
            FROM cinema_booking.bookings
            """
        ).fetchone()
        by_movie = connection.execute(
            """
            SELECT movie_title,
                   COUNT(*)::int AS bookings_count,
                   COALESCE(SUM(cardinality(seats)), 0)::int AS seats_sold,
                   COALESCE(SUM(amount), 0)::int AS revenue
            FROM cinema_booking.bookings
            WHERE status = 'CONFIRMED'
            GROUP BY movie_title
            ORDER BY revenue DESC, movie_title
            """
        ).fetchall()
        by_cinema = connection.execute(
            """
            SELECT cinema_name,
                   COUNT(*)::int AS bookings_count,
                   COALESCE(SUM(cardinality(seats)), 0)::int AS seats_sold,
                   COALESCE(SUM(amount), 0)::int AS revenue
            FROM cinema_booking.bookings
            WHERE status = 'CONFIRMED'
            GROUP BY cinema_name
            ORDER BY revenue DESC, cinema_name
            """
        ).fetchall()
        return {"kpi": kpi, "by_movie": by_movie, "by_cinema": by_cinema}

    def admin_bookings(self, connection, status_filter: str | None = None, query: str | None = None):
        rows = connection.execute(
            """
            SELECT b.id, b.screening_id, b.movie_title, b.starts_at, b.auditorium,
                   b.cinema_name, b.screening_format, b.seats, b.customer_name,
                   b.amount, b.concessions_amount, b.discount_amount, b.promo_code,
                   b.points_redeemed, a.username AS account_username,
                   CASE WHEN b.status = 'HELD' AND b.expires_at <= statement_timestamp()
                        THEN 'EXPIRED' ELSE b.status END AS status
            FROM cinema_booking.bookings b
            LEFT JOIN cinema_booking.accounts a ON a.id = b.account_id
            ORDER BY b.starts_at DESC, b.id
            LIMIT 100
            """
        ).fetchall()
        if status_filter:
            rows = [row for row in rows if row["status"] == status_filter]
        if query:
            needle = query.strip().lower()
            rows = [
                row
                for row in rows
                if needle in str(row["id"]).lower()
                or needle in (row["movie_title"] or "").lower()
                or needle in (row["customer_name"] or "").lower()
                or needle in (row["account_username"] or "").lower()
            ]
        return rows


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
            SELECT code, seat, customer_name, checked_in_at
            FROM cinema_booking.tickets WHERE booking_id = %s ORDER BY seat
        """,
            (booking_id,),
        ).fetchall()

    def find(self, connection, code):
        return connection.execute(
            """
            SELECT t.code, t.seat, t.customer_name, t.checked_in_at,
                   b.id AS booking_id, b.movie_title, b.auditorium, b.cinema_name,
                   b.screening_format, b.starts_at
            FROM cinema_booking.tickets t JOIN cinema_booking.bookings b ON b.id = t.booking_id
            WHERE t.code = %s
        """,
            (code,),
        ).fetchone()

    def lock_ticket(self, connection, code):
        return connection.execute(
            """
            SELECT t.code, t.seat, t.customer_name, t.checked_in_at,
                   b.id AS booking_id, b.movie_title, b.auditorium, b.cinema_name,
                   b.screening_format, b.starts_at
            FROM cinema_booking.tickets t JOIN cinema_booking.bookings b ON b.id = t.booking_id
            WHERE t.code = %s
            FOR UPDATE OF t
            """,
            (code,),
        ).fetchone()

    def mark_checked_in(self, connection, code, staff_account_id):
        return connection.execute(
            """
            UPDATE cinema_booking.tickets
            SET checked_in_at = clock_timestamp(), checked_in_by = %s
            WHERE code = %s
            RETURNING checked_in_at
            """,
            (staff_account_id, code),
        ).fetchone()
