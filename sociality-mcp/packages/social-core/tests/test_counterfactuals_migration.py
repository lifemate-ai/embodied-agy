"""Tests for migration 003 — counterfactuals table.

Counterfactuals are typed records of "the action the agent rejected and why",
used by Phase 2.1's CounterfactualStore (in consciousness-mcp/packages/
kernel-mcp). The table lives in social-core's shared SQLite so
multiple processes can write to it transactionally alongside the existing
agent_experiences / interpretation_shifts tables.
"""

from __future__ import annotations

from social_core.db import SocialDB
from social_core.migrations import MIGRATIONS


def test_counterfactuals_table_created(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    tables = {
        row["name"]
        for row in db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "counterfactuals" in tables


def test_counterfactuals_columns(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    columns = {
        row["name"]
        for row in db.fetchall("PRAGMA table_info(counterfactuals)")
    }
    expected = {
        "counterfactual_id",
        "tick_id",
        "ts",
        "person_id",
        "chosen_action_ref",
        "rejected_action",
        "rejected_action_payload_json",
        "reason",
        "source",
        "expected_outcome",
        "evidence_type",
        "importance",
        "created_at",
    }
    assert expected <= columns, f"missing: {expected - columns}"


def test_counterfactuals_indexes(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    indexes = {
        row["name"]
        for row in db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='counterfactuals'"
        )
    }
    assert "idx_counterfactuals_ts" in indexes
    assert "idx_counterfactuals_source" in indexes
    assert "idx_counterfactuals_tick" in indexes


def test_migration_003_registered(temp_db_path) -> None:
    db = SocialDB(temp_db_path)
    db.connect()
    applied = {row["name"] for row in db.fetchall("SELECT name FROM schema_migrations")}
    assert "003_counterfactuals" in applied
    assert len(applied) == len(MIGRATIONS)


def test_counterfactuals_insert_round_trip(temp_db_path) -> None:
    """The schema accepts a fully populated row and reads it back."""
    db = SocialDB(temp_db_path)
    db.connect()
    db.execute(
        """
        INSERT INTO counterfactuals(
            counterfactual_id, tick_id, ts, person_id,
            chosen_action_ref, rejected_action, rejected_action_payload_json,
            reason, source, expected_outcome, evidence_type, importance,
            created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "cf_test_001",
            "tick_test_001",
            "2026-06-13T03:00:00Z",
            "kouta",
            "act_001",
            "send_loud_late_night_message",
            '{"channel": "tts", "text_preview": "hey"}',
            "boundary policy: quiet hours",
            "boundary_deny",
            "user reports interrupted sleep",
            "remembered",
            4,
            "2026-06-13T03:00:00Z",
        ),
    )
    row = db.fetchone(
        "SELECT * FROM counterfactuals WHERE counterfactual_id = ?",
        ("cf_test_001",),
    )
    assert row is not None
    assert row["rejected_action"] == "send_loud_late_night_message"
    assert row["source"] == "boundary_deny"
    assert row["evidence_type"] == "remembered"
    assert row["importance"] == 4
