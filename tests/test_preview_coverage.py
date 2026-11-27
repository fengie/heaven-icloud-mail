"""Synthetic MIME coverage cases; no real mailbox or account data."""
from datetime import datetime, timezone
from email.message import EmailMessage

import pytest

from heaven_icloud_mail.mail import MAX_PREVIEW, parse_mail
from heaven_icloud_mail.summary import prepare_summary_context


def parse(message):
    return parse_mail(message.as_bytes(), received_at=datetime(2026, 11, 27, tzinfo=timezone.utc))


@pytest.mark.parametrize("length", [699, 700, 701])
def test_normalized_unicode_preview_reports_exact_boundary(length):
    message = EmailMessage()
    message.set_content("字" * length)
    result = parse(message)
    assert len(result["preview"]) == min(length, MAX_PREVIEW)
    assert result["preview_source"] == "plain"
    assert result["preview_status"] == ("truncated" if length > MAX_PREVIEW else "complete")


def test_empty_plain_alternative_falls_back_to_visible_html():
    message = EmailMessage()
    message.set_content(" \n\t ")
    message.add_alternative("<p>Action required</p><script>HIDDEN_SCRIPT</script>", subtype="html")
    result = parse(message)
    assert result["preview"] == "Action required"
    assert result["preview_source"] == "html"
    assert result["preview_status"] == "complete"
    assert "HIDDEN_SCRIPT" not in str(result)


def test_nonempty_plain_is_preferred_over_html_and_attachments():
    message = EmailMessage()
    message.set_content("  Plain    evidence  ")
    message.add_alternative("<p>Alternative</p>", subtype="html")
    message.add_attachment(b"PRIVATE_ATTACHMENT", maintype="text", subtype="plain", filename="sample.txt")
    result = parse(message)
    assert result["preview"] == "Plain evidence"
    assert result["preview_source"] == "plain"
    assert result["preview_status"] == "complete"
    assert "PRIVATE_ATTACHMENT" not in str(result)


def test_empty_body_is_distinct_from_unsupported_charset():
    empty = EmailMessage()
    empty.set_content(" \n")
    result = parse(empty)
    assert result["preview"] == ""
    assert result["preview_status"] == "empty"
    assert result["preview_source"] == "plain"
    malformed = EmailMessage()
    malformed.set_type("text/plain")
    malformed.set_param("charset", "not-a-real-charset")
    malformed.set_payload("Unavailable body")
    result = parse(malformed)
    assert result["preview"] == ""
    assert result["preview_status"] == "unavailable"
    assert result["preview_source"] is None


def test_summary_preserves_message_coverage_even_when_list_is_complete():
    message = EmailMessage()
    message.set_content("x" * MAX_PREVIEW + " urgent payment")
    item = parse(message)
    result = prepare_summary_context({
        "day": "2026-11-27", "timezone": "UTC", "messages": [item],
        "incomplete": False,
    })
    assert result["incomplete"] is False
    assert result["messages"][0]["preview_status"] == "truncated"
    assert item["preview"] == "x" * MAX_PREVIEW
    assert "urgent payment" not in str(item)
    assert "preview_status" in result["instructions"]
    assert "不能据此断定" in result["instructions"]
    assert "potential_risk" in result["instructions"]
