from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ("cinema_catalog", "cinema_booking", "cinema_payment")
SHOW_TIMES = ("11:00", "15:30", "20:00")


def migrate(connection):
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        connection.execute(path.read_text(), prepare=False)


def seed(connection):
    connection.execute(
        """
        INSERT INTO cinema_catalog.movies VALUES
            ('saigon', 'Sài Gòn Sau Mưa', 'Tâm lý · Tình cảm', 108,
             'Hai người lạ gặp nhau trong một đêm mưa và cùng lần theo những ký ức về thành phố.'),
            ('orbit', 'Quỹ Đạo Cuối', 'Khoa học viễn tưởng', 124,
             'Một đội kỹ sư phải tìm đường trở về khi trạm nghiên cứu đổi quỹ đạo.')
        ON CONFLICT (id) DO NOTHING;
        INSERT INTO cinema_catalog.auditoriums VALUES ('room-1', 'Phòng 1')
        ON CONFLICT (id) DO NOTHING;
        INSERT INTO cinema_catalog.seats
        SELECT 'room-1', row_name || seat_no,
               CASE WHEN row_name = 'D' THEN 'PREMIUM' ELSE 'STANDARD' END
        FROM unnest(ARRAY['A', 'B', 'C', 'D']) AS rows(row_name)
        CROSS JOIN generate_series(1, 8) AS numbers(seat_no)
        ON CONFLICT DO NOTHING;
        INSERT INTO cinema_catalog.screenings VALUES
            ('saigon-evening', 'saigon', 'room-1', date_trunc('minute', now()) + interval '1 day', 90000),
            ('orbit-evening', 'orbit', 'room-1', date_trunc('minute', now()) + interval '2 days', 95000)
        ON CONFLICT (id) DO NOTHING;
    """,
        prepare=False,
    )
    seed_theatrical_films(connection)


def seed_theatrical_films(connection):
    films = json.loads((ROOT / "cinema/demo_movies.json").read_text(encoding="utf-8"))
    first_showings = [(film["id"], "demo") for film in films]
    reruns = [(film["id"], "rerun") for film in films[:6]]
    screenings = []
    for index, (movie_id, label) in enumerate(first_showings + reruns):
        day, slot = divmod(index, len(SHOW_TIMES))
        screenings.append((f"{movie_id}-{label}", movie_id, 3 + day, SHOW_TIMES[slot], 75000 + slot * 10000))
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.movies (id, title, genre, duration_minutes, synopsis)
            VALUES (%(id)s, %(title)s, %(genre)s, %(duration)s, %(synopsis)s)
            ON CONFLICT (id) DO NOTHING
            """,
            films,
        )
        cursor.executemany(
            """
            INSERT INTO cinema_catalog.screenings (id, movie_id, auditorium_id, starts_at, base_price)
            VALUES (%s, %s, 'room-1',
                ((now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date + %s + %s::time)
                    AT TIME ZONE 'Asia/Ho_Chi_Minh',
                %s)
            ON CONFLICT (id) DO NOTHING
            """,
            screenings,
        )


def main():
    parser = argparse.ArgumentParser(description="Apply schemas to Supabase and optionally load demo data")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--runtime-roles", nargs=3, metavar=("CATALOG", "BOOKING", "PAYMENT"))
    args = parser.parse_args()
    load_dotenv()
    if not (dsn := os.getenv("SUPABASE_DATABASE_URL")):
        parser.error("Set SUPABASE_DATABASE_URL in .env")
    with psycopg.connect(dsn, connect_timeout=8) as connection:
        migrate(connection)
        if args.seed:
            seed(connection)
        for schema, role in zip(SCHEMAS, args.runtime_roles or []):
            identifiers = {"schema": sql.Identifier(schema), "role": sql.Identifier(role)}
            connection.execute(sql.SQL("GRANT USAGE ON SCHEMA {schema} TO {role}").format(**identifiers))
            permissions = "SELECT" if schema == "cinema_catalog" else "SELECT, INSERT, UPDATE"
            connection.execute(
                sql.SQL("GRANT " + permissions + " ON ALL TABLES IN SCHEMA {schema} TO {role}").format(
                    **identifiers
                )
            )
            if schema == "cinema_booking":
                connection.execute(sql.SQL(
                    "GRANT DELETE ON cinema_booking.saved_bookings, cinema_booking.account_sessions, "
                    "cinema_booking.auth_attempts TO {role}"
                ).format(**identifiers))
    print("Đã áp dụng schema" + (" và nạp dữ liệu mẫu." if args.seed else "."))


if __name__ == "__main__":
    main()
