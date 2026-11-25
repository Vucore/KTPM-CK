-- DUT Cinema user-facing extensions: multi-cinema, formats, movie profiles,
-- concessions, promotions, cinema corner blog, couple seats, and D-Star membership.

DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT conname INTO constraint_name
    FROM pg_constraint
    WHERE conrelid = 'cinema_catalog.seats'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%seat_type%';
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE cinema_catalog.seats DROP CONSTRAINT %I', constraint_name);
    END IF;
    ALTER TABLE cinema_catalog.seats
        ADD CONSTRAINT seats_seat_type_check CHECK (seat_type IN ('STANDARD', 'PREMIUM', 'COUPLE'));

    SELECT conname INTO constraint_name
    FROM pg_constraint
    WHERE conrelid = 'cinema_booking.screening_seats'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%seat_type%';
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE cinema_booking.screening_seats DROP CONSTRAINT %I', constraint_name);
    END IF;
    ALTER TABLE cinema_booking.screening_seats
        ADD CONSTRAINT screening_seats_seat_type_check CHECK (seat_type IN ('STANDARD', 'PREMIUM', 'COUPLE'));

    SELECT conname INTO constraint_name
    FROM pg_constraint
    WHERE conrelid = 'cinema_booking.bookings'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%status%HELD%';
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE cinema_booking.bookings DROP CONSTRAINT %I', constraint_name);
    END IF;
    ALTER TABLE cinema_booking.bookings
        ADD CONSTRAINT bookings_status_check CHECK (status IN ('HELD', 'EXPIRED', 'CONFIRMED', 'CANCELLED'));
END $$;

CREATE TABLE IF NOT EXISTS cinema_catalog.cinemas (
    id text PRIMARY KEY,
    name text NOT NULL,
    city text NOT NULL,
    address text NOT NULL,
    hotline text NOT NULL,
    formats text[] NOT NULL DEFAULT ARRAY['2D'],
    opening_hours text NOT NULL DEFAULT '08:30 - 23:30',
    price_table jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS cinema_catalog.auditorium_cinemas (
    auditorium_id text PRIMARY KEY REFERENCES cinema_catalog.auditoriums(id),
    cinema_id text NOT NULL REFERENCES cinema_catalog.cinemas(id),
    screen_format text NOT NULL DEFAULT '2D'
);

CREATE TABLE IF NOT EXISTS cinema_catalog.movie_profiles (
    movie_id text PRIMARY KEY REFERENCES cinema_catalog.movies(id),
    release_status text NOT NULL DEFAULT 'NOW_SHOWING'
        CHECK (release_status IN ('NOW_SHOWING', 'COMING_SOON')),
    age_rating text NOT NULL DEFAULT 'P'
        CHECK (age_rating IN ('P', 'K', 'T13', 'T16', 'T18')),
    rating numeric(3, 1) NOT NULL DEFAULT 8.5,
    release_date date,
    director text NOT NULL DEFAULT '',
    cast_list text NOT NULL DEFAULT '',
    country text NOT NULL DEFAULT 'Việt Nam',
    trailer_url text NOT NULL DEFAULT '',
    is_imax boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS cinema_catalog.screening_details (
    screening_id text PRIMARY KEY REFERENCES cinema_catalog.screenings(id),
    format text NOT NULL DEFAULT '2D Phụ đề',
    is_special boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS cinema_catalog.concessions (
    id text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL,
    price integer NOT NULL CHECK (price > 0),
    category text NOT NULL,
    badge text,
    sort_order integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cinema_catalog.promotions (
    id text PRIMARY KEY,
    title text NOT NULL,
    tag text NOT NULL,
    summary text NOT NULL,
    code text UNIQUE,
    discount_type text NOT NULL CHECK (discount_type IN ('PERCENT', 'FIXED', 'INFO')),
    discount_value integer NOT NULL DEFAULT 0,
    min_amount integer NOT NULL DEFAULT 0,
    valid_until text NOT NULL,
    details text NOT NULL,
    sort_order integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cinema_catalog.blog_posts (
    id text PRIMARY KEY,
    category text NOT NULL CHECK (category IN ('review', 'blog')),
    title text NOT NULL,
    summary text NOT NULL,
    content text NOT NULL,
    author text NOT NULL,
    published_label text NOT NULL,
    movie_id text REFERENCES cinema_catalog.movies(id),
    views integer NOT NULL DEFAULT 100,
    sort_order integer NOT NULL DEFAULT 0
);

ALTER TABLE cinema_booking.bookings
    ADD COLUMN IF NOT EXISTS cinema_name text NOT NULL DEFAULT 'DUT Nguyễn Du',
    ADD COLUMN IF NOT EXISTS screening_format text NOT NULL DEFAULT '2D Phụ đề',
    ADD COLUMN IF NOT EXISTS concessions jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS concessions_amount integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS discount_amount integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS promo_code text,
    ADD COLUMN IF NOT EXISTS points_redeemed integer NOT NULL DEFAULT 0;

ALTER TABLE cinema_booking.accounts
    ADD COLUMN IF NOT EXISTS full_name text,
    ADD COLUMN IF NOT EXISTS email text,
    ADD COLUMN IF NOT EXISTS phone text,
    ADD COLUMN IF NOT EXISTS birth_date date,
    ADD COLUMN IF NOT EXISTS points integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_spent integer NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS cinema_booking.point_transactions (
    id uuid PRIMARY KEY,
    account_id uuid NOT NULL REFERENCES cinema_booking.accounts(id) ON DELETE CASCADE,
    booking_id uuid REFERENCES cinema_booking.bookings(id) ON DELETE SET NULL,
    kind text NOT NULL CHECK (kind IN ('EARN', 'REDEEM', 'RESTORE', 'BONUS')),
    points_delta integer NOT NULL,
    description text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (booking_id, kind)
);
CREATE INDEX IF NOT EXISTS point_transactions_account_idx
    ON cinema_booking.point_transactions (account_id, created_at DESC);
