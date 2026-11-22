CREATE SCHEMA IF NOT EXISTS cinema_catalog;
REVOKE ALL ON SCHEMA cinema_catalog FROM PUBLIC;

CREATE TABLE IF NOT EXISTS cinema_catalog.movies (
    id text PRIMARY KEY,
    title text NOT NULL,
    genre text NOT NULL,
    duration_minutes integer NOT NULL CHECK (duration_minutes > 0),
    synopsis text NOT NULL
);

CREATE TABLE IF NOT EXISTS cinema_catalog.auditoriums (
    id text PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE IF NOT EXISTS cinema_catalog.seats (
    auditorium_id text NOT NULL REFERENCES cinema_catalog.auditoriums(id),
    label text NOT NULL,
    seat_type text NOT NULL CHECK (seat_type IN ('STANDARD', 'PREMIUM')),
    PRIMARY KEY (auditorium_id, label)
);

CREATE TABLE IF NOT EXISTS cinema_catalog.screenings (
    id text PRIMARY KEY,
    movie_id text NOT NULL REFERENCES cinema_catalog.movies(id),
    auditorium_id text NOT NULL REFERENCES cinema_catalog.auditoriums(id),
    starts_at timestamptz NOT NULL,
    base_price integer NOT NULL CHECK (base_price > 0)
);
