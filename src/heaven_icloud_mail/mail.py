"""Read a bounded snapshot from one iCloud inbox without changing message flags.

Privacy invariant: mailbox commands are LOGIN, SELECT(readonly), UID SEARCH,
UID FETCH using BODY.PEEK[], and LOGOUT only. No STORE, EXPUNGE, or SMTP.
"""
from __future__ import annotations

import email
from email import policy
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import imaplib
import re
import ssl
from typing import Callable
from zoneinfo import ZoneInfo

MAIL_HOST = "imap.mail.me.com"
MAIL_PORT = 993
MAX_EMAIL_BYTES = 262_144
MAX_SCAN = 200
MAX_PREVIEW = 700

_DATE = re.compile(rb'INTERNALDATE\s+"(\d{1,2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2} [+-]\d{4})"', re.I)
_SIZE = re.compile(rb'RFC822\.SIZE\s+(\d+)', re.I)
_RISK = re.compile(r"(?i)(ignore (?:all |your |the )?previous instructions|send (?:your |me )?(?:password|credentials)|verify (?:your )?account|urgent.{0,30}(?:payment|transfer)|验证码|账户异常|立即转账|密码)")


class _VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "head", "iframe", "svg", "noscript"):
            self.skip.append(tag)
        elif tag in ("p", "br", "div", "li", "tr") and not self.skip:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self.skip and tag == self.skip[-1]:
            self.skip.pop()
        elif tag in ("p", "div", "li", "tr") and not self.skip:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def _flat(value: str, limit: int) -> str:
    # Never return terminal control characters, even when present in untrusted headers.
    return re.sub(r"\s+", " ", "".join(c for c in str(value) if c.isprintable() or c in "\t\n ")).strip()[:limit]


def _body_parts(message: email.message.EmailMessage):
    # walk() descends into attached messages and multipart attachments. Exclude
    # the complete subtree before examining any of its child text parts.
    if message.get_content_disposition() == "attachment":
        return
    if message.is_multipart():
        for part in message.iter_parts():
            yield from _body_parts(part)
    else:
        yield message


def _text_preview(message: email.message.EmailMessage) -> str:
    html_part = None
    for part in _body_parts(message):
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, ValueError):
            continue
        if not isinstance(content, str):
            continue
        if part.get_content_type() == "text/plain":
            return _flat(content, MAX_PREVIEW)
        if html_part is None:
            html_part = content
    if html_part is not None:
        parser = _VisibleHTML()
        parser.feed(html_part)
        parser.close()
        return _flat("".join(parser.parts), MAX_PREVIEW)
    return ""


def parse_mail(raw: bytes, *, received_at: datetime) -> dict[str, object]:
    """Parse only a safe, bounded preview; no attachments or active HTML."""
    message = email.message_from_bytes(raw, policy=policy.default)
    sender = _flat(str(message.get("From", "Unknown sender")), 160)
    subject = _flat(str(message.get("Subject", "(no subject)")), 200)
    preview = _text_preview(message)
    risk = bool(_RISK.search(" ".join((subject, preview))))
    return {
        "sender": sender,
        "subject": subject,
        "preview": preview,
        "received_at": received_at.isoformat(timespec="seconds"),
        "potential_risk": risk,
        "untrusted": True,
    }


def _response_bytes(items: object) -> bytes:
    if not isinstance(items, (tuple, list)):
        raise ValueError("Unrecognized IMAP response")
    return b" ".join(
        chunk if isinstance(chunk, bytes) else chunk[0]
        for chunk in items
        if isinstance(chunk, bytes) or (isinstance(chunk, tuple) and chunk and isinstance(chunk[0], bytes))
    )


def parse_internal_date(fetch_response: bytes) -> datetime:
    match = _DATE.search(fetch_response)
    if not match:
        raise ValueError("IMAP INTERNALDATE missing")
    return datetime.strptime(match.group(1).decode("ascii"), "%d-%b-%Y %H:%M:%S %z")


def _size(fetch_response: bytes) -> int:
    match = _SIZE.search(fetch_response)
    if not match:
        raise ValueError("IMAP message size missing")
    return int(match.group(1))


class ICloudMailbox:
    def __init__(self, username: str, password: str, *, connect: Callable[[], object] | None = None) -> None:
        self.username = username
        self._password = password
        self._connect = connect or (lambda: imaplib.IMAP4_SSL(
            MAIL_HOST, MAIL_PORT, ssl_context=ssl.create_default_context(), timeout=15
        ))

    def read_day(self, day: str, timezone_name: str = "America/New_York", limit: int = 20) -> dict[str, object]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= 30):
            raise ValueError("limit must be between 1 and 30")
        requested = date.fromisoformat(day)
        tz = ZoneInfo(timezone_name)
        box = None
        try:
            box = self._connect()
            status, _ = box.login(self.username, self._password)
            if status != "OK":
                raise ValueError("Login rejected")
            status, _ = box.select("INBOX", readonly=True)
            if status != "OK":
                raise ValueError("Inbox selection rejected")
            # Search starts two calendar days early to account for server/user TZ offsets.
            # Membership is determined by trusted IMAP INTERNALDATE, not the spoofable Date header.
            since = (requested - timedelta(days=2)).strftime("%d-%b-%Y")
            status, rows = box.uid("SEARCH", None, "SINCE", since)
            if status != "OK" or not rows:
                raise ValueError("Inbox search rejected")
            ids = rows[0].decode("ascii").split()
            if any(not x.isdecimal() or int(x) < 1 for x in ids):
                raise ValueError("Invalid UID from server")
            selected = list(reversed(ids[-MAX_SCAN:]))
            messages: list[dict[str, object]] = []
            too_large = 0
            for uid in selected:
                status, response = box.uid("FETCH", uid, "(INTERNALDATE RFC822.SIZE)")
                if status != "OK":
                    continue
                meta = _response_bytes(response)
                try:
                    received = parse_internal_date(meta).astimezone(tz)
                    size = _size(meta)
                except ValueError:
                    continue
                if received.date() != requested:
                    continue
                if size > MAX_EMAIL_BYTES:
                    too_large += 1
                    continue
                status, raw_response = box.uid("FETCH", uid, "(BODY.PEEK[])")
                if status != "OK":
                    continue
                data = next((item[1] for item in raw_response if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bytes)), None)
                if data is None or len(data) > MAX_EMAIL_BYTES:
                    continue
                messages.append(parse_mail(data, received_at=received))
                if len(messages) >= limit:
                    break
            return {
                "day": requested.isoformat(),
                "timezone": timezone_name,
                "messages": messages,
                "returned": len(messages),
                "oversized_skipped": too_large,
                "incomplete": len(ids) > MAX_SCAN or len(messages) >= limit,
                "read_only": True,
            }
        except (imaplib.IMAP4.error, OSError, ValueError, AttributeError, TypeError) as exc:
            # Do not leak provider errors, which can include account or mailbox details.
            raise RuntimeError("Unable to read iCloud Mail; check account consent, app-specific credentials, and connection") from None
        finally:
            if box is not None:
                try:
                    box.logout()
                except (OSError, imaplib.IMAP4.error):
                    pass
