"""Single-mailbox credentials; fail closed without account-owner consent."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Settings:
    username: str
    password: str = field(repr=False)
    timezone_name: str = "America/New_York"

    @classmethod
    def from_mapping(cls, environ: Mapping[str, str]) -> "Settings":
        if environ.get("ICLOUD_MAIL_ACCOUNT_CONSENT", "").lower().strip() != "yes":
            raise ValueError("Account-owner consent must be explicitly enabled")
        username = environ.get("ICLOUD_MAIL_USERNAME", "").strip()
        password = environ.get("ICLOUD_MAIL_APP_PASSWORD", "")
        if not username or not password:
            raise ValueError("iCloud Mail credentials must be supplied through secret environment settings")
        # App passwords can be used with Apple domains; refuse accidentally targeting other providers.
        if not username.lower().endswith(("@icloud.com", "@me.com", "@mac.com")):
            raise ValueError("Only Apple iCloud Mail account addresses are permitted")
        tz = environ.get("ICLOUD_MAIL_TIMEZONE", "America/New_York")
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unrecognized mailbox timezone") from exc
        return cls(username=username, password=password, timezone_name=tz)

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls.from_mapping(os.environ)
