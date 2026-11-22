CREATE TABLE IF NOT EXISTS cinema_booking.accounts (
    id uuid PRIMARY KEY,
    username text UNIQUE NOT NULL,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS cinema_booking.account_sessions (
    token_hash text PRIMARY KEY,
    account_id uuid NOT NULL REFERENCES cinema_booking.accounts(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS account_sessions_expiry_idx
    ON cinema_booking.account_sessions (expires_at);

CREATE TABLE IF NOT EXISTS cinema_booking.auth_attempts (
    subject text PRIMARY KEY,
    attempts integer NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_attempts_expiry_idx ON cinema_booking.auth_attempts (expires_at);

ALTER TABLE cinema_booking.bookings
    ADD COLUMN IF NOT EXISTS account_id uuid REFERENCES cinema_booking.accounts(id);

CREATE TABLE IF NOT EXISTS cinema_booking.saved_bookings (
    owner_key text NOT NULL,
    booking_id uuid NOT NULL REFERENCES cinema_booking.bookings(id) ON DELETE CASCADE,
    saved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_key, booking_id)
);
CREATE INDEX IF NOT EXISTS saved_bookings_recent_idx
    ON cinema_booking.saved_bookings (owner_key, saved_at DESC, booking_id);
