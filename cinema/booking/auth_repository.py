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
            SELECT account.id, account.username FROM cinema_booking.account_sessions AS session
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
