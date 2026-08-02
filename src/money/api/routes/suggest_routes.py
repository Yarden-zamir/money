"""Guessed entries and nearby places.

Both exist to remove typing, never to record anything on their own — a suggestion is a
pre-filled form the person still has to accept.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from money.api import places
from money.api.config import Settings
from money.api.deps import BudgetContext, CurrentUser, budget_context, current_user, get_settings
from money.api.schemas import (
    LineItemInput,
    NearbyPlaceResponse,
    ShareInput,
    SuggestionResponse,
)
from money.domain.suggest import suggest

router = APIRouter(tags=["suggestions"])


@router.get(
    "/places/nearby",
    operation_id="nearbyPlaces",
    response_model=list[NearbyPlaceResponse],
    summary="Venues around a point",
)
def nearby_places(
    _: Annotated[CurrentUser, Depends(current_user)],
    config: Annotated[Settings, Depends(get_settings)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> list[NearbyPlaceResponse]:
    """Names the shop someone is standing in, so the first visit does not need typing.

    Proxied rather than called from the browser, so the API key stays on the server. Returns
    an empty list rather than an error when the lookup fails — a places outage should not
    stop anyone recording an expense.
    """
    found = places.nearby(config.google_cloud_api_key, lat, lon)
    return [NearbyPlaceResponse(id=p.id, name=p.name, kind=p.kind) for p in found]


@router.get(
    "/budgets/{budget}/suggest",
    operation_id="suggestEntry",
    response_model=SuggestionResponse,
    summary="A guessed entry, with its reasoning",
    openapi_extra={"x-cli": {"command": "entry suggest"}},
)
def suggest_entry(
    context: Annotated[BudgetContext, Depends(budget_context)],
    payee: str | None = None,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    at: str | None = None,
) -> SuggestionResponse:
    """What this person probably about to record, drawn only from this budget's own history.

    Every field the caller already knows narrows the pool the rest is drawn from, so filling
    in the payee improves the amount and the split rather than being ignored.
    """
    when = datetime.fromisoformat(at) if at else datetime.now()
    result = suggest(entries=context.store.all_entries(), payee=payee, lat=lat, lon=lon, at=when)

    return SuggestionResponse(
        payee=result.payee,
        amount=result.amount,
        bucket=result.bucket,
        shares=[
            ShareInput(person=s.person, amount=s.amount, bucket=s.bucket) for s in result.shares
        ],
        items=[
            LineItemInput(
                label=item.label,
                amount=item.amount,
                quantity=item.quantity,
                shares=[
                    ShareInput(person=s.person, amount=s.amount, bucket=s.bucket)
                    for s in item.shares
                ]
                or None,
            )
            for item in result.items
        ],
        place_name=result.place_name,
        confidence=result.confidence,
        basis=result.basis,
        reason=result.reason,
        sample_size=result.sample_size,
    )
