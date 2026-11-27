"""Read a bounded snapshot from one iCloud inbox without changing message flags.

Privacy invariant: mailbox commands are LOGIN, SELECT(readonly), UID SEARCH,
UID FETCH using bounded BODY.PEEK[] partial requests, and LOGOUT only. No STORE, EXPUNGE, or SMTP.
"""
from __future__ import annotations

import email
from email import policy
from datetime import date, datetime
from html.parser import HTMLParser
import imaplib
import re
import ssl
import time
from typing import Callable
from zoneinfo import ZoneInfo

MAIL_HOST = "imap.mail.me.com"
MAIL_PORT = 993
MAX_EMAIL_BYTES = 262_144
MAX_SCAN = 200
MAX_PREVIEW = 700
MAX_READ_SECONDS = 20.0
MAX_IO_SECONDS = 15.0
CLEANUP_SECONDS = 0.5

_DATE = re.compile(rb'INTERNALDATE\s+"((?: \d|\d{1,2})-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2} [+-]\d{4})"', re.I)
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


def _normalized_text(value: str) -> str:
    # Never return terminal control characters, even in untrusted headers.
    return re.sub(r"\s+", " ", "".join(c for c in str(value) if c.isprintable() or c in "\t\n ")).strip()


def _flat(value: str, limit: int) -> str:
    return _normalized_text(value)[:limit]

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


def _text_preview(message: email.message.EmailMessage) -> tuple[str, str, str | None]:
    """Return bounded text, selected-representation coverage and source.

    Complete means the selected normalized text fits, not that other MIME
    representations, attachments, or the semantic meaning were assessed.
    """
    html_text = None
    empty_source = None
    decoding_failed = False

    def covered(text: str, source: str) -> tuple[str, str, str]:
        status = "truncated" if len(text) > MAX_PREVIEW else "complete"
        return text[:MAX_PREVIEW], status, source

    for part in _body_parts(message):
        content_type = part.get_content_type()
        if content_type not in ("text/plain", "text/html"):
            continue
        source = "plain" if content_type == "text/plain" else "html"
        try:
            # The default content manager replaces invalid bytes silently.
            # Reject an undecodable representation rather than assert coverage.
            content = part.get_content(errors="strict")
            if not isinstance(content, str) or part.defects:
                decoding_failed = True
                continue
            if source == "html":
                parser = _VisibleHTML()
                parser.feed(content)
                parser.close()
                content = "".join(parser.parts)
            normalized = _normalized_text(content)
        except (LookupError, UnicodeError, ValueError):
            decoding_failed = True
            continue
        if not normalized:
            if empty_source is None or source == "plain":
                empty_source = source
            continue
        if source == "plain":
            return covered(normalized, source)
        if html_text is None:
            html_text = normalized

    if html_text is not None:
        return covered(html_text, "html")
    if empty_source is not None and not decoding_failed:
        return "", "empty", empty_source
    return "", "unavailable", None

def parse_mail(raw: bytes, *, received_at: datetime) -> dict[str, object]:
    """Parse only a safe, bounded preview; no attachments or active HTML."""
    message = email.message_from_bytes(raw, policy=policy.default)
    sender = _flat(str(message.get("From", "Unknown sender")), 160)
    subject = _flat(str(message.get("Subject", "(no subject)")), 200)
    preview, preview_status, preview_source = _text_preview(message)
    risk = bool(_RISK.search(" ".join((subject, preview))))
    return {
        "sender": sender,
        "subject": subject,
        "preview": preview,
        "preview_status": preview_status,
        "preview_source": preview_source,
        "received_at": received_at.isoformat(timespec="seconds"),
        "potential_risk": risk,
        "untrusted": True,
    }


# imaplib returns FETCH metadata as bytes, or a (header, literal)
# tuple followed by the remainder of that same response. Recognize only
# the attributes this read-only client uses, plus ordinary FLAGS.
# In particular, UID inside FLAGS or a message literal is not a UID item.
_MAX_FETCH_METADATA = 8192
_FETCH_FRAME = re.compile(rb'[1-9][0-9]{0,9} \((.*)\)', re.I)
_FETCH_FIELD = re.compile(
    rb'(?:(?P<uid>UID [1-9][0-9]{0,9})'
    rb'|(?P<date>INTERNALDATE "[^"\r\n]{1,40}")'
    rb'|(?P<size>RFC822\.SIZE [0-9]{1,10})'
    rb'|(?P<body>BODY\[\]<0> \{[0-9]{1,10}\})'
    rb'|(?P<flags>FLAGS \([^()\r\n]*\)))',
    re.I,
)


