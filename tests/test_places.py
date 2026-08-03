"""Turning a Places response into something an entry can be filed against.

The parsing is the part worth pinning. Everything else is an HTTP call, and the module already
treats a failed one as "no suggestions" rather than an error — a places outage must never stop
someone recording an expense.
"""

from __future__ import annotations

from money.api import places


def google(name: str | None, lat: float | None, lon: float | None, **extra: object) -> dict:
    """One entry shaped like the Places v1 response, with pieces optionally missing."""
    place: dict = {"id": extra.get("id", "abc"), "primaryType": "cafe"}
    if name is not None:
        place["displayName"] = {"text": name}
    if lat is not None and lon is not None:
        place["location"] = {"latitude": lat, "longitude": lon}
    if "address" in extra:
        place["formattedAddress"] = extra["address"]
    return place


class TestParsing:
    def test_it_keeps_the_venues_own_position(self) -> None:
        """The whole reason coordinates were added: a venue is not where the phone is.

        Picking "the café across the road" used to record the pavement outside, because the
        only coordinates in play were the device's.
        """
        parsed = places._parse([google("קפה גרג", 32.0709, 34.7803, address="דיזנגוף 100")])

        assert len(parsed) == 1
        assert (parsed[0].lat, parsed[0].lon) == (32.0709, 34.7803)
        assert parsed[0].name == "קפה גרג"
        assert parsed[0].address == "דיזנגוף 100"

    def test_a_place_with_no_position_is_dropped(self) -> None:
        """Defaulting to 0,0 would drop a pin in the Gulf of Guinea and call it a café."""
        assert places._parse([google("Somewhere", None, None)]) == []

    def test_a_place_with_no_name_is_dropped(self) -> None:
        assert places._parse([google(None, 32.07, 34.78)]) == []

    def test_an_address_is_optional(self) -> None:
        parsed = places._parse([google("Landwer", 32.07, 34.78)])
        assert parsed[0].address is None

    def test_it_survives_a_response_shape_it_did_not_expect(self) -> None:
        """Places is an external API: an empty object must be skipped, not raise."""
        assert places._parse([{}, {"displayName": {}}, {"location": {}}]) == []


class TestNoKey:
    """A deployment without GOOGLE_CLOUD_API_KEY still records entries, just without names."""

    def test_nearby_returns_nothing(self) -> None:
        assert places.nearby("", 32.07, 34.78) == []

    def test_search_returns_nothing(self) -> None:
        assert places.search("", "cafe", 32.07, 34.78) == []

    def test_a_blank_query_is_not_sent(self) -> None:
        """Guarding here rather than at the route: an empty text search bills for nothing."""
        assert places.search("a-key", "   ", 32.07, 34.78) == []
