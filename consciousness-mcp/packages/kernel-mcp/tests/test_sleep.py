"""Tests for SleepConsolidator — quiet-hours-gated scheduler glue.

Phase 2.1 ships only the glue: quiet-hours gate, briefing assembly,
morning_briefing.json emission. The actual memory-mcp consolidate/recall_divergent
calls are mocked here and will be wired in a subsequent PR — this PR proves the
scheduling skeleton, not the consolidation engine itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from kernel_mcp.counterfactual import (
    CounterfactualInput,
    CounterfactualStore,
)
from kernel_mcp.sleep import (
    MorningBriefing,
    SleepConsolidationResult,
    SleepConsolidator,
)


def _quiet_yes(_ts: str) -> bool:
    return True


def _quiet_no(_ts: str) -> bool:
    return False


def _fixed_clock(_ts: str = "2026-06-13T18:30:00+00:00"):
    def now() -> str:
        return _ts

    return now


class TestQuietHoursGate:
    def test_skipped_when_not_in_quiet_hours(self, social_db, tmp_path):
        store = CounterfactualStore(social_db)
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=tmp_path / "morning_briefing.json",
            is_quiet_hours=_quiet_no,
            clock=_fixed_clock(),
        )
        result = consolidator.run()
        assert isinstance(result, SleepConsolidationResult)
        assert result.ran is False
        assert result.skipped_reason is not None
        assert "quiet" in result.skipped_reason
        assert result.briefing is None

    def test_runs_when_in_quiet_hours(self, social_db, tmp_path):
        store = CounterfactualStore(social_db)
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=tmp_path / "morning_briefing.json",
            is_quiet_hours=_quiet_yes,
            clock=_fixed_clock(),
        )
        result = consolidator.run()
        assert result.ran is True
        assert result.briefing is not None

    def test_force_bypasses_gate(self, social_db, tmp_path):
        store = CounterfactualStore(social_db)
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=tmp_path / "morning_briefing.json",
            is_quiet_hours=_quiet_no,
            clock=_fixed_clock(),
        )
        result = consolidator.run(force=True)
        assert result.ran is True
        assert result.briefing is not None


class TestBriefingContent:
    def test_briefing_includes_counterfactual_count(self, social_db, tmp_path):
        store = CounterfactualStore(social_db)
        for i in range(3):
            store.record(
                CounterfactualInput(
                    rejected_action=f"action_{i}",
                    source="boundary_deny",
                    ts="2026-06-13T03:00:00+00:00",
                )
            )
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=tmp_path / "morning_briefing.json",
            is_quiet_hours=_quiet_yes,
            clock=_fixed_clock(),
        )
        result = consolidator.run()
        assert result.briefing.counterfactual_count == 3

    def test_summary_line_under_120_chars(self, social_db, tmp_path):
        store = CounterfactualStore(social_db)
        store.record(
            CounterfactualInput(
                rejected_action="x",
                source="attention_lost_bid",
            )
        )
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=tmp_path / "morning_briefing.json",
            is_quiet_hours=_quiet_yes,
            clock=_fixed_clock(),
        )
        result = consolidator.run()
        assert len(result.briefing.summary_line) <= 120

    def test_briefing_includes_top_counterfactuals(self, social_db, tmp_path):
        store = CounterfactualStore(social_db)
        for i in range(5):
            store.record(
                CounterfactualInput(
                    rejected_action=f"action_{i}",
                    source="boundary_deny",
                    importance=4,
                    ts=f"2026-06-13T0{i}:00:00+00:00",
                )
            )
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=tmp_path / "morning_briefing.json",
            is_quiet_hours=_quiet_yes,
            clock=_fixed_clock(),
        )
        result = consolidator.run()
        # Top-3 by importance + recency
        assert len(result.briefing.top_counterfactuals) <= 3

    def test_briefing_window_uses_24h_default(self, social_db, tmp_path):
        store = CounterfactualStore(social_db)
        # Outside window: 48h ago
        store.record(
            CounterfactualInput(
                rejected_action="old",
                source="boundary_deny",
                ts="2026-06-11T18:30:00+00:00",
            )
        )
        # Inside window: 6h ago
        store.record(
            CounterfactualInput(
                rejected_action="recent",
                source="boundary_deny",
                ts="2026-06-13T12:30:00+00:00",
            )
        )
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=tmp_path / "morning_briefing.json",
            is_quiet_hours=_quiet_yes,
            clock=_fixed_clock(),
        )
        result = consolidator.run()
        # Only the recent one is counted
        assert result.briefing.counterfactual_count == 1


class TestBriefingPersistence:
    def test_briefing_written_to_path(self, social_db, tmp_path):
        path = tmp_path / "morning_briefing.json"
        store = CounterfactualStore(social_db)
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=path,
            is_quiet_hours=_quiet_yes,
            clock=_fixed_clock(),
        )
        result = consolidator.run()
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "summary_line" in data
        assert "counterfactual_count" in data
        assert result.briefing_path == str(path)

    def test_briefing_is_written_as_utf8(self, social_db, tmp_path):
        """summary_line is always Japanese, so the file is never pure ASCII.

        SleepConsolidator pins encoding="utf-8" on the write; nothing asserted it.
        Reading the raw bytes keeps the on-disk encoding independent of the
        locale of whoever runs the suite.
        """
        path = tmp_path / "morning_briefing.json"
        store = CounterfactualStore(social_db)
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=path,
            is_quiet_hours=_quiet_yes,
            clock=_fixed_clock(),
        )
        consolidator.run()
        data = json.loads(path.read_bytes().decode("utf-8"))
        assert not data["summary_line"].isascii()

    def test_dry_run_does_not_write(self, social_db, tmp_path):
        path = tmp_path / "morning_briefing.json"
        store = CounterfactualStore(social_db)
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=path,
            is_quiet_hours=_quiet_yes,
            clock=_fixed_clock(),
        )
        result = consolidator.run(dry_run=True)
        assert not path.exists()
        assert result.ran is True
        assert result.briefing is not None
        assert result.briefing_path is None

    def test_briefing_parent_dir_created(self, social_db, tmp_path):
        path = tmp_path / "nested" / "dir" / "morning_briefing.json"
        store = CounterfactualStore(social_db)
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=path,
            is_quiet_hours=_quiet_yes,
            clock=_fixed_clock(),
        )
        consolidator.run()
        assert path.exists()


class TestMorningBriefingShape:
    def test_briefing_serializes_round_trip(self, social_db, tmp_path):
        path = tmp_path / "morning_briefing.json"
        store = CounterfactualStore(social_db)
        consolidator = SleepConsolidator(
            db=social_db,
            counterfactual_store=store,
            briefing_path=path,
            is_quiet_hours=_quiet_yes,
            clock=_fixed_clock(),
        )
        consolidator.run()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        # MorningBriefing must be re-constructible from disk JSON
        briefing = MorningBriefing(**data)
        assert briefing.summary_line == data["summary_line"]


def test_default_briefing_path_is_under_gemini_dir():
    """The shipping default lives under ~/.gemini/ so autonomous-action.sh can find it."""
    from kernel_mcp.sleep import DEFAULT_BRIEFING_PATH

    assert Path(DEFAULT_BRIEFING_PATH).parts[-2:] == (
        ".gemini",
        "morning_briefing.json",
    )
