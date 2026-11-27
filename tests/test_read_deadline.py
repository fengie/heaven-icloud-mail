"""Deterministic foreground deadline tests, without real network access."""
from email.message import EmailMessage

from heaven_icloud_mail.mail import ICloudMailbox, MAX_READ_SECONDS
from heaven_icloud_mail.summary import prepare_summary_context


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class Inbox:
    def __init__(self, clock, *, expire_at=None, timeout_at=None):
        self.clock = clock
        self.expire_at = expire_at
        self.timeout_at = timeout_at
        self.calls = []
        self.timeouts = []
        self.sock = self
        self.bodies = {}
        for uid in ("1", "2"):
            message = EmailMessage()
            message["Subject"] = f"Synthetic {uid}"
            message.set_content("Synthetic text")
            self.bodies[uid] = message.as_bytes()

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def step(self, name):
        self.calls.append(name)
        if name == self.expire_at:
            self.clock.now = MAX_READ_SECONDS + 1
        if name == self.timeout_at:
            raise TimeoutError("private provider diagnostic")

    def login(self, user, password):
        self.step("login")
        return "OK", [b"authenticated"]

    def select(self, box, readonly=False):
        assert box == "INBOX" and readonly
        self.step("select")
        return "OK", [b"2"]

    def uid(self, action, *args):
        if action == "SEARCH":
            self.step("search")
            return "OK", [b"1 2"]
        uid, query = args
        body = self.bodies[uid]
        if "INTERNALDATE" in query:
            self.step(f"meta-{uid}")
            return "OK", [f'1 (UID {uid} INTERNALDATE "27-Nov-2026 12:00:00 +0000" RFC822.SIZE {len(body)})'.encode()]
        assert "BODY.PEEK[]" in query
        self.step(f"body-{uid}")
        return "OK", [(f"1 (UID {uid} BODY[]<0> {{{len(body)}}}".encode(), body), b")"]

    def logout(self):
        self.step("logout")

    def shutdown(self):
        self.step("shutdown")


def read(inbox, clock):
    return ICloudMailbox("user@example.test", "synthetic-only", connect=lambda: inbox, clock=clock).read_day("2026-11-27", "UTC")


def test_deadline_retains_verified_results_and_starts_no_more_fetches():
    clock = Clock()
    inbox = Inbox(clock, expire_at="meta-1")
    result = read(inbox, clock)
    assert [m["subject"] for m in result["messages"]] == ["Synthetic 2"]
    assert result["incomplete"] and result["deadline_exceeded"]
    assert "body-1" not in inbox.calls
    assert inbox.calls[-1] == "shutdown"
    assert "logout" not in inbox.calls
    context = prepare_summary_context(result)
    assert context["deadline_exceeded"] is True
    assert context["incomplete"] is True


def test_deadline_after_search_does_not_start_metadata_fetch():
    clock = Clock()
    inbox = Inbox(clock, expire_at="search")
    result = read(inbox, clock)
    assert result["returned"] == 0
    assert result["incomplete"] and result["deadline_exceeded"]
    assert inbox.calls == ["login", "select", "search", "shutdown"]


def test_socket_timeout_preserves_partial_results_without_provider_details():
    clock = Clock()
    inbox = Inbox(clock, timeout_at="body-1")
    result = read(inbox, clock)
    assert result["returned"] == 1 and result["incomplete"]
    assert result["read_timed_out"] is True
    assert result["deadline_exceeded"] is False
    assert "private provider diagnostic" not in str(result)
    assert inbox.calls[-1] == "shutdown"


def test_normal_read_reports_complete_and_attempts_bounded_logout():
    clock = Clock()
    inbox = Inbox(clock)
    result = read(inbox, clock)
    assert result["returned"] == 2 and not result["incomplete"]
    assert not result["deadline_exceeded"] and not result["read_timed_out"]
    assert inbox.calls[-1] == "logout"
    assert all(0 < value <= 15 for value in inbox.timeouts)
    assert inbox.timeouts[-1] <= 1
