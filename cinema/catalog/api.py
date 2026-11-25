from contextlib import asynccontextmanager
from datetime import timedelta
from string import ascii_uppercase
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from psycopg.types.json import Jsonb

from cinema.common import Database, Settings, configure_http, require_key
from cinema.contracts import (
    AdminAuditoriumInput,
    AdminBlogPostInput,
    AdminCinemaInput,
    AdminConcessionInput,
    AdminMovieInput,
    AdminPromotionInput,
    AdminScreeningInput,
)
from cinema.setup import PRICE_TABLE_2D, PRICE_TABLE_IMAX

SCREENINGS = """
    SELECT s.id, s.movie_id, m.title, m.genre, m.duration_minutes, m.synopsis,
           a.name AS auditorium, s.auditorium_id, s.starts_at, s.base_price,
           COALESCE(c.id, 'dut-nguyen-du') AS cinema_id,
           COALESCE(c.name, 'DUT Nguyễn Du') AS cinema_name,
           COALESCE(c.city, 'TP.HCM') AS city,
           COALESCE(sd.format, ac.screen_format, '2D Phụ đề') AS format,
           COALESCE(sd.is_special, false) AS is_special,
           COALESCE(mp.age_rating, 'P') AS age_rating,
           COALESCE(mp.rating::float, 8.5) AS rating,
           COALESCE(mp.is_imax, false) AS is_imax,
           COALESCE(mp.release_status, 'NOW_SHOWING') AS release_status,
           COALESCE(mp.director, '') AS director,
           COALESCE(mp.cast_list, '') AS cast_list,
           COALESCE(mp.country, 'Việt Nam') AS country,
           COALESCE(mp.trailer_url, '') AS trailer_url,
           COALESCE(mp.poster_url, '') AS poster_url,
           mp.release_date
    FROM cinema_catalog.screenings s
    JOIN cinema_catalog.movies m ON m.id = s.movie_id
    JOIN cinema_catalog.auditoriums a ON a.id = s.auditorium_id
    LEFT JOIN cinema_catalog.auditorium_cinemas ac ON ac.auditorium_id = a.id
    LEFT JOIN cinema_catalog.cinemas c ON c.id = ac.cinema_id
    LEFT JOIN cinema_catalog.movie_profiles mp ON mp.movie_id = m.id
    LEFT JOIN cinema_catalog.screening_details sd ON sd.screening_id = s.id
"""

MOVIES = """
    SELECT m.id, m.title, m.genre, m.duration_minutes, m.synopsis,
           COALESCE(mp.release_status, 'NOW_SHOWING') AS release_status,
           COALESCE(mp.age_rating, 'P') AS age_rating,
           COALESCE(mp.rating::float, 8.5) AS rating,
           mp.release_date,
           COALESCE(mp.director, '') AS director,
           COALESCE(mp.cast_list, '') AS cast_list,
           COALESCE(mp.country, 'Việt Nam') AS country,
           COALESCE(mp.trailer_url, '') AS trailer_url,
           COALESCE(mp.poster_url, '') AS poster_url,
           COALESCE(mp.is_imax, false) AS is_imax
    FROM cinema_catalog.movies m
    LEFT JOIN cinema_catalog.movie_profiles mp ON mp.movie_id = m.id
"""


