"""Naming the venue at a set of coordinates.

Proxied through the backend so the API key never reaches a browser, where it could be lifted
from the network tab and spent by anyone.

Only ever called with coordinates the person's own device supplied, and only when they are
adding an entry — there is no background tracking. What Google is told is "somebody is near
here", with no account attached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

ENDPOINT = "https://places.googleapis.com/v1/places:searchNearby"

# Wide enough to catch the shop you are standing in when GPS is a little off indoors, narrow
# enough that a high street does not return every café on it.
SEARCH_RADIUS_METRES = 150.0


@dataclass(frozen=True)
class NearbyPlace:
    id: str
    name: str
    kind: str | None


class PlacesError(RuntimeError):
    pass


def nearby(api_key: str, lat: float, lon: float, limit: int = 8) -> list[NearbyPlace]:
    """Venues around a point, closest first.

    The field mask is deliberately minimal — an id, a name and a type. Places bills per field
    group, and nothing here needs an address, a photo or opening hours.
    """
    if not api_key:
        return []

    try:
        response = httpx.post(
            ENDPOINT,
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "places.id,places.displayName,places.primaryType",
                "Content-Type": "application/json",
            },
            json={
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lon},
                        "radius": SEARCH_RADIUS_METRES,
                    }
                },
                "maxResultCount": limit,
                "rankPreference": "DISTANCE",
            },
            timeout=8.0,
        )
    except httpx.RequestError as exc:
        # A places outage must not stop someone logging an expense; they can type the name.
        logger.warning("places lookup failed: %s", exc)
        return []

    if response.status_code != 200:
        logger.warning("places lookup returned %s: %s", response.status_code, response.text[:200])
        return []

    found = response.json().get("places", [])
    return [
        NearbyPlace(
            id=place.get("id", ""),
            name=(place.get("displayName") or {}).get("text", ""),
            kind=place.get("primaryType"),
        )
        for place in found
        if (place.get("displayName") or {}).get("text")
    ]
