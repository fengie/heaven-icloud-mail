"""MCP v2 protocol smoke test, in memory: no mailbox, network or credentials.

CI installs the actual MCP SDK and checks what an actual MCP host can discover.
Do not substitute mocked decorators for this test: that misses SDK breakages.
"""
from __future__ import annotations

import asyncio
import os

from mcp import Client

from heaven_icloud_mail.server import build_mcp


async def _verify() -> None:
    # Force a fail-closed tool call even if the runner later acquires secrets.
    for key in ("ICLOUD_MAIL_USERNAME", "ICLOUD_MAIL_APP_PASSWORD", "ICLOUD_MAIL_ACCOUNT_CONSENT"):
        os.environ.pop(key, None)

    async with Client(build_mcp()) as client:
        assert client.server_capabilities.tools is not None
        tools = await client.list_tools()
        names = [tool.name for tool in tools.tools]
        assert names == ["summarize_icloud_mail"], names
        tool = tools.tools[0]
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False
        assert "今天有什么重要邮件" in (tool.description or "")

        # Without explicit owner consent and runtime credentials the tool MUST
        # refuse access before any IMAP connection, and the MCP client must get
        # a tool error, not an unhandled transport/protocol crash.
        result = await client.call_tool("summarize_icloud_mail", {"day": "today", "limit": 1})
        assert result.is_error is True, result


if __name__ == "__main__":
    asyncio.run(_verify())
    print("MCP_V2_PROTOCOL_OK")
