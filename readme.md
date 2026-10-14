# Heaven iCloud Mail

**A read-only iCloud Mail connector for Chinese-language email summaries in ChatGPT.**

**Stage:** v0.1.0 source prototype; local MCP only. **Not connected to anyone's iCloud mailbox or ChatGPT account.** The ChatGPT Free/normal-chat integration and authenticated remote endpoint still need live testing. Source is currently in a **PUBLIC** GitHub repository: do not put personal data in it.

## What it does now

- Retrieves a bounded set of emails received on a particular day from one `@icloud.com` inbox with Apple's secure IMAP server (`imap.mail.me.com:993`), using an Apple **app-specific password** supplied at runtime.
- Restricts IMAP to readonly selection, UID SEARCH and UID FETCH with `BODY.PEEK[]`. Doesn't send, delete, edit, mark read, or download attachments to disk.
- Uses the IMAP `INTERNALDATE` rather than a possibly forged email Date header; respects the configured timezone.
- Returns only a short plain-text preview (up to 700 characters), sender, subject, time, and basic risk hints. The ChatGPT model, not this program, creates the Chinese-language summary.
- No background sync, no database, and no persistence of message contents.

## Setup for the account owner (only after she approves)

1. Keep using the iPhone **Mail** app exactly as before. On [Apple Account](https://account.apple.com/), under Sign-In and Security → App-Specific Passwords, create a password named `Heaven iCloud Mail`. Two-factor authentication is required. This is **not** her main Apple Account password.
2. On a trusted host, install Python 3.11+ and create an isolated environment. Run `python -m pip install '.[mcp]'` from a trusted checkout. Do not use a systemwide privileged Python.
3. Supply `ICLOUD_MAIL_USERNAME`, `ICLOUD_MAIL_APP_PASSWORD`, and `ICLOUD_MAIL_ACCOUNT_CONSENT=yes` as **ephemeral process environment variables** from a secure vault or private password prompt. Optionally set `ICLOUD_MAIL_TIMEZONE` (default `America/New_York`). Do **not** commit `.env`, use `setx`, paste secrets into ChatGPT, or add them to GitHub Actions secrets before evaluating host access.
4. Run `python -m heaven_icloud_mail`, which starts a **local stdio MCP server**. The module deliberately refuses `HEAVEN_MAIL_TRANSPORT=streamable-http` to prevent unauthenticated publication.
5. For ChatGPT mobile/Free access, a **separately authorized HTTPS remote server with OAuth** and a successful account-plan test must still be implemented. Local stdio does not solve the mobile requirement by itself. See [Delivery status](docs/DELIVERY.md).

Example normal-language request after ChatGPT integration is actually verified: `今天有什么重要邮件？请用中文简短总结，并告诉我哪些需要回复。`

## Developer quickstart

```sh
python -m pip install -e '.[test,mcp]'
python -m pytest -q
python scripts/security_gate.py
python integration/mcp_smoke.py
python -m compileall -q src integration
```

Install MCP separately with `python -m pip install -e '.[mcp]'` on the authorized host. GitHub Actions tests the independent IMAP parser, read-only invariants, and **real MCP v2 tool negotiation/call failures** on Python 3.11 and 3.13 on Windows and Linux. The in-process handshake passed at source SHA `c7f017f` on all four platform combinations; the additional stdio subprocess acceptance test is pending fresh CI at the next commit. Live iCloud auth, installed ChatGPT behavior, and Free-plan invocation **remain unverified**.

## Ownership and maintenance

- Canonical source: `fengie/heaven-icloud-mail` (this repo). Shared methods/policies: [`fengie/heaven-toolbox`](https://github.com/fengie/heaven-toolbox), no duplicate factory.
- [`AGENTS.md`](AGENTS.md): canonical bootstrap and privacy/security requirements.
- [`docs/SECURITY.md`](docs/SECURITY.md): threat model, credentials, and revocation.
- [`docs/DELIVERY.md`](docs/DELIVERY.md): exact acceptance gates and outstanding blockers.
- [Apple iCloud Mail server settings](https://support.apple.com/en-us/102525) and [Apple app-specific password help](https://support.apple.com/en-us/102654).
