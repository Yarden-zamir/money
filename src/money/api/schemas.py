"""Request and response bodies.

Kept separate from the domain models because they are a public contract: the TypeScript
client and the CLI are both generated from them, so a field rename here is a breaking change
for two downstream artifacts.
"""

from __future__ import annotations

from datetime import date as DateType
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from money.domain.derive import Balance, BucketState, Settlement
from money.domain.models import Entry, EntryKind, Member, Month


class ShareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person: str
    amount: Decimal
    bucket: str | None = None


class EntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(description="Negative for money out, positive for money in")
    payee: str = Field(min_length=1, max_length=200)
    date: DateType | None = Field(default=None, description="Defaults to today")
    kind: EntryKind = EntryKind.EXPENSE
    currency: str | None = Field(default=None, description="Defaults to the budget currency")

    paid_by: dict[str, Decimal] | None = Field(
        default=None, description="Defaults to the whole amount from the calling user"
    )
    shares: list[ShareInput] | None = Field(
        default=None, description="Explicit split. When omitted, rules decide."
    )
    bucket: str | None = Field(
        default=None, description="Book every share against this bucket, overriding the rule"
    )
    note: str | None = None
    tags: list[str] = Field(default_factory=list)


class EntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal | None = None
    payee: str | None = None
    date: DateType | None = None
    paid_by: dict[str, Decimal] | None = None
    shares: list[ShareInput] | None = None
    note: str | None = None
    tags: list[str] | None = None


class CommitRef(BaseModel):
    sha: str
    subject: str
    author_name: str
    date: str


class EntryResponse(BaseModel):
    entry: Entry
    commit: str = Field(description="Sha of the commit that recorded this change")


class EntryList(BaseModel):
    entries: list[Entry]
    total: int


class HistoryList(BaseModel):
    commits: list[CommitRef]


class BalanceSheet(BaseModel):
    currency: str
    balances: list[Balance]
    settle_up: list[Settlement]


class MonthResponse(BaseModel):
    person: str
    month: Month
    currency: str
    ready_to_assign: Decimal
    income: Decimal
    assigned: Decimal
    buckets: list[BucketState]


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket: str
    amount: Decimal


class SettleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str = Field(description="Person id being paid")
    amount: Decimal = Field(gt=0)
    payer: str | None = Field(
        default=None,
        description="Person id who handed over the money. Defaults to the calling user.",
    )
    date: DateType | None = None
    note: str | None = None


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=20000, description="Markdown. Empty removes the note.")


class NoteResponse(BaseModel):
    entry_id: str
    text: str


class MonthClose(BaseModel):
    month: Month
    closed: bool
    commit: str | None = None


class BudgetSummary(BaseModel):
    slug: str
    name: str
    repo: str
    currency: str
    branch: str
    members: list[Member]
    me: str | None = Field(description="Which member the caller is, if any")
    can_write: bool


class BudgetConnect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,38}$")
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$", description="owner/repo on GitHub")


class SplitPreview(BaseModel):
    rule: str | None
    shares: list[ShareInput]


class UserResponse(BaseModel):
    login: str
    name: str
    email: str
    avatar_url: str | None


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    scopes: list[str]
    created_at: str
    expires_at: str | None
    last_used_at: str | None


class ApiKeyCreated(ApiKeyResponse):
    token: str = Field(description="Shown once. It cannot be retrieved again.")


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["read", "write"])
    expires_in_days: int | None = Field(default=None, gt=0, le=3650)