class CatalogRepository:
    def __init__(self, db: Database):
        self.db = db

    def upcoming(self):
        with self.db.transaction() as connection:
            return connection.execute(
                SCREENINGS + " WHERE s.starts_at > clock_timestamp() ORDER BY s.starts_at, s.id"
            ).fetchall()

    def screening(self, screening_id: str):
        with self.db.transaction() as connection:
            screening = connection.execute(SCREENINGS + " WHERE s.id = %s", (screening_id,)).fetchone()
            if not screening:
                raise HTTPException(404, "Không tìm thấy suất chiếu")
            screening["seats"] = connection.execute(
                """
                SELECT label, seat_type FROM cinema_catalog.seats
                WHERE auditorium_id = %s ORDER BY label
            """,
                (screening["auditorium_id"],),
            ).fetchall()
            return screening

    def movie(self, movie_id: str):
        with self.db.transaction() as connection:
            movie = connection.execute(MOVIES + " WHERE m.id = %s", (movie_id,)).fetchone()
            if not movie:
                raise HTTPException(404, "Không tìm thấy phim")
            movie["screenings"] = connection.execute(
                SCREENINGS + " WHERE s.movie_id = %s AND s.starts_at > clock_timestamp() ORDER BY s.starts_at, s.id",
                (movie_id,),
            ).fetchall()
            return movie

    def home(self):
        with self.db.transaction() as connection:
            screenings = connection.execute(
                SCREENINGS + " WHERE s.starts_at > clock_timestamp() ORDER BY s.starts_at, s.id"
            ).fetchall()
            coming_soon = connection.execute(
                MOVIES + " WHERE COALESCE(mp.release_status, 'NOW_SHOWING') = 'COMING_SOON' ORDER BY mp.release_date, m.title"
            ).fetchall()
            cinemas = connection.execute(
                "SELECT * FROM cinema_catalog.cinemas ORDER BY city, name"
            ).fetchall()
            concessions = connection.execute(
                "SELECT * FROM cinema_catalog.concessions WHERE COALESCE(active, true) = true ORDER BY sort_order, id"
            ).fetchall()
            promotions = connection.execute(
                "SELECT * FROM cinema_catalog.promotions WHERE COALESCE(active, true) = true ORDER BY sort_order, id"
            ).fetchall()
            blog_posts = connection.execute(
                "SELECT * FROM cinema_catalog.blog_posts ORDER BY sort_order, id"
            ).fetchall()
            return {
                "screenings": screenings,
                "coming_soon": coming_soon,
                "cinemas": cinemas,
                "concessions": concessions,
                "promotions": promotions,
                "blog_posts": blog_posts,
            }

    def checkout_options(self):
        with self.db.transaction() as connection:
            concessions = connection.execute(
                """
                SELECT id, name, price FROM cinema_catalog.concessions
                WHERE COALESCE(active, true) = true ORDER BY sort_order, id
                """
            ).fetchall()
            promotions = connection.execute(
                """
                SELECT id, title, code, discount_type, discount_value, min_amount
                FROM cinema_catalog.promotions
                WHERE COALESCE(active, true) = true
                  AND code IS NOT NULL AND discount_type IN ('PERCENT', 'FIXED')
                """
            ).fetchall()
            return {"concessions": concessions, "promotions": promotions}

    def admin_snapshot(self):
        with self.db.transaction() as connection:
            movies = connection.execute(
                """
                SELECT m.id, m.title, m.genre, m.duration_minutes, m.synopsis,
                       COALESCE(mp.release_status, 'NOW_SHOWING') AS release_status,
                       COALESCE(mp.age_rating, 'P') AS age_rating,
                       COALESCE(mp.rating::float, 8.5) AS rating,
                       mp.release_date,
                       COALESCE(mp.director, '') AS director,
                       COALESCE(mp.cast_list, '') AS cast_list,
                       COALESCE(mp.country, 'Việt Nam') AS country,
                       COALESCE(mp.trailer_url, '') AS trailer_url,
                       COALESCE(mp.poster_url, '') AS poster_url,
                       COALESCE(mp.is_imax, false) AS is_imax,
                       count(s.id)::int AS screening_count
                FROM cinema_catalog.movies m
                LEFT JOIN cinema_catalog.movie_profiles mp ON mp.movie_id = m.id
                LEFT JOIN cinema_catalog.screenings s ON s.movie_id = m.id
                GROUP BY m.id, mp.movie_id
                ORDER BY COALESCE(mp.release_status, 'NOW_SHOWING') DESC, m.title
                """
            ).fetchall()
            cinemas = connection.execute(
                "SELECT * FROM cinema_catalog.cinemas ORDER BY city, name"
            ).fetchall()
            auditoriums = connection.execute(
                """
                SELECT a.id, a.name,
                       COALESCE(ac.cinema_id, 'dut-nguyen-du') AS cinema_id,
                       COALESCE(c.name, 'DUT Nguyễn Du') AS cinema_name,
                       COALESCE(ac.screen_format, '2D Phụ đề') AS screen_format,
                       count(st.label)::int AS seat_count
                FROM cinema_catalog.auditoriums a
                LEFT JOIN cinema_catalog.auditorium_cinemas ac ON ac.auditorium_id = a.id
                LEFT JOIN cinema_catalog.cinemas c ON c.id = ac.cinema_id
                LEFT JOIN cinema_catalog.seats st ON st.auditorium_id = a.id
                GROUP BY a.id, ac.auditorium_id, c.id
                ORDER BY a.id
                """
            ).fetchall()
            screenings = connection.execute(
                SCREENINGS + " ORDER BY s.starts_at DESC, s.id LIMIT 120"
            ).fetchall()
            concessions = connection.execute(
                "SELECT * FROM cinema_catalog.concessions ORDER BY sort_order, id"
            ).fetchall()
            promotions = connection.execute(
                "SELECT * FROM cinema_catalog.promotions ORDER BY sort_order, id"
            ).fetchall()
            blog_posts = connection.execute(
                "SELECT * FROM cinema_catalog.blog_posts ORDER BY sort_order, id"
            ).fetchall()
            return {
                "movies": movies,
                "cinemas": cinemas,
                "auditoriums": auditoriums,
                "screenings": screenings,
                "concessions": concessions,
                "promotions": promotions,
                "blog_posts": blog_posts,
            }

    def save_movie(self, payload: AdminMovieInput):
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO cinema_catalog.movies (id, title, genre, duration_minutes, synopsis)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    genre = EXCLUDED.genre,
                    duration_minutes = EXCLUDED.duration_minutes,
                    synopsis = EXCLUDED.synopsis
                """,
                (payload.id, payload.title, payload.genre, payload.duration_minutes, payload.synopsis),
            )
            connection.execute(
                """
                INSERT INTO cinema_catalog.movie_profiles
                    (movie_id, release_status, age_rating, rating, release_date, director,
                     cast_list, country, trailer_url, poster_url, is_imax)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (movie_id) DO UPDATE SET
                    release_status = EXCLUDED.release_status,
                    age_rating = EXCLUDED.age_rating,
                    rating = EXCLUDED.rating,
                    release_date = EXCLUDED.release_date,
                    director = EXCLUDED.director,
                    cast_list = EXCLUDED.cast_list,
                    country = EXCLUDED.country,
                    trailer_url = EXCLUDED.trailer_url,
                    poster_url = EXCLUDED.poster_url,
                    is_imax = EXCLUDED.is_imax
                """,
                (
                    payload.id,
                    payload.release_status,
                    payload.age_rating,
                    payload.rating,
                    payload.release_date,
                    payload.director,
                    payload.cast_list,
                    payload.country,
                    payload.trailer_url,
                    payload.poster_url,
                    payload.is_imax,
                ),
            )
            return connection.execute(MOVIES + " WHERE m.id = %s", (payload.id,)).fetchone()

    def delete_movie(self, movie_id: str):
        with self.db.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM cinema_catalog.movies WHERE id = %s", (movie_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(404, "Không tìm thấy phim")
            has_screenings = connection.execute(
                "SELECT 1 FROM cinema_catalog.screenings WHERE movie_id = %s LIMIT 1", (movie_id,)
            ).fetchone()
            if has_screenings:
                raise HTTPException(409, "Không thể xóa phim đã có suất chiếu. Hãy xóa các suất chiếu trước.")
            connection.execute(
                "UPDATE cinema_catalog.blog_posts SET movie_id = NULL WHERE movie_id = %s", (movie_id,)
            )
            connection.execute("DELETE FROM cinema_catalog.movie_profiles WHERE movie_id = %s", (movie_id,))
            connection.execute("DELETE FROM cinema_catalog.movies WHERE id = %s", (movie_id,))

    def save_cinema(self, payload: AdminCinemaInput):
        price_table = PRICE_TABLE_IMAX if any("IMAX" in f.upper() for f in payload.formats) else PRICE_TABLE_2D
        with self.db.transaction() as connection:
            return connection.execute(
                """
                INSERT INTO cinema_catalog.cinemas
                    (id, name, city, address, hotline, formats, opening_hours, price_table)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    city = EXCLUDED.city,
                    address = EXCLUDED.address,
                    hotline = EXCLUDED.hotline,
                    formats = EXCLUDED.formats,
                    opening_hours = EXCLUDED.opening_hours,
                    price_table = EXCLUDED.price_table
                RETURNING *
                """,
                (
                    payload.id,
                    payload.name,
                    payload.city,
                    payload.address,
                    payload.hotline,
                    payload.formats,
                    payload.opening_hours,
                    Jsonb(price_table),
                ),
            ).fetchone()

    def save_auditorium(self, payload: AdminAuditoriumInput):
        with self.db.transaction() as connection:
            cinema = connection.execute(
                "SELECT id, name FROM cinema_catalog.cinemas WHERE id = %s", (payload.cinema_id,)
            ).fetchone()
            if not cinema:
                raise HTTPException(404, "Không tìm thấy cụm rạp")
            connection.execute(
                """
                INSERT INTO cinema_catalog.auditoriums (id, name)
                VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """,
                (payload.id, payload.name),
            )
            connection.execute(
                """
                INSERT INTO cinema_catalog.auditorium_cinemas (auditorium_id, cinema_id, screen_format)
                VALUES (%s, %s, %s)
                ON CONFLICT (auditorium_id) DO UPDATE SET
                    cinema_id = EXCLUDED.cinema_id,
                    screen_format = EXCLUDED.screen_format
                """,
                (payload.id, payload.cinema_id, payload.screen_format),
            )

            seats = []
            row_idx = 0
            for _ in range(payload.standard_rows):
                letter = ascii_uppercase[row_idx]
                row_idx += 1
                for num in range(1, payload.seats_per_row + 1):
                    seats.append((payload.id, f"{letter}{num}", "STANDARD"))
            for _ in range(payload.vip_rows):
                letter = ascii_uppercase[row_idx]
                row_idx += 1
                for num in range(1, payload.seats_per_row + 1):
                    seats.append((payload.id, f"{letter}{num}", "PREMIUM"))
            if payload.couple_seats > 0:
                letter = ascii_uppercase[row_idx]
                for num in range(1, payload.couple_seats + 1):
                    seats.append((payload.id, f"{letter}{num}", "COUPLE"))

            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO cinema_catalog.seats (auditorium_id, label, seat_type)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (auditorium_id, label) DO UPDATE SET seat_type = EXCLUDED.seat_type
                    """,
                    seats,
                )
            return {
                "id": payload.id,
                "name": payload.name,
                "cinema_id": payload.cinema_id,
                "cinema_name": cinema["name"],
                "screen_format": payload.screen_format,
                "seat_count": len(seats),
            }

    def save_screening(self, payload: AdminScreeningInput, screening_id: str | None = None):
        target_id = screening_id or payload.id or f"{payload.movie_id}-{uuid4().hex[:8]}"
        with self.db.transaction() as connection:
            movie = connection.execute(
                "SELECT id, duration_minutes FROM cinema_catalog.movies WHERE id = %s",
                (payload.movie_id,),
            ).fetchone()
            if not movie:
                raise HTTPException(404, "Không tìm thấy phim")
            auditorium = connection.execute(
                "SELECT id FROM cinema_catalog.auditoriums WHERE id = %s",
                (payload.auditorium_id,),
            ).fetchone()
            if not auditorium:
                raise HTTPException(404, "Không tìm thấy phòng chiếu")

            duration = timedelta(minutes=movie["duration_minutes"] + 15)
            ends_at = payload.starts_at + duration
            conflict = connection.execute(
                """
                SELECT s.id, m.title, s.starts_at
                FROM cinema_catalog.screenings s
                JOIN cinema_catalog.movies m ON m.id = s.movie_id
                WHERE s.auditorium_id = %s
                  AND s.id <> %s
                  AND s.starts_at < %s
                  AND (s.starts_at + make_interval(mins => m.duration_minutes + 15)) > %s
                LIMIT 1
                """,
                (payload.auditorium_id, target_id, ends_at, payload.starts_at),
            ).fetchone()
            if conflict:
                raise HTTPException(
                    409,
                    f"Trùng lịch phòng chiếu với suất {conflict['title']} ({conflict['id']}).",
                )

            connection.execute(
                """
                INSERT INTO cinema_catalog.screenings (id, movie_id, auditorium_id, starts_at, base_price)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    movie_id = EXCLUDED.movie_id,
                    auditorium_id = EXCLUDED.auditorium_id,
                    starts_at = EXCLUDED.starts_at,
                    base_price = EXCLUDED.base_price
                """,
                (target_id, payload.movie_id, payload.auditorium_id, payload.starts_at, payload.base_price),
            )
            connection.execute(
                """
                INSERT INTO cinema_catalog.screening_details (screening_id, format, is_special)
                VALUES (%s, %s, %s)
                ON CONFLICT (screening_id) DO UPDATE SET
                    format = EXCLUDED.format,
                    is_special = EXCLUDED.is_special
                """,
                (target_id, payload.format, payload.is_special),
            )
            return connection.execute(SCREENINGS + " WHERE s.id = %s", (target_id,)).fetchone()

    def delete_screening(self, screening_id: str):
        with self.db.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM cinema_catalog.screenings WHERE id = %s", (screening_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(404, "Không tìm thấy suất chiếu")
            connection.execute(
                "DELETE FROM cinema_catalog.screening_details WHERE screening_id = %s", (screening_id,)
            )
            connection.execute("DELETE FROM cinema_catalog.screenings WHERE id = %s", (screening_id,))

    def save_concession(self, payload: AdminConcessionInput):
        with self.db.transaction() as connection:
            return connection.execute(
                """
                INSERT INTO cinema_catalog.concessions
                    (id, name, description, price, category, badge, active, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    price = EXCLUDED.price,
                    category = EXCLUDED.category,
                    badge = EXCLUDED.badge,
                    active = EXCLUDED.active,
                    sort_order = EXCLUDED.sort_order
                RETURNING *
                """,
                (
                    payload.id,
                    payload.name,
                    payload.description,
                    payload.price,
                    payload.category,
                    payload.badge,
                    payload.active,
                    payload.sort_order,
                ),
            ).fetchone()

    def delete_concession(self, concession_id: str):
        with self.db.transaction() as connection:
            deleted = connection.execute(
                "DELETE FROM cinema_catalog.concessions WHERE id = %s RETURNING id", (concession_id,)
            ).fetchone()
            if not deleted:
                raise HTTPException(404, "Không tìm thấy combo bắp nước")

    def save_promotion(self, payload: AdminPromotionInput):
        with self.db.transaction() as connection:
            if payload.code:
                duplicate = connection.execute(
                    "SELECT id FROM cinema_catalog.promotions WHERE code = %s AND id <> %s",
                    (payload.code, payload.id),
                ).fetchone()
                if duplicate:
                    raise HTTPException(409, f"Mã khuyến mãi {payload.code} đã thuộc chương trình khác.")
            return connection.execute(
                """
                INSERT INTO cinema_catalog.promotions
                    (id, title, tag, summary, code, discount_type, discount_value,
                     min_amount, valid_until, details, active, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    tag = EXCLUDED.tag,
                    summary = EXCLUDED.summary,
                    code = EXCLUDED.code,
                    discount_type = EXCLUDED.discount_type,
                    discount_value = EXCLUDED.discount_value,
                    min_amount = EXCLUDED.min_amount,
                    valid_until = EXCLUDED.valid_until,
                    details = EXCLUDED.details,
                    active = EXCLUDED.active,
                    sort_order = EXCLUDED.sort_order
                RETURNING *
                """,
                (
                    payload.id,
                    payload.title,
                    payload.tag,
                    payload.summary,
                    payload.code,
                    payload.discount_type,
                    payload.discount_value,
                    payload.min_amount,
                    payload.valid_until,
                    payload.details,
                    payload.active,
                    payload.sort_order,
                ),
            ).fetchone()

    def delete_promotion(self, promotion_id: str):
        with self.db.transaction() as connection:
            deleted = connection.execute(
                "DELETE FROM cinema_catalog.promotions WHERE id = %s RETURNING id", (promotion_id,)
            ).fetchone()
            if not deleted:
                raise HTTPException(404, "Không tìm thấy chương trình khuyến mãi")

    def save_blog_post(self, payload: AdminBlogPostInput):
        with self.db.transaction() as connection:
            if payload.movie_id:
                movie = connection.execute(
                    "SELECT id FROM cinema_catalog.movies WHERE id = %s", (payload.movie_id,)
                ).fetchone()
                if not movie:
                    raise HTTPException(404, "Mã phim liên kết không tồn tại")
            return connection.execute(
                """
                INSERT INTO cinema_catalog.blog_posts
                    (id, category, title, summary, content, author, published_label, movie_id, views, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    category = EXCLUDED.category,
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    content = EXCLUDED.content,
                    author = EXCLUDED.author,
                    published_label = EXCLUDED.published_label,
                    movie_id = EXCLUDED.movie_id,
                    views = EXCLUDED.views,
                    sort_order = EXCLUDED.sort_order
                RETURNING *
                """,
                (
                    payload.id,
                    payload.category,
                    payload.title,
                    payload.summary,
                    payload.content,
                    payload.author,
                    payload.published_label,
                    payload.movie_id,
                    payload.views,
                    payload.sort_order,
                ),
            ).fetchone()

    def delete_blog_post(self, post_id: str):
        with self.db.transaction() as connection:
            deleted = connection.execute(
                "DELETE FROM cinema_catalog.blog_posts WHERE id = %s RETURNING id", (post_id,)
            ).fetchone()
            if not deleted:
                raise HTTPException(404, "Không tìm thấy bài viết")


