from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from cinema.common import Database, Settings, configure_http

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
                "SELECT * FROM cinema_catalog.concessions ORDER BY sort_order, id"
            ).fetchall()
            promotions = connection.execute(
                "SELECT * FROM cinema_catalog.promotions ORDER BY sort_order, id"
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
                "SELECT id, name, price FROM cinema_catalog.concessions ORDER BY sort_order, id"
            ).fetchall()
            promotions = connection.execute(
                """
                SELECT id, title, code, discount_type, discount_value, min_amount
                FROM cinema_catalog.promotions
                WHERE code IS NOT NULL AND discount_type IN ('PERCENT', 'FIXED')
                """
            ).fetchall()
            return {"concessions": concessions, "promotions": promotions}


def create_app(settings: Settings | None = None):
    settings = settings or Settings.load("catalog")
    db = Database(settings.database_url)
    repository = CatalogRepository(db)

    @asynccontextmanager
    async def lifespan(app):
        db.pool.open()
        try:
            yield
        finally:
            db.pool.close()

    app = FastAPI(title="Catalog Service", lifespan=lifespan)
    configure_http(app, db)
    app.get("/screenings")(repository.upcoming)
    app.get("/screenings/{screening_id}")(repository.screening)
    app.get("/movies/{movie_id}")(repository.movie)
    app.get("/catalog/home")(repository.home)
    app.get("/catalog/checkout-options")(repository.checkout_options)
    return app
