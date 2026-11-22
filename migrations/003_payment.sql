CREATE SCHEMA IF NOT EXISTS cinema_payment;
REVOKE ALL ON SCHEMA cinema_payment FROM PUBLIC;

CREATE TABLE IF NOT EXISTS cinema_payment.payments (
    id uuid PRIMARY KEY,
    booking_id uuid UNIQUE NOT NULL,
    amount integer NOT NULL CHECK (amount > 0),
    status text NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PROCESSING', 'DECLINED', 'SUCCEEDED', 'REFUNDED')),
    provider_reference text
);

CREATE TABLE IF NOT EXISTS cinema_payment.attempts (
    payment_id uuid NOT NULL REFERENCES cinema_payment.payments(id),
    request_key uuid NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('success', 'decline')),
    delay_seconds integer NOT NULL CHECK (delay_seconds BETWEEN 0 AND 120),
    due_at timestamptz NOT NULL,
    finished_at timestamptz,
    PRIMARY KEY (payment_id, request_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS payment_pending_idx
    ON cinema_payment.attempts (payment_id) WHERE finished_at IS NULL;
CREATE INDEX IF NOT EXISTS payment_due_idx
    ON cinema_payment.attempts (due_at) WHERE finished_at IS NULL;

CREATE TABLE IF NOT EXISTS cinema_payment.refunds (
    payment_id uuid PRIMARY KEY REFERENCES cinema_payment.payments(id),
    provider_reference text NOT NULL,
    refunded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS cinema_payment.outbox (
    id uuid PRIMARY KEY,
    kind text NOT NULL,
    correlation_id uuid NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz,
    UNIQUE (kind, correlation_id)
);
CREATE INDEX IF NOT EXISTS payment_outbox_idx
    ON cinema_payment.outbox (created_at, id) WHERE published_at IS NULL;
