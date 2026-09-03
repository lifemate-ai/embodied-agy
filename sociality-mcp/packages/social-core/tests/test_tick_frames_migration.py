"""Tests for migration 004 — tick_frames table.

tick_frames is the canonical per-tick record of "what was online" in the
workspace. It stores FKs (memory ids, desire name, agent_state_summary_id,
action ref) — not payloads — so the table stays storage-rich, prompt-poor.

Backs Phase 2.3's TickFrameStore in consciousness-mcp/packages/
kernel-mcp.
"""

from __future__ import annotations

from social_core.db import SocialDB
from social_core.migrations import MIGRATIONS


def test_tick_frames_table_created(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    tables = {
        row["name"]
        for row in db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "tick_frames" in tables


def test_tick_frames_columns(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    columns = {
        row["name"] for row in db.fetchall("PRAGMA table_info(tick_frames)")
    }
    expected = {
        "tick_id",
        "ts",
        "person_id",
        "ignited",
        "conflicted",
        "attention_target_ref",
        "dominant_desire",
        "winning_memory_ids_json",
        "prediction_error_json",
        "affect_summary",
        "chosen_action_ref",
        "reportability",
        "created_at",
    }
    assert expected <= columns, f"missing: {expected - columns}"


def test_tick_frames_indexes(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    indexes = {
        row["name"]
        for row in db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='tick_frames'"
        )
    }
    assert "idx_tick_frames_ts" in indexes
    assert "idx_tick_frames_reportability" in indexes
    assert "idx_tick_frames_person" in indexes


def test_migration_004_registered(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    applied = {row["name"] for row in db.fetchall("SELECT name FROM schema_migrations")}
    assert "004_tick_frames" in applied
    assert len(applied) == len(MIGRATIONS)


def test_tick_id_is_primary_key(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    rows = db.fetchall("PRAGMA table_info(tick_frames)")
    pk_columns = [row["name"] for row in rows if row["pk"] > 0]
    assert pk_columns == ["tick_id"]


def test_tick_frames_insert_round_trip(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    db.execute(
        """
        INSERT INTO tick_frames(
            tick_id, ts, person_id, ignited, conflicted,
            attention_target_ref, dominant_desire,
            winning_memory_ids_json, prediction_error_json,
            affect_summary, chosen_action_ref, reportability, created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tick_test_001",
            "2026-06-13T03:00:00Z",
            "kouta",
            1,
            0,
            "wifi_cam.see",
            "browse_curiosity",
            '["mem_001", "mem_002"]',
            '{"extero": 0.7, "intero": 0.2, "mnemonic": 0.4}',
            "calm focus",
            "act_001",
            "mentionable",
            "2026-06-13T03:00:00Z",
        ),
    )
    row = db.fetchone(
        "SELECT * FROM tick_frames WHERE tick_id = ?",
        ("tick_test_001",),
    )
    assert row is not None
    assert row["person_id"] == "kouta"
    assert row["ignited"] == 1
    assert row["dominant_desire"] == "browse_curiosity"
    assert row["reportability"] == "mentionable"
    assert "mem_001" in row["winning_memory_ids_json"]


def test_tick_id_unique(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    db.execute(
        """
        INSERT INTO tick_frames(
            tick_id, ts, ignited, conflicted, reportability, created_at
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        ("tick_dupe", "2026-06-13T03:00:00Z", 1, 0, "mentionable", "2026-06-13T03:00:00Z"),
    )
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO tick_frames(
                tick_id, ts, ignited, conflicted, reportability, created_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                "tick_dupe",
                "2026-06-13T04:00:00Z",
                1,
                0,
                "mentionable",
                "2026-06-13T04:00:00Z",
            ),
        )