def create_app(settings: Settings | None = None):
    settings = settings or Settings.load("catalog")
    db = Database(settings.database_url)
    repository = CatalogRepository(db)

    def authorize(x_internal_key: Annotated[str, Header()] = ""):
        require_key(x_internal_key, settings.internal_key)

    @asynccontextmanager
    async def lifespan(app):
        db.pool.open()
        try:
            yield
        finally:
            db.pool.close()

    app = FastAPI(title="Catalog Service", lifespan=lifespan)
    configure_http(app, db)
    protected = [Depends(authorize)]

    app.get("/screenings")(repository.upcoming)
    app.get("/screenings/{screening_id}")(repository.screening)
    app.get("/movies/{movie_id}")(repository.movie)
    app.get("/catalog/home")(repository.home)
    app.get("/catalog/checkout-options")(repository.checkout_options)

    app.get("/admin/catalog", dependencies=protected)(repository.admin_snapshot)
    app.post("/admin/movies", status_code=201, dependencies=protected)(repository.save_movie)

    @app.put("/admin/movies/{movie_id}", dependencies=protected)
    def update_movie(movie_id: str, payload: AdminMovieInput):
        return repository.save_movie(payload.model_copy(update={"id": movie_id}))

    app.delete("/admin/movies/{movie_id}", status_code=204, dependencies=protected)(repository.delete_movie)

    app.post("/admin/cinemas", status_code=201, dependencies=protected)(repository.save_cinema)

    @app.put("/admin/cinemas/{cinema_id}", dependencies=protected)
    def update_cinema(cinema_id: str, payload: AdminCinemaInput):
        return repository.save_cinema(payload.model_copy(update={"id": cinema_id}))

    app.post("/admin/auditoriums", status_code=201, dependencies=protected)(repository.save_auditorium)

    app.post("/admin/screenings", status_code=201, dependencies=protected)(repository.save_screening)

    @app.put("/admin/screenings/{screening_id}", dependencies=protected)
    def update_screening(screening_id: str, payload: AdminScreeningInput):
        return repository.save_screening(payload, screening_id)

    app.delete("/admin/screenings/{screening_id}", status_code=204, dependencies=protected)(
        repository.delete_screening
    )

    app.post("/admin/concessions", status_code=201, dependencies=protected)(repository.save_concession)

    @app.put("/admin/concessions/{concession_id}", dependencies=protected)
    def update_concession(concession_id: str, payload: AdminConcessionInput):
        return repository.save_concession(payload.model_copy(update={"id": concession_id}))

    app.delete("/admin/concessions/{concession_id}", status_code=204, dependencies=protected)(
        repository.delete_concession
    )

    app.post("/admin/promotions", status_code=201, dependencies=protected)(repository.save_promotion)

    @app.put("/admin/promotions/{promotion_id}", dependencies=protected)
    def update_promotion(promotion_id: str, payload: AdminPromotionInput):
        return repository.save_promotion(payload.model_copy(update={"id": promotion_id}))

    app.delete("/admin/promotions/{promotion_id}", status_code=204, dependencies=protected)(
        repository.delete_promotion
    )

    app.post("/admin/blog-posts", status_code=201, dependencies=protected)(repository.save_blog_post)

    @app.put("/admin/blog-posts/{post_id}", dependencies=protected)
    def update_blog_post(post_id: str, payload: AdminBlogPostInput):
        return repository.save_blog_post(payload.model_copy(update={"id": post_id}))

    app.delete("/admin/blog-posts/{post_id}", status_code=204, dependencies=protected)(
        repository.delete_blog_post
    )

    return app
