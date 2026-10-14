# Deployment and acceptance ledger — 2026-10-13

## Product goal
Mom should continue using Apple Mail with `@icloud.com`, ask ChatGPT Free **“今天有什么重要邮件？”**, and receive a Chinese summary naturally. No Gmail, Microsoft, separate service signup, manual plugin names, or perpetual copy/paste.

## Status evidence

| Gate | Status | Proof / missing next step |
| --- | --- | --- |
| GitHub repository | VERIFIED | Owner repo `fengie/heaven-icloud-mail`; initial state public, not private. Confirm privacy setting before storing any credentials (credentials never belong in Git anyway). |
| Read-only mailbox logic | SOURCE TESTED | Fake IMAP tests for readonly select, UID SEARCH, `BODY.PEEK[]`, timezone and bounded preview. No live iCloud access. |
| Apple mailbox consent | NOT STARTED | Account owner must explicitly consent and create Apple app-specific password on her own trusted device. Do not request it through chat. |
| MCP runtime | SOURCE ONLY | Python MCP SDK is an optional runtime dependency; in-process or live handshake not yet tested. stdio permitted; remote disabled. |
| Remote HTTPS + OAuth | BLOCKED: IMPLEMENTATION | Requires server hosting, OAuth, secret storage, authorization, and HTTPS. Never publish unauthorized mailbox access. |
| ChatGPT Free plugin installation | UNVERIFIED | Availability varies by plan/account. Have mom explicitly authorize and test on *her* Free account after secure server is live. |
| Automatic invocation in normal ChatGPT conversation | UNVERIFIED | Must prove a real conversation routes a Chinese email request to the MCP tool without an @ mention; do not infer from Work. |
| Live runtime deployment/rollback | PENDING | Source CI / merge / presence of installer does not establish an installed healthy service. |

## Next owned tasks

1. Verify and, if desired, change repository visibility **Private** through authenticated GitHub owner settings. The current GitHub connector does not expose administration of visibility.
2. Test Apple IMAP against a consented synthetic test mailbox, then real mailbox only with explicit owner consent. Do not persist test emails or credentials.
3. Integrate a least-privilege OAuth resource server + authorization server for a single user, externally hosted with HTTPS, replay protection, and encrypted secret storage. Reuse an established trusted identity provider only if the user approves; do not demand Gmail or Microsoft accounts.
4. Publish a private ChatGPT plugin **from mom's account** if allowed; verify tool visibility and no-@ auto invocation in normal Free chat. Do not enable publicly without an owner-approved authorization model.
5. Add an accountable host runtime/release owner and verify installed revision, auto-update, and rollback. If Free cannot invoke a custom server, record platform limitation rather than bypassing restrictions.

## Rollback
Disconnect any installed plugin, stop server, revoke Apple app-specific password. Local stdio build does not create a persistent background worker and does not modify inbox contents. Source revert alone is not a runtime rollback.

**Factory diagnosis:** External limitation (absence of provider-side Free proof and public-only repository visibility) is NOT evidence of a reusable Toolbox factory bug. Maintain product ownership here; promote only proven reusable defects to Toolbox, with evidence.
