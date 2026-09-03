"""The HTTP recall endpoint must never be able to take the MCP server down."""

from __future__ import annotations

import asyncio

from memory_mcp.server import _start_http_recall_server


async def _noop_handler(
    _reader: asyncio.StreamReader, _writer: asyncio.StreamWriter
) -> None:  # pragma: no cover - the tests never open a connection
    return None


async def test_binds_when_the_port_is_free() -> None:
    server = await _start_http_recall_server(_noop_handler, 0)

    assert server is not None
    try:
        assert server.sockets
    finally:
        server.close()
        await server.wait_closed()


async def test_returns_none_when_the_port_is_already_held() -> None:
    """A second holder of the port must degrade to stdio-only, not crash.

    The bind previously raised straight out of ``run()``, so a second Antigravity CLI
    window took down that window's memory-mcp entirely — even though its stdio
    tools never needed the HTTP endpoint in the first place.
    """
    holder = await asyncio.start_server(_noop_handler, "127.0.0.1", 0)
    port = holder.sockets[0].getsockname()[1]

    try:
        assert await _start_http_recall_server(_noop_handler, port) is None
    finally:
        holder.close()
        await holder.wait_closed()
