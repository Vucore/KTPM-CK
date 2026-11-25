from uuid import uuid4


class AccountRepository:
    def register(self, connection, account_id, username, password_hash):
        return connection.execute(
            """
            INSERT INTO cinema_booking.accounts (id, username, password_hash)
            VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING
            RETURNING id, username
            """,
            (account_id, username, password_hash),
        ).fetchone()

    def find(self, connection, username):
        return connection.execute(
            "SELECT id, username, password_hash FROM cinema_booking.accounts WHERE username = %s",
            (username,),
        ).fetchone()

    def find_by_id(self, connection, account_id):
        return connection.execute(
            """
            SELECT id, username, password_hash, full_name, email, phone, birth_date, points, total_spent, created_at
            FROM cinema_booking.accounts WHERE id = %s
            """,
            (account_id,),
        ).fetchone()

    def lock_account(self, connection, account_id):
        return connection.execute(
            """
            SELECT id, username, points, total_spent
            FROM cinema_booking.accounts WHERE id = %s FOR UPDATE
            """,
            (account_id,),
        ).fetchone()

    def update_profile(self, connection, account_id, full_name, email, phone, birth_date):
        return connection.execute(
            """
            UPDATE cinema_booking.accounts
            SET full_name = %s, email = %s, phone = %s, birth_date = %s
            WHERE id = %s
            RETURNING id, username, full_name, email, phone, birth_date, points, total_spent, created_at
            """,
            (full_name, email, phone, birth_date, account_id),
        ).fetchone()

    def record_point_transaction(self, connection, account_id, booking_id, kind, points_delta, description):
        inserted = connection.execute(
            """
            INSERT INTO cinema_booking.point_transactions
                (id, account_id, booking_id, kind, points_delta, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (booking_id, kind) DO NOTHING
            RETURNING points_delta
            """,
            (uuid4(), account_id, booking_id, kind, points_delta, description),
        ).fetchone()
        if not inserted:
            return False
        spent_delta = 0
        if kind == "EARN":
            spent_delta = max(0, points_delta * 10000)
        connection.execute(
            """
            UPDATE cinema_booking.accounts
            SET points = GREATEST(0, points + %s),
                total_spent = total_spent + %s
            WHERE id = %s
            """,
            (points_delta, spent_delta, account_id),
        )
        return True

    def add_spent_and_earn(self, connection, account_id, booking_id, amount, description):
        earned = max(1, amount // 10000)
        inserted = connection.execute(
            """
            INSERT INTO cinema_booking.point_transactions
                (id, account_id, booking_id, kind, points_delta, description)
            VALUES (%s, %s, %s, 'EARN', %s, %s)
            ON CONFLICT (booking_id, kind) DO NOTHING
            RETURNING id
            """,
            (uuid4(), account_id, booking_id, earned, description),
        ).fetchone()
        if inserted:
            connection.execute(
                """
                UPDATE cinema_booking.accounts
                SET points = points + %s,
                    total_spent = total_spent + %s
                WHERE id = %s
                """,
                (earned, amount, account_id),
            )
            return earned
        return 0

    def point_history(self, connection, account_id):
        return connection.execute(
            """
            SELECT id, booking_id, kind, points_delta, description, created_at
            FROM cinema_booking.point_transactions
            WHERE account_id = %s
            ORDER BY created_at DESC
            LIMIT 25
            """,
            (account_id,),
        ).fetchall()

    def update_password_hash(self, connection, account_id, previous, password_hash):
        connection.execute(
            "UPDATE cinema_booking.accounts SET password_hash = %s WHERE id = %s AND password_hash = %s",
            (password_hash, account_id, previous),
        )

    def start_session(self, connection, account_id, token_hash, lifetime):
        connection.execute(
            """
            INSERT INTO cinema_booking.account_sessions (token_hash, account_id, expires_at)
            VALUES (%s, %s, statement_timestamp() + %s)
            """,
            (token_hash, account_id, lifetime),
        )

    def session_account(self, connection, token_hash):
        return connection.execute(
            """
            SELECT account.id, account.username, account.full_name, account.email,
                   account.phone, account.birth_date, account.points, account.total_spent
            FROM cinema_booking.account_sessions AS session
            JOIN cinema_booking.accounts AS account ON account.id = session.account_id
            WHERE session.token_hash = %s AND session.expires_at > statement_timestamp()
            """,
            (token_hash,),
        ).fetchone()

    def revoke_session(self, connection, token_hash):
        connection.execute("DELETE FROM cinema_booking.account_sessions WHERE token_hash = %s", (token_hash,))

    def record_attempt(self, connection, subject, lifetime, limit):
        return connection.execute(
            """
            INSERT INTO cinema_booking.auth_attempts AS quota (subject, attempts, expires_at)
            VALUES (%s, 1, statement_timestamp() + %s)
            ON CONFLICT (subject) DO UPDATE SET
                attempts = CASE WHEN quota.expires_at <= statement_timestamp() THEN 1
                                ELSE least(quota.attempts + 1, %s) END,
                expires_at = CASE WHEN quota.expires_at <= statement_timestamp()
                                  THEN excluded.expires_at ELSE quota.expires_at END
            RETURNING attempts, ceil(extract(epoch FROM (expires_at - statement_timestamp()))) AS retry_after
            """,
            (subject, lifetime, limit + 1),
        ).fetchone()

    def delete_expired(self, connection):
        connection.execute("DELETE FROM cinema_booking.account_sessions WHERE expires_at <= statement_timestamp()")
        connection.execute("DELETE FROM cinema_booking.auth_attempts WHERE expires_at <= statement_timestamp()")
