"""Preview sign-in handoff.

A PR preview cannot run its own OAuth flow, so production completes it and hands the result
over as a ticket. That ticket carries a GitHub token, so these tests exist to pin down the
properties that keep it from being useful to anyone else.

See specs/api-and-auth.md.
"""

from __future__ import annotations

import time

import pytest

from money.api import auth
from money.api.config import Settings

SECRET = "test-session-secret"
KEY = "test-encryption-key"


def settings_for(environment: str) -> Settings:
    return Settings(
        kitshn_environment=environment,
        base_url="https://money.yarden-zamir.com",
        github_client_id="id",
        github_client_secret="secret",
        session_secret=SECRET,
        token_encryption_key=KEY,
    )


class TestHostValidation:
    @pytest.fixture
    def prod(self) -> Settings:
        return settings_for("prod")

    def test_a_real_preview_host_is_accepted(self, prod: Settings) -> None:
        assert prod.is_valid_preview_host("pr-42.money.yarden-zamir.com")

    @pytest.mark.parametrize(
        "host",
        [
            "evil.com",
            "money.yarden-zamir.com",  # production is not a preview of itself
            "pr-42.money.yarden-zamir.com.evil.com",  # suffix smuggling
            "pr.42.money.yarden-zamir.com",  # the old two-label form
            "pr-42.evil.com",
            "pr-notanumber.money.yarden-zamir.com",
            "pr-.money.yarden-zamir.com",
            "pr-٤٢.money.yarden-zamir.com",  # non-ASCII digits
            "pr-42.money.yarden-zamir.com@evil.com",
            "xpr-42.money.yarden-zamir.com",
            "",
        ],
    )
    def test_anything_else_is_refused(self, prod: Settings, host: str) -> None:
        """This value decides where a ticket is sent, so the check must not be generous."""
        assert not prod.is_valid_preview_host(host)

    def test_a_preview_knows_its_own_hostname(self) -> None:
        assert settings_for("pr-42").own_host == "pr-42.money.yarden-zamir.com"
        assert settings_for("prod").own_host == "money.yarden-zamir.com"


class TestTicket:
    def issue(self, host: str = "pr-42.money.yarden-zamir.com") -> str:
        return auth.issue_handoff(
            github_token="gho_realtoken", host=host, secret=SECRET, encryption_key=KEY
        )

    def read(self, ticket: str, host: str = "pr-42.money.yarden-zamir.com") -> str:
        return auth.read_handoff(ticket, expected_host=host, secret=SECRET, encryption_key=KEY)

    def test_a_valid_ticket_yields_the_token(self) -> None:
        assert self.read(self.issue()) == "gho_realtoken"

    def test_a_ticket_is_single_use(self) -> None:
        ticket = self.issue()
        self.read(ticket)
        with pytest.raises(auth.HandoffError, match="already been used"):
            self.read(ticket)

    def test_a_ticket_is_pinned_to_one_preview(self) -> None:
        """pr-43 must not be able to spend a ticket minted for pr-42."""
        ticket = self.issue(host="pr-42.money.yarden-zamir.com")
        with pytest.raises(auth.HandoffError, match="different host"):
            self.read(ticket, host="pr-43.money.yarden-zamir.com")

    def test_a_ticket_signed_with_another_key_is_refused(self) -> None:
        forged = auth.issue_handoff(
            github_token="gho_x",
            host="pr-42.money.yarden-zamir.com",
            secret="not-the-real-secret",
            encryption_key=KEY,
        )
        with pytest.raises(auth.HandoffError, match="not valid"):
            self.read(forged)

    def test_a_tampered_ticket_is_refused(self) -> None:
        ticket = self.issue()
        with pytest.raises(auth.HandoffError, match="not valid"):
            self.read(ticket[:-3] + "aaa")

    def test_an_expired_ticket_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ticket = self.issue()
        real_time = time.time
        monkeypatch.setattr(time, "time", lambda: real_time() + auth.HANDOFF_MAX_AGE + 5)
        with pytest.raises(auth.HandoffError, match="expired"):
            self.read(ticket)

    def test_the_token_is_not_readable_from_the_ticket(self) -> None:
        """The signature proves origin; encryption keeps the token out of browser history."""
        assert "gho_realtoken" not in self.issue()

    def test_the_window_stays_short(self) -> None:
        """The ticket travels in a URL, so its lifetime is the mitigation. Widen it and the
        trade documented in auth.py stops holding."""
        assert auth.HANDOFF_MAX_AGE <= 120
