"""Fail CI if the checkout includes likely plaintext mailbox secrets or message dumps."""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_EXT = {".eml", ".mbox", ".pst", ".ost", ".p12", ".pfx", ".key", ".pem"}
FORBIDDEN_NAME = {".env", "secrets.json", "credentials.json"}
# Scan tracked configuration files rather than code or synthetic fixtures.
CONFIG_EXT = {".yaml", ".yml", ".json", ".toml", ".ini", ".env"}
SECRET_ASSIGNMENT = re.compile(r"(?im)^\s*(?:ICLOUD_MAIL_APP_PASSWORD|APPLE_ID_PASSWORD|MCP_ACCESS_TOKEN)\s*[:=]\s*['\"]?[^\s'\"#][^\s]*")
EXAMPLE_SECRET_ASSIGNMENT = re.compile(
    r"(?i)^[ \t]*(?:export[ \t]+)?(?:ICLOUD_MAIL_USERNAME|ICLOUD_MAIL_APP_PASSWORD|APPLE_ID_PASSWORD|MCP_ACCESS_TOKEN)[ \t]*=[ \t]*(.*)$"
)


def _populated_example_secret(data: str) -> bool:
    for line in data.splitlines():
        assignment = EXAMPLE_SECRET_ASSIGNMENT.match(line)
        if assignment is None:
            continue
        value = assignment.group(1).strip()
        if not value or value.startswith("#"):
            continue
        if value[0] in ("'", '"'):
            quoted = re.fullmatch(r"(['\"])(.*?)\1[ \t]*(?:#.*)?", value)
            if quoted is not None and not quoted.group(2).strip():
                continue
        return True
    return False


def main() -> int:
    proc = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=False)
    if proc.returncode != 0:
        # Explicitly fail rather than silently passing a checkout without a Git index.
        print("SECURITY_GATE_ERROR: Git index is required", file=sys.stderr)
        return 2
    failures = []
    for value in proc.stdout.decode("utf-8").split("\x00"):
        if not value:
            continue
        path = Path(value)
        name = path.name.casefold()
        if (name in FORBIDDEN_NAME or path.suffix.casefold() in FORBIDDEN_EXT or
                (name.startswith(".env.") and name != ".env.example")):
            failures.append(f"forbidden tracked path: {value}")
            continue
        if name == ".env.example":
            data = (ROOT / path).read_text(encoding="utf-8", errors="replace")
            if _populated_example_secret(data):
                failures.append(f"possible plaintext secret in tracked config: {value}")
        elif path.suffix.lower() in CONFIG_EXT:
            data = (ROOT / path).read_text(encoding="utf-8", errors="replace")
            if SECRET_ASSIGNMENT.search(data):
                failures.append(f"possible plaintext secret in tracked config: {value}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("SECURITY_GATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
