from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout


@dataclass(frozen=True)
class Settings:
    database_url: str
    rabbitmq_url: str = "amqp://guest:guest@127.0.0.1:5672/%2F"
    catalog_url: str = "http://127.0.0.1:8001"
    payment_url: str = "http://127.0.0.1:8002"
    internal_key: str = ""
    hold_seconds: int = 300

    @classmethod
    def load(cls, service: str) -> Settings:
        load_dotenv()
        database_url = os.getenv(f"{service.upper()}_DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL")
        if not database_url:
            raise RuntimeError("Set SUPABASE_DATABASE_URL in .env")
        internal_key = os.getenv("INTERNAL_API_KEY", "")
        if service in {"booking", "payment"} and len(internal_key) < 24:
            raise RuntimeError("Set INTERNAL_API_KEY to a random value of at least 24 characters")
        hold_seconds = int(os.getenv("HOLD_SECONDS", "300"))
        if not 1 <= hold_seconds <= 3600:
            raise ValueError("HOLD_SECONDS must be 1–3600")
        return cls(
            database_url,
            os.getenv("RABBITMQ_URL", cls.rabbitmq_url),
            os.getenv("CATALOG_URL", cls.catalog_url),
            os.getenv("PAYMENT_URL", cls.payment_url),
            internal_key,
            hold_seconds,
        )


class Database:
    def __init__(self, dsn: str):
        self.pool = ConnectionPool(
            dsn,
            kwargs={"row_factory": dict_row, "prepare_threshold": None, "connect_timeout": 5},
            min_size=0,
            max_size=6,
            timeout=6,
            open=False,
        )

    def transaction(self):
        return self.pool.connection()

    def ping(self):
        with self.transaction() as connection:
            connection.execute("SELECT 1")


def configure_http(app: FastAPI, db: Database) -> None:
    @app.get("/health")
    def health():
        db.ping()
        return {"status": "ok"}

    @app.exception_handler(PoolTimeout)
    @app.exception_handler(OperationalError)
    async def database_unavailable(request: Request, error: Exception):
        return JSONResponse(status_code=503, content={"detail": "Database tạm thời không khả dụng"})


def require_key(received: str, expected: str) -> None:
    if not expected or not hmac.compare_digest(received.encode(), expected.encode()):
        raise HTTPException(403, "Từ chối truy cập")


class ServiceClient:
    def __init__(self, client: httpx.Client):
        self.client = client

    def request(self, method: str, url: str, **kwargs):
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.RequestError as error:
            raise HTTPException(503, "Dịch vụ tạm thời gián đoạn. Hãy thử lại.") from error
        if response.status_code == 404:
            raise HTTPException(404, "Không tìm thấy dữ liệu")
        if response.status_code in {409, 422}:
            detail = response.json().get("detail", "Yêu cầu không hợp lệ")
            raise HTTPException(response.status_code, detail)
        if response.is_error:
            raise HTTPException(503, "Dịch vụ tạm thời gián đoạn. Hãy thử lại.")
        if response.status_code == 204:
            return None
        return response.json()
