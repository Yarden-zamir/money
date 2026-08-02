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


class LineItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    amount: Decimal
    quantity: Decimal | None = None
    shares: list[ShareInput] | None = None


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
    items: list[LineItemInput] | None = Field(
        default=None, description="Receipt lines; must sum to the entry amount"
    )


class EntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal | None = None
    payee: str | None = None
    date: DateType | None = None
    paid_by: dict[str, Decimal] | None = None
    shares: list[ShareInput] | None = None
    items: list[LineItemInput] | None = None
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


class AutoAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: str = Field(
        pattern=r"^(underfunded|assigned_last_month|spent_last_month)$",
        description="How much to put in each bucket",
    )
    buckets: list[str] | None = Field(
        default=None, description="Limit to these buckets; all of them when omitted"
    )


class MoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Bucket the money leaves")
    target: str = Field(description="Bucket the money goes to")
    amount: Decimal = Field(gt=0)


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


class DueEntry(BaseModel):
    scheduled_id: str
    name: str
    payee: str
    amount: Decimal
    currency: str
    kind: EntryKind
    date: DateType
    overdue: bool = Field(description="Its date has already passed")


class DueList(BaseModel):
    due: list[DueEntry]
    through: DateType = Field(description="How far ahead this list looked")


class PostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: DateType | None = Field(default=None, description="Defaults to today")


class PayeeSuggestion(BaseModel):
    payee: str
    count: int = Field(description="How many times this payee appears")
    last_used: DateType
    amount: Decimal | None = Field(description="Typical amount: the mode, else the most recent")
    bucket: str | None = Field(description="Bucket most often used for this payee")
    basis: str = Field(description="Which rule produced the suggestion, for the explanation")


class HistoryEvent(BaseModel):
    sha: str
    subject: str
    kind: str = Field(description="entry, assignment, bucket, rules, members, note, undo")
    author: str
    actor: str | None
    date: str
    entry_id: str | None
    mine: bool = Field(description="You made this change")


class HistoryPage(BaseModel):
    events: list[HistoryEvent]
    undoable: str | None = Field(description="Sha of your most recent change, if any")


class UndoResult(BaseModel):
    undone_sha: str
    undone_subject: str = Field(description="What was reverted, for the confirmation")
    commit: str
    can_redo: bool


class NearbyPlaceResponse(BaseModel):
    id: str
    name: str
    kind: str | None


class SuggestionResponse(BaseModel):
    payee: str | None
    amount: Decimal | None
    bucket: str | None
    shares: list[ShareInput]
    items: list[LineItemInput]
    place_name: str | None
    confidence: float
    basis: str = Field(description="payee, place, time or none")
    reason: str = Field(description="Why this was suggested; shown on hover")
    sample_size: int


class RepoOption(BaseModel):
    full_name: str
    private: bool
    description: str | None
    is_budget: bool = Field(description="Has a budget.yaml, so it is ready to connect")
    connected: bool = Field(description="Already connected as a budget here")


class UserOption(BaseModel):
    login: str
    name: str | None
    avatar_url: str | None


class CollaboratorResponse(BaseModel):
    login: str
    name: str | None
    avatar_url: str | None
    permission: str
    invited: bool = Field(description="Invitation sent but not yet accepted")
    is_member: bool = Field(description="Already listed in the budget's members")


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=1, max_length=64, description="GitHub login")
    name: str | None = Field(default=None, description="Display name; defaults to the login")
    person: str | None = Field(default=None, description="Person id; derived from the login")


class InviteResponse(BaseModel):
    login: str
    invited: bool = Field(description="False when they already had repo access")
    person: str


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