def _fetch_fields(frame: bytes) -> dict[str, bytes] | None:
    if len(frame) > _MAX_FETCH_METADATA:
        return None
    envelope = _FETCH_FRAME.fullmatch(frame)
    if envelope is None:
        return None
    payload = envelope.group(1)
    fields: dict[str, bytes] = {}
    cursor = 0
    while cursor < len(payload):
        field = _FETCH_FIELD.match(payload, cursor)
        if field is None or field.lastgroup is None or field.lastgroup in fields:
            return None
        fields[field.lastgroup] = field.group()
        cursor = field.end()
        if cursor < len(payload):
            if payload[cursor:cursor + 1] != b" ":
                return None
            cursor += 1
            if cursor == len(payload):
                return None
    return fields


def _fetch_frames(items: object):
    if not isinstance(items, (tuple, list)):
        return
    index = 0
    while index < len(items):
        part = items[index]
        index += 1
        data = None
        if isinstance(part, bytes):
            frame = part
        elif (isinstance(part, tuple) and len(part) == 2 and
              all(isinstance(value, bytes) for value in part)):
            # UID can follow the literal. Do not concatenate a separate
            # untagged FETCH response or scan the untrusted body as metadata.
            if index >= len(items) or not isinstance(items[index], bytes):
                continue
            trailer = items[index]
            if trailer != b")" and not trailer.startswith(b" "):
                continue
            index += 1
            if len(part[0]) + len(trailer) > _MAX_FETCH_METADATA:
                continue
            frame, data = part[0] + trailer, part[1]
        else:
            continue
        fields = _fetch_fields(frame)
        if fields is not None:
            yield fields, data


def _has_uid(fields: dict[str, bytes], uid: str) -> bool:
    value = fields.get("uid")
    return value is not None and int(value.split()[1]) == int(uid)


def _matching_metadata(items: object, uid: str) -> bytes | None:
    matches = [
        fields["date"] + b" " + fields.get("size", b"")
        for fields, data in _fetch_frames(items)
        if data is None and "body" not in fields and
        _has_uid(fields, uid) and "date" in fields
    ]
    # Never assemble a date and size from different FETCH responses.
    return matches[0] if len(matches) == 1 else None


def _matching_body(items: object, uid: str) -> bytes | None:
    matches = []
    for fields, data in _fetch_frames(items):
        if data is None or not _has_uid(fields, uid) or "body" not in fields:
            continue
        declared = int(fields["body"].split(b"{", 1)[1][:-1])
        if declared != len(data):
            return None
        matches.append(data)
    return matches[0] if len(matches) == 1 else None


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


class _ReadDeadline(Exception):
    """No further foreground commands may start."""


def _close_connection(box: object) -> None:
    # Do not issue another protocol command on an expired or uncertain stream.
    close = getattr(box, "shutdown", None)
    if callable(close):
        try:
            close()
        except (OSError, imaplib.IMAP4.error, ValueError, AttributeError):
            pass


