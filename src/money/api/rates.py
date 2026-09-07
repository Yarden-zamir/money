"""Exchange rates from the European Central Bank.

The ECB publishes daily reference rates against the euro, with no key and no terms that
matter for a household. Any pair is a cross through the euro: shekels per dollar is
(shekels per euro) / (dollars per euro).

Behind one function returning `Decimal | None`, so a failed fetch degrades to "type the
rate, or keep it unconverted" — never to a guess, and never to a blocked save. Swap the
provider by replacing this module; nothing else knows where a rate came from.

Two feeds, because the ECB splits them: the last ninety days in a small file, and the whole
history in a large one. A conversion is almost always for a recent day, so the small file is
tried first and the large one only when the day is older than it covers.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree

import httpx

from money.domain.models import parse_rate

logger = logging.getLogger(__name__)

RECENT = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
HISTORY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
NAMESPACE = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"

# How many calendar days the small feed reaches back. Chosen under the ECB's own ninety so a
# weekend at the edge does not fall through to the large file.
RECENT_DAYS = 85


def fetch_rate(currency: str, base: str, day: date) -> Decimal | None:
    """Units of `base` per one unit of `currency`, on `day` or the last day the ECB published
    before it — a weekend purchase takes Friday's rate, which is what the card does too.

    None when the ECB does not quote one of the two currencies, or the network failed.
    """
    if currency == base:
        return Decimal("1.0000")
    try:
        url = RECENT if (date.today() - day).days <= RECENT_DAYS else HISTORY
        response = httpx.get(url, timeout=10, follow_redirects=True)
        response.raise_for_status()
        return rate_from_feed(response.text, currency, base, day)
    except (httpx.HTTPError, ElementTree.ParseError) as exc:
        logger.warning("rate lookup for %s/%s on %s failed: %s", currency, base, day, exc)
        return None


def rate_from_feed(xml: str, currency: str, base: str, day: date) -> Decimal | None:
    """The cross rate for `day` from an ECB feed, or the nearest earlier day it holds.

    Pure, so it is testable against a saved feed without the network.
    """
    per_euro: dict[date, dict[str, Decimal]] = {}
    root = ElementTree.fromstring(xml)
    for cube in root.iter(f"{NAMESPACE}Cube"):
        when = cube.get("time")
        if when is None:
            continue
        quoted = {
            rate.get("currency", ""): Decimal(rate.get("rate", "0"))
            for rate in cube.findall(f"{NAMESPACE}Cube")
            if rate.get("currency")
        }
        quoted["EUR"] = Decimal("1")
        per_euro[date.fromisoformat(when)] = quoted

    candidates = sorted(when for when in per_euro if when <= day)
    if not candidates:
        return None
    quotes = per_euro[candidates[-1]]
    if currency not in quotes or base not in quotes or quotes[currency] == 0:
        return None
    return parse_rate(quotes[base] / quotes[currency])
