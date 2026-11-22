from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from cinema.common import Database, Settings, configure_http

SCREENINGS = """
    SELECT s.id, s.movie_id, m.title, m.genre, m.duration_minutes, m.synopsis,
           a.name AS auditorium, s.auditorium_id, s.starts_at, s.base_price
    FROM cinema_catalog.screenings s
    JOIN cinema_catalog.movies m ON m.id = s.movie_id
    JOIN cinema_catalog.auditoriums a ON a.id = s.auditorium_id
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
    return app
