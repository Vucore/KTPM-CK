ALTER TABLE cinema_booking.bookings
    ADD COLUMN IF NOT EXISTS checkout_phase text NOT NULL DEFAULT 'LEGACY'
        CHECK (checkout_phase IN ('LEGACY', 'DRAFT', 'READY')),
    ADD COLUMN IF NOT EXISTS hold_owner text,
    ADD COLUMN IF NOT EXISTS options_hash text,
    ADD COLUMN IF NOT EXISTS pay_by timestamptz,
    ADD COLUMN IF NOT EXISTS attempt_key uuid;
