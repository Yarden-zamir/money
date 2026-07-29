"""Default split rules."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from money.api.deps import BudgetContext, budget_context, writable
from money.domain.rules import Rule

router = APIRouter(prefix="/budgets/{budget}/rules", tags=["rules"])


@router.get(
    "",
    operation_id="listRules",
    response_model=list[Rule],
    summary="Default split rules, in match order",
    openapi_extra={"x-cli": {"command": "rule list"}},
)
def list_rules(context: Annotated[BudgetContext, Depends(budget_context)]) -> list[Rule]:
    return context.store.rules()


@router.put(
    "",
    operation_id="putRules",
    response_model=list[Rule],
    summary="Replace the whole rule list",
    openapi_extra={"x-cli": {"command": "rule set"}},
)
def put_rules(
    body: list[Rule],
    context: Annotated[BudgetContext, Depends(writable)],
) -> list[Rule]:
    """Replaces the list wholesale, because order is meaningful: first match wins.

    Editing one rule in place would leave the caller unable to express a reordering.
    """
    context.store.put_rules(body, context.actor)
    return body
