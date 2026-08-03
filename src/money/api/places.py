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
SEARCH_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

# Places bills per field group, so this asks for exactly what a picker needs: what it is
# called, where it is, and enough of an address to tell two branches apart.
FIELD_MASK = (
    "places.id,places.displayName,places.primaryType,places.location,places.formattedAddress"
)

# Wide enough to catch the shop you are standing in when GPS is a little off indoors, narrow
# enough that a high street does not return every café on it.
SEARCH_RADIUS_METRES = 150.0


@dataclass(frozen=True)
class NearbyPlace:
    id: str
    name: str
    kind: str | None
    # Where the venue is, which is not where the phone is. Picking "the café across the road"
    # should record the café, and without this the entry recorded the pavement outside.
    lat: float
    lon: float
    address: str | None = None


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
                "X-Goog-FieldMask": FIELD_MASK,
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

    return _parse(response.json().get("places", []))


def search(api_key: str, query: str, lat: float | None, lon: float | None) -> list[NearbyPlace]:
    """Find a venue by name.

    Nearby answers "what am I standing in", which is the common case but not the only one:
    recording yesterday's lunch, or a shop you have left, needs naming a place you are not at.
    Coordinates are still passed when known so results near the person rank first — Places
    biases towards the circle rather than restricting to it, so somewhere across town is still
    findable.
    """
    if not api_key or not query.strip():
        return []

    body: dict = {"textQuery": query.strip(), "maxResultCount": 8}
    if lat is not None and lon is not None:
        body["locationBias"] = {
            "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": 20_000.0}
        }

    try:
        response = httpx.post(
            SEARCH_ENDPOINT,
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": FIELD_MASK,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=8.0,
        )
    except httpx.RequestError as exc:
        logger.warning("places search failed: %s", exc)
        return []

    if response.status_code != 200:
        logger.warning("places search returned %s: %s", response.status_code, response.text[:200])
        return []

    return _parse(response.json().get("places", []))


def _parse(found: list[dict]) -> list[NearbyPlace]:
    """Both endpoints answer with the same shape, so they share the parsing.

    A place with no name or no position is dropped rather than defaulted: an unnamed pin at
    0,0 in the Gulf of Guinea is worse than one fewer suggestion.
    """
    places_out: list[NearbyPlace] = []
    for place in found:
        name = (place.get("displayName") or {}).get("text", "")
        location = place.get("location") or {}
        lat, lon = location.get("latitude"), location.get("longitude")
        if not name or lat is None or lon is None:
            continue
        places_out.append(
            NearbyPlace(
                id=place.get("id", ""),
                name=name,
                kind=place.get("primaryType"),
                lat=float(lat),
                lon=float(lon),
                address=place.get("formattedAddress"),
            )
        )
    return places_out