class ICloudMailbox:
    def __init__(self, username: str, password: str, *,
                 connect: Callable[[], object] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.username = username
        self._password = password
        self._clock = clock
        self._connect = connect or (lambda: imaplib.IMAP4_SSL(
            MAIL_HOST, MAIL_PORT, ssl_context=ssl.create_default_context(), timeout=MAX_IO_SECONDS
        ))

    def read_day(self, day: str, timezone_name: str = "America/New_York", limit: int = 20) -> dict[str, object]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= 30):
            raise ValueError("limit must be between 1 and 30")
        requested = date.fromisoformat(day)
        tz = ZoneInfo(timezone_name)
        box = None
        messages: list[dict[str, object]] = []
        too_large = 0
        incomplete = False
        abort_stream = False
        deadline = self._clock() + MAX_READ_SECONDS

        def remaining() -> float:
            left = deadline - self._clock()
            if left <= 0:
                raise _ReadDeadline()
            return left

        def command(fn, *args, **kwargs):
            # The socket timeout bounds idle I/O, not total elapsed time if
            # a server keeps trickling bytes. The monotonic deadline governs
            # whether any additional command may start.
            left = remaining()
            sock = getattr(box, "sock", None)
            if sock is not None:
                sock.settimeout(min(MAX_IO_SECONDS, left))
            return fn(*args, **kwargs)

        def snapshot(*, expired=False, timed_out=False):
            return {
                "day": requested.isoformat(),
                "timezone": timezone_name,
                "messages": messages,
                "returned": len(messages),
                "oversized_skipped": too_large,
                "incomplete": incomplete or too_large > 0 or expired or timed_out,
                "deadline_exceeded": expired,
                "read_timed_out": timed_out,
                "read_only": True,
            }

        try:
            remaining()
            box = self._connect()
            status, _ = command(box.login, self.username, self._password)
            if status != "OK":
                raise ValueError("Login rejected")
            status, _ = command(box.select, "INBOX", readonly=True)
            if status != "OK":
                raise ValueError("Inbox selection rejected")
            # IMAP searches the server calendar date. Opposite UTC offsets can put
            # that date two days either side of the user's day. BEFORE is exclusive.
            ordinal = requested.toordinal()
            since = date.fromordinal(max(1, ordinal - 2)).strftime("%d-%b-%Y")
            criteria = ["SINCE", since]
            if ordinal + 3 <= date.max.toordinal():
                before = date.fromordinal(ordinal + 3).strftime("%d-%b-%Y")
                criteria.extend(["BEFORE", before])
            status, rows = command(box.uid, "SEARCH", None, *criteria)
            if status != "OK" or not rows:
                raise ValueError("Inbox search rejected")
            ids = rows[0].decode("ascii").split()
            if any(not x.isdecimal() or int(x) < 1 for x in ids):
                raise ValueError("Invalid UID from server")
            selected = list(reversed(ids[-MAX_SCAN:]))
            incomplete = len(ids) > MAX_SCAN
            for scanned, uid in enumerate(selected, start=1):
                status, response = command(box.uid, "FETCH", uid, "(INTERNALDATE RFC822.SIZE)")
                if status != "OK":
                    incomplete = True
                    continue
                meta = _matching_metadata(response, uid)
                if meta is None:
                    incomplete = True
                    continue
                try:
                    received = parse_internal_date(meta).astimezone(tz)
                    if received.date() != requested:
                        continue
                    size = _size(meta)
                except ValueError:
                    incomplete = True
                    continue
                if size > MAX_EMAIL_BYTES:
                    too_large += 1
                    continue
                if size <= 0:
                    incomplete = True
                    continue
                # RFC 3501/9051 partial BODY.PEEK is read-only and limits the
                # requested octets on a compliant server. One sentinel byte
                # detects a body above the quota even if size was underreported.
                status, raw_response = command(box.uid, "FETCH", uid, f"(BODY.PEEK[]<0.{MAX_EMAIL_BYTES + 1}>)")
                if status != "OK":
                    incomplete = True
                    continue
                data = _matching_body(raw_response, uid)
                if data is None:
                    incomplete = True
                    continue
                if len(data) > MAX_EMAIL_BYTES:
                    too_large += 1
                    continue
                # A partial/mismatched response cannot establish a complete
                # message. Do not summarize it as if all its MIME bytes arrived.
                if len(data) != size:
                    incomplete = True
                    continue
                messages.append(parse_mail(data, received_at=received))
                if len(messages) >= limit:
                    incomplete = incomplete or scanned < len(selected)
                    break
            return snapshot()
        except _ReadDeadline:
            abort_stream = True
            return snapshot(expired=True)
        except TimeoutError:
            abort_stream = True
            return snapshot(expired=self._clock() >= deadline, timed_out=True)
        except (imaplib.IMAP4.error, OSError, ValueError, AttributeError, TypeError):
            # Do not leak provider errors, which can include account or mailbox details.
            raise RuntimeError("Unable to read iCloud Mail; check account consent, app-specific credentials, and connection") from None
        finally:
            if box is not None:
                left = deadline - self._clock()
                if abort_stream or left <= 0:
                    _close_connection(box)
                else:
                    try:
                        sock = getattr(box, "sock", None)
                        if sock is not None:
                            sock.settimeout(min(CLEANUP_SECONDS, left))
                        box.logout()
                    except (OSError, imaplib.IMAP4.error, ValueError, AttributeError):
                        _close_connection(box)
