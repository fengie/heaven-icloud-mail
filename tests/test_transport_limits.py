"""Exercise the production transport boundary with synthetic data only."""
import imaplib
from email.message import EmailMessage

import pytest

from heaven_icloud_mail import mail
from heaven_icloud_mail.summary import prepare_summary_context


@pytest.fixture
def transport(monkeypatch):
    calls = []
    # No connection is made. Retain the production subclass and documented
    # imaplib.read override; replace only the underlying transport read.
    monkeypatch.setattr(imaplib.IMAP4_SSL, "__init__", lambda self, *args, **kwargs: None)
    def underlying(self, size):
        calls.append(size)
        return b""
    monkeypatch.setattr(imaplib.IMAP4_SSL, "read", underlying)
    return mail._BoundedIMAP4SSL(), calls


def test_declared_oversized_literal_is_rejected_before_any_underlying_read(transport):
    client, calls = transport
    with pytest.raises(mail._TransportReadLimit):
        client.read(mail.MAX_EMAIL_BYTES + 2)
    assert calls == []
    # The parser's stream is not safe to reuse after refusing a literal.
    with pytest.raises(mail._TransportReadLimit):
        client.read(1)
    assert calls == []


def test_exact_body_request_sentinel_is_allowed(transport):
    client, calls = transport
    client.read(mail.MAX_EMAIL_BYTES + 1)
    assert calls == [mail.MAX_EMAIL_BYTES + 1]


def test_aggregate_byte_limit_checks_declared_size_before_read(transport, monkeypatch):
    client, calls = transport
    monkeypatch.setattr(mail, "MAX_SESSION_LITERAL_BYTES", 5)
    client.read(3)
    client.read(2)
    with pytest.raises(mail._TransportReadLimit):
        client.read(1)
    assert calls == [3, 2]


def test_zero_length_literals_still_consume_count_quota(transport, monkeypatch):
    client, calls = transport
    monkeypatch.setattr(mail, "MAX_SESSION_LITERALS", 2)
    client.read(0)
    client.read(0)
    with pytest.raises(mail._TransportReadLimit):
        client.read(0)
    assert calls == [0, 0]


def test_default_mailbox_selects_bounded_tls_transport(monkeypatch):
    called = []
    def init(self, host, port, **kwargs):
        called.append((type(self), host, port, kwargs))
    monkeypatch.setattr(imaplib.IMAP4_SSL, "__init__", init)
    reader = mail.ICloudMailbox("user@example.test", "synthetic-only")
    connection = reader._connect()
    assert type(connection) is mail._BoundedIMAP4SSL
    assert called[0][1:3] == (mail.MAIL_HOST, mail.MAIL_PORT)
    assert called[0][3]["ssl_context"].check_hostname
    assert called[0][3]["timeout"] > 0


def test_limit_after_verified_message_preserves_partial_results_and_aborts_stream():
    message = EmailMessage()
    message["Subject"] = "Synthetic verified message"
    message.set_content("Synthetic text")
    raw = message.as_bytes()
    calls = []
    class Inbox:
        def login(self, *_): return "OK", [b"authenticated"]
        def select(self, name, readonly=False):
            assert name == "INBOX" and readonly
            return "OK", [b"2"]
        def uid(self, action, *args):
            calls.append((action, *args))
            if action == "SEARCH": return "OK", [b"1 2"]
            uid, query = args
            if "INTERNALDATE" in query:
                return "OK", [f'1 (UID {uid} INTERNALDATE "27-Nov-2026 12:00:00 +0000" RFC822.SIZE {len(raw)})'.encode()]
            assert "BODY.PEEK[]" in query
            if uid == "1": raise mail._TransportReadLimit("DO_NOT_LOG")
            return "OK", [(f"1 (UID 2 BODY[]<0> {{{len(raw)}}}".encode(), raw), b")"]
        def logout(self): calls.append(("logout",))
        def shutdown(self): calls.append(("shutdown",))
    result = mail.ICloudMailbox("user@example.test", "synthetic-only", connect=Inbox).read_day("2026-11-27", "UTC")
    assert result["returned"] == 1
    assert result["messages"][0]["subject"] == "Synthetic verified message"
    assert result["incomplete"] and result["transport_limited"]
    assert not result["read_timed_out"]
    assert calls[-1] == ("shutdown",)
    assert ("logout",) not in calls
    assert "DO_NOT_LOG" not in str(result)
    context = prepare_summary_context(result)
    assert context["transport_limited"] is True
    assert "transport_limited" in context["instructions"]
