CREATE SCHEMA IF NOT EXISTS cinema_booking;
REVOKE ALL ON SCHEMA cinema_booking FROM PUBLIC;

CREATE TABLE IF NOT EXISTS cinema_booking.bookings (
    id uuid PRIMARY KEY,
    request_key uuid UNIQUE NOT NULL,
    request_hash text NOT NULL,
    screening_id text NOT NULL,
    movie_title text NOT NULL,
    starts_at timestamptz NOT NULL,
    auditorium text NOT NULL,
    seats text[] NOT NULL CHECK (cardinality(seats) BETWEEN 1 AND 8),
    customer_name text,
    amount integer NOT NULL CHECK (amount > 0),
    status text NOT NULL CHECK (status IN ('HELD', 'EXPIRED', 'CONFIRMED')),
    expires_at timestamptz NOT NULL,
    payment_id uuid UNIQUE,
    CHECK ((status = 'CONFIRMED') = (payment_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS booking_due_idx
    ON cinema_booking.bookings (expires_at) WHERE status = 'HELD';

CREATE TABLE IF NOT EXISTS cinema_booking.screening_seats (
    screening_id text NOT NULL,
    label text NOT NULL,
    seat_type text NOT NULL CHECK (seat_type IN ('STANDARD', 'PREMIUM')),
    status text NOT NULL DEFAULT 'AVAILABLE' CHECK (status IN ('AVAILABLE', 'HELD', 'SOLD')),
    booking_id uuid REFERENCES cinema_booking.bookings(id),
    expires_at timestamptz,
    PRIMARY KEY (screening_id, label),
    CHECK (
        (status = 'AVAILABLE' AND booking_id IS NULL AND expires_at IS NULL)
        OR (status = 'HELD' AND booking_id IS NOT NULL AND expires_at IS NOT NULL)
        OR (status = 'SOLD' AND booking_id IS NOT NULL AND expires_at IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS cinema_booking.tickets (
    code uuid PRIMARY KEY,
    booking_id uuid NOT NULL REFERENCES cinema_booking.bookings(id),
    screening_id text NOT NULL,
    seat text NOT NULL,
    customer_name text,
    UNIQUE (screening_id, seat)
);

CREATE TABLE IF NOT EXISTS cinema_booking.outbox (
    id uuid PRIMARY KEY,
    kind text NOT NULL,
    correlation_id uuid NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz,
    UNIQUE (kind, correlation_id)
);
CREATE INDEX IF NOT EXISTS booking_outbox_idx
    ON cinema_booking.outbox (created_at, id) WHERE published_at IS NULL;
