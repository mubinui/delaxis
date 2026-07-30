"""Voice tickets are the only thing guarding the voice WebSocket.

FastAPI's JWT and rate-limiting middleware do not run on WebSocket connections,
so the socket accepts no credentials of its own — only a ticket minted by the
authenticated, rate-limited HTTP endpoint. Every property below is what stops
that socket from being a free, unthrottled handle on a billed realtime model.
"""

import time
from datetime import timedelta

import pytest

from src.api.auth import create_access_token
from src.api.voice import tickets


@pytest.fixture(autouse=True)
def clean_ticket_cache():
    tickets.reset()
    yield
    tickets.reset()


class TestMintAndRedeem:
    def test_round_trips_session_and_deployment(self):
        ticket, ttl = tickets.mint(session_id="abc-123", deployment="support-bot")
        assert ttl > 0
        assert tickets.redeem(ticket) == ("abc-123", "support-bot", tickets.PURPOSE_SESSION)

    def test_deployment_is_optional(self):
        ticket, _ = tickets.mint(session_id="abc-123", deployment=None)
        session_id, deployment, purpose = tickets.redeem(ticket)
        assert session_id == "abc-123"
        assert not deployment
        assert purpose == tickets.PURPOSE_SESSION


class TestBuilderPurpose:
    """A builder ticket is a design conversation with no workflow behind it.

    It legitimately carries no session, so the "must name a session" rule has to
    apply only to session-scoped tickets — while still refusing a *session*
    ticket that lacks one.
    """

    def test_round_trips_without_a_session(self):
        ticket, _ = tickets.mint(session_id="", deployment=None, purpose=tickets.PURPOSE_BUILDER)
        session_id, deployment, purpose = tickets.redeem(ticket)
        assert session_id == ""
        assert deployment is None
        assert purpose == tickets.PURPOSE_BUILDER

    def test_session_ticket_still_requires_a_session(self):
        ticket, _ = tickets.mint(session_id="", deployment=None, purpose=tickets.PURPOSE_SESSION)
        with pytest.raises(tickets.TicketError, match="no session"):
            tickets.redeem(ticket)

    def test_unknown_purpose_is_refused(self):
        token = create_access_token(
            {"typ": "voice", "pur": "something-else", "sid": "abc", "dep": "", "jti": "z"}
        )
        with pytest.raises(tickets.TicketError, match="unknown ticket purpose"):
            tickets.redeem(token)

    def test_a_purposeless_ticket_defaults_to_session(self):
        # Tickets minted before the purpose claim existed must keep working.
        token = create_access_token({"typ": "voice", "sid": "abc", "dep": "", "jti": "legacy"})
        assert tickets.redeem(token) == ("abc", None, tickets.PURPOSE_SESSION)

    def test_builder_tickets_are_still_single_use(self):
        ticket, _ = tickets.mint(session_id="", deployment=None, purpose=tickets.PURPOSE_BUILDER)
        tickets.redeem(ticket)
        with pytest.raises(tickets.TicketError, match="already used"):
            tickets.redeem(ticket)


class TestSingleUse:
    def test_second_redemption_is_refused(self):
        # Otherwise a ticket captured from the URL could open sessions forever.
        ticket, _ = tickets.mint(session_id="abc-123", deployment=None)
        tickets.redeem(ticket)
        with pytest.raises(tickets.TicketError, match="already used"):
            tickets.redeem(ticket)


class TestRejections:
    def test_empty_ticket(self):
        with pytest.raises(tickets.TicketError, match="missing ticket"):
            tickets.redeem("")

    def test_garbage_ticket(self):
        with pytest.raises(tickets.TicketError, match="invalid or expired"):
            tickets.redeem("not-a-jwt")

    def test_tampered_signature(self):
        ticket, _ = tickets.mint(session_id="abc-123", deployment=None)
        forged = ticket[:-4] + ("aaaa" if not ticket.endswith("aaaa") else "bbbb")
        with pytest.raises(tickets.TicketError):
            tickets.redeem(forged)

    def test_expired_ticket(self):
        expired = create_access_token(
            {"typ": "voice", "sid": "abc-123", "dep": "", "jti": "x"},
            expires_delta=timedelta(seconds=-5),
        )
        with pytest.raises(tickets.TicketError, match="invalid or expired"):
            tickets.redeem(expired)

    def test_ordinary_access_token_is_not_a_ticket(self):
        # Access tokens are long-lived and far easier to come by; they must not
        # be interchangeable with a voice ticket.
        token = create_access_token({"sub": "user-1", "username": "someone"})
        with pytest.raises(tickets.TicketError, match="not a voice ticket"):
            tickets.redeem(token)

    def test_ticket_without_session_is_refused(self):
        token = create_access_token({"typ": "voice", "dep": "", "jti": "y"})
        with pytest.raises(tickets.TicketError, match="no session"):
            tickets.redeem(token)

    def test_ticket_without_id_is_refused(self):
        token = create_access_token({"typ": "voice", "sid": "abc", "dep": ""})
        with pytest.raises(tickets.TicketError, match="no id"):
            tickets.redeem(token)


class TestTtl:
    def test_ttl_follows_settings(self, monkeypatch):
        from src.config.settings import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings.voice, "ticket_ttl_seconds", 45)
        _ticket, ttl = tickets.mint(session_id="abc", deployment=None)
        assert ttl == 45

    def test_ttl_has_a_floor(self, monkeypatch):
        # A zero or negative TTL would mint tickets that can never be redeemed.
        from src.config.settings import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings.voice, "ticket_ttl_seconds", 0)
        ticket, ttl = tickets.mint(session_id="abc", deployment=None)
        assert ttl >= 5
        assert tickets.redeem(ticket) == ("abc", None, tickets.PURPOSE_SESSION)
