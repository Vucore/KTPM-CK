-- DUT Cinema Admin & Staff Portal extensions:
-- Role-based access control (USER, STAFF, ADMIN), QR ticket check-in tracking,
-- custom poster URLs, and active toggles for concessions & promotions.

ALTER TABLE cinema_booking.accounts
    ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'USER';

DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT conname INTO constraint_name
    FROM pg_constraint
    WHERE conrelid = 'cinema_booking.accounts'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%role%';
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE cinema_booking.accounts DROP CONSTRAINT %I', constraint_name);
    END IF;
    ALTER TABLE cinema_booking.accounts
        ADD CONSTRAINT accounts_role_check CHECK (role IN ('USER', 'STAFF', 'ADMIN'));
END $$;

ALTER TABLE cinema_booking.tickets
    ADD COLUMN IF NOT EXISTS checked_in_at timestamptz,
    ADD COLUMN IF NOT EXISTS checked_in_by uuid REFERENCES cinema_booking.accounts(id) ON DELETE SET NULL;

ALTER TABLE cinema_catalog.movie_profiles
    ADD COLUMN IF NOT EXISTS poster_url text NOT NULL DEFAULT '';

ALTER TABLE cinema_catalog.concessions
    ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;

ALTER TABLE cinema_catalog.promotions
    ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;
