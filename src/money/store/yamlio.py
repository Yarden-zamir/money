"""YAML that round-trips money exactly.

PyYAML parses `-50.00` into a float, which would defeat the whole point of using Decimal.
Both directions are overridden here so an amount survives a read/write cycle unchanged and
still reads as a plain number in the file — quoting every amount would make the ledger
noticeably uglier to edit by hand, and the repo is meant to be edited by hand.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

import yaml

FLOAT_TAG = "tag:yaml.org,2002:float"


class Loader(yaml.SafeLoader):
    pass


def _decimal_from_scalar(loader: yaml.Loader, node: yaml.Node) -> Decimal:
    # node.value is the original text, so no float ever exists in between.
    return Decimal(node.value)


Loader.add_constructor(FLOAT_TAG, _decimal_from_scalar)


class Dumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        # Indent list items under their key. Without this PyYAML writes lists flush with the
        # parent, which reads badly in a ledger reviewed as a diff.
        super().increase_indent(flow=flow, indentless=False)


def _represent_decimal(dumper: yaml.Dumper, value: Decimal) -> yaml.Node:
    # `f` formatting, not `.2f`: every Decimal here is already quantized to the places it
    # means — two for an amount, four for an exchange rate — and forcing two rounded a
    # rate of 3.4991 to 3.50 on the way into the ledger.
    return dumper.represent_scalar(FLOAT_TAG, f"{value:f}")


def _represent_str_enum(dumper: yaml.Dumper, value: StrEnum) -> yaml.Node:
    # Models dump with mode="python" so Decimals stay Decimal; that leaves enums as enums.
    return dumper.represent_str(str(value))


Dumper.add_representer(Decimal, _represent_decimal)
Dumper.add_multi_representer(StrEnum, _represent_str_enum)


def load(text: str | None) -> Any:
    if text is None or not text.strip():
        return None
    return yaml.load(text, Loader=Loader)


def dump(data: Any) -> str:
    """Serialize with stable key order and Hebrew left as-is.

    `sort_keys=False` keeps the field order the models declare, so a diff shows what changed
    rather than a reshuffle. `allow_unicode=True` keeps Hebrew payees readable instead of
    escaping them to `\\u05e9…`.
    """
    return yaml.dump(
        data,
        Dumper=Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )
