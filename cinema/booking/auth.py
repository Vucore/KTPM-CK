from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from secrets import token_hex
from typing import Annotated
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException
from pydantic import BaseModel, Field, SecretStr, StringConstraints, field_validator

from cinema.booking.auth_repository import AccountRepository
from cinema.booking.domain import member_tier
from cinema.common import Database

SESSION_LIFETIME = timedelta(days=30)
ATTEMPT_WINDOW = timedelta(minutes=10)


class Credentials(BaseModel):
    username: Annotated[str, StringConstraints(min_length=3, max_length=32, pattern=r"^[a-z0-9_.-]+$")]
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class SignUp(Credentials):
    password: SecretStr = Field(min_length=15, max_length=128)


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
    birth_date: date | None = None

    @field_validator("full_name", "email", "phone", mode="before")
    @classmethod
    def clean_optional(cls, value):
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed or None
        return value


class PasswordChange(BaseModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=15, max_length=128)


@dataclass(frozen=True)
class BookingViewer:
    account_id: UUID | None = None
    history_key: str | None = None


def token_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, db: Database, accounts: AccountRepository, passwords: PasswordHasher):
        self.db = db
        self.accounts = accounts
        self.passwords = passwords
        self.dummy_hash = passwords.hash(token_hex(32))

    def register(self, credentials: SignUp, source: str, previous: str | None):
        self._throttle("register", credentials.username, source)
        password_hash = self.passwords.hash(credentials.password.get_secret_value())
        with self.db.transaction() as connection:
            account = self.accounts.register(connection, uuid4(), credentials.username, password_hash)
            if not account:
                raise HTTPException(409, "Tên đăng nhập đã được sử dụng")
            return account, self._start_session(connection, account["id"], previous)

    def login(self, credentials: Credentials, source: str, previous: str | None):
        self._throttle("login", credentials.username, source)
        with self.db.transaction() as connection:
            account = self.accounts.find(connection, credentials.username)
        password_hash = account["password_hash"] if account else self.dummy_hash
        password = credentials.password.get_secret_value()
        try:
            verified = self.passwords.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            verified = False
        if not account or not verified:
            raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng")

        replacement = (
            self.passwords.hash(password) if self.passwords.check_needs_rehash(password_hash) else None
        )
        with self.db.transaction() as connection:
            if replacement:
                self.accounts.update_password_hash(connection, account["id"], password_hash, replacement)
            token = self._start_session(connection, account["id"], previous)
        return {"id": account["id"], "username": account["username"]}, token

    def _start_session(self, connection, account_id, previous):
        if previous:
            self.accounts.revoke_session(connection, token_digest(previous))
        token = token_hex(32)
        self.accounts.start_session(connection, account_id, token_digest(token), SESSION_LIFETIME)
        return token

    def current_account(self, token: str | None):
        if not token:
            return None
        with self.db.transaction() as connection:
            account = self.accounts.session_account(connection, token_digest(token))
            if not account:
                return None
            account["tier"] = member_tier(account["total_spent"])
            return account

    def profile(self, account_id: UUID):
        with self.db.transaction() as connection:
            account = self.accounts.find_by_id(connection, account_id)
            if not account:
                raise HTTPException(404, "Không tìm thấy tài khoản")
            account.pop("password_hash", None)
            account["tier"] = member_tier(account["total_spent"])
            account["point_history"] = self.accounts.point_history(connection, account_id)
            return account

    def update_profile(self, account_id: UUID, data: ProfileUpdate):
        with self.db.transaction() as connection:
            updated = self.accounts.update_profile(
                connection, account_id, data.full_name, data.email, data.phone, data.birth_date
            )
            if not updated:
                raise HTTPException(404, "Không tìm thấy tài khoản")
            updated["tier"] = member_tier(updated["total_spent"])
            return updated

    def change_password(self, account_id: UUID, data: PasswordChange):
        with self.db.transaction() as connection:
            account = self.accounts.find_by_id(connection, account_id)
        if not account:
            raise HTTPException(404, "Không tìm thấy tài khoản")
        try:
            verified = self.passwords.verify(
                account["password_hash"], data.current_password.get_secret_value()
            )
        except (VerificationError, InvalidHashError):
            verified = False
        if not verified:
            raise HTTPException(401, "Mật khẩu hiện tại không đúng")
        new_hash = self.passwords.hash(data.new_password.get_secret_value())
        with self.db.transaction() as connection:
            self.accounts.update_password_hash(connection, account_id, account["password_hash"], new_hash)

    def logout(self, token: str | None):
        if token:
            with self.db.transaction() as connection:
                self.accounts.revoke_session(connection, token_digest(token))

    def _throttle(self, action, username, source):
        limits = [(source, 120 if action == "login" else 30), (f"{source}:{username}", 8)]
        retry_after = []
        with self.db.transaction() as connection:
            for subject, limit in limits:
                record = self.accounts.record_attempt(
                    connection, token_digest(f"{action}:{subject}"), ATTEMPT_WINDOW, limit
                )
                if record["attempts"] > limit:
                    retry_after.append(int(record["retry_after"]))
        if retry_after:
            delay = str(max(1, max(retry_after)))
            raise HTTPException(429, "Quá nhiều lượt thử. Hãy thử lại sau.", headers={"Retry-After": delay})

    def expire(self):
        with self.db.transaction() as connection:
            self.accounts.delete_expired(connection)
        return False
