"""Tests for MemoryStore.connect() parent directory auto-creation."""

from pathlib import Path

import pytest

from memory_mcp.config import MemoryConfig
from memory_mcp.store import MemoryStore


@pytest.mark.asyncio
async def test_connect_creates_missing_parent_directories(tmp_path: Path) -> None:
    """connect() must create missing parent directories for db_path."""
    nested = tmp_path / "a" / "b" / "c"
    db = nested / "memory.db"
    assert not nested.exists()

    store = MemoryStore(MemoryConfig(db_path=str(db), collection_name="t"))
    try:
        await store.connect()
        assert db.exists()
        assert nested.exists()
    finally:
        await store.disconnect()


@pytest.mark.asyncio
async def test_connect_is_idempotent_when_parent_exists(tmp_path: Path) -> None:
    """Pre-existing parent directory must not cause connect() to fail."""
    tmp_path.mkdir(exist_ok=True)
    db = tmp_path / "memory.db"

    store = MemoryStore(MemoryConfig(db_path=str(db), collection_name="t"))
    try:
        await store.connect()
        assert db.exists()
    finally:
        await store.disconnect()
