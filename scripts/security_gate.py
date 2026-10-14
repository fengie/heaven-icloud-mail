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
        if (path.name.lower() in FORBIDDEN_NAME or path.suffix.lower() in FORBIDDEN_EXT or
                (path.name.startswith(".env.") and path.name != ".env.example")):
            failures.append(f"forbidden tracked path: {value}")
            continue
        if path.suffix.lower() in CONFIG_EXT and path.name != ".env.example":
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
