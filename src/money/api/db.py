"""App state: users, API keys, and which repo backs which budget.

This is the only relational storage in the system, and it deliberately holds no budget data.
Deleting `app.db` costs users a sign-in and their API keys; it costs them no money history.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

TOKEN_PREFIX = "money_pat_"


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(unique=True, index=True)
    login: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    avatar_url: Mapped[str | None] = mapped_column(String(500), default=None)

    # The user's GitHub OAuth token, encrypted at rest. Pushes to the data repo are made with
    # it, so GitHub itself decides whether a write is allowed. See specs/deployment.md.
    encrypted_token: Mapped[str] = mapped_column(String(1000))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))

    # Only the hash is stored, so a database leak yields no usable credential.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scopes: Mapped[str] = mapped_column(String(100), default="read,write")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    def is_valid(self) -> bool:
        return self.expires_at is None or self.expires_at > utcnow()


class BudgetLink(Base):
    """Maps a budget slug onto the GitHub repo that holds its data."""

    __tablename__ = "budget_links"
    __table_args__ = (UniqueConstraint("slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), index=True)
    repo: Mapped[str] = mapped_column(String(200))  # owner/repo
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def mint_token() -> tuple[str, str]:
    """Return (token to show the user once, hash to store)."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def make_sessionmaker(db_path: Path) -> sessionmaker:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
