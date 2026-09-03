"""Tests for ConsciousFrame + TickFrameStore (Phase 2.3).

The frame is the canonical per-tick record of "what was online" in the
workspace. It stores FKs and tags — payloads stay in their source tables.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kernel_mcp.frame import (
    ConsciousFrame,
    ConsciousFrameInput,
    PredictionErrorChannels,
    TickFrameStore,
)


def _minimal_input(**overrides) -> ConsciousFrameInput:
    base = dict(
        attention_target_ref="wifi_cam.see",
        ignited=True,
    )
    base.update(overrides)
    return ConsciousFrameInput(**base)


class TestConsciousFrameInput:
    def test_defaults(self) -> None:
        payload = ConsciousFrameInput()
        assert payload.ignited is False
        assert payload.conflicted is False
        assert payload.winning_memory_ids == []
        assert payload.attention_target_ref is None
        assert payload.dominant_desire is None
        assert payload.reportability == "mentionable"

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ConsciousFrameInput(unknown_field="oops")  # type: ignore[call-arg]

    def test_rejects_unknown_reportability(self) -> None:
        with pytest.raises(ValidationError):
            ConsciousFrameInput(reportability="public")  # type: ignore[arg-type]

    def test_reportability_values(self) -> None:
        for r in ("mentionable", "background_only", "do_not_surface"):
            p = ConsciousFrameInput(reportability=r)
            assert p.reportability == r

    def test_prediction_error_channels_default_zero(self) -> None:
        payload = ConsciousFrameInput()
        assert payload.prediction_error.extero == 0.0
        assert payload.prediction_error.intero == 0.0
        assert payload.prediction_error.mnemonic == 0.0

    def test_prediction_error_rejects_extra_channels(self) -> None:
        with pytest.raises(ValidationError):
            PredictionErrorChannels(extero=0.5, weird_channel=1.0)  # type: ignore[call-arg]


class TestRecord:
    def test_record_assigns_tick_id(self, social_db) -> None:
        store = TickFrameStore(social_db)
        frame = store.record(_minimal_input())
        assert frame.tick_id.startswith("tick_")

    def test_record_persists_basic_fields(self, social_db) -> None:
        store = TickFrameStore(social_db)
        frame = store.record(
            _minimal_input(
                person_id="kouta",
                dominant_desire="browse_curiosity",
                affect_summary="calm focus",
            )
        )
        row = social_db.fetchone(
            "SELECT * FROM tick_frames WHERE tick_id = ?",
            (frame.tick_id,),
        )
        assert row is not None
        assert row["person_id"] == "kouta"
        assert row["dominant_desire"] == "browse_curiosity"
        assert row["affect_summary"] == "calm focus"
        assert row["ignited"] == 1

    def test_winning_memory_ids_serialized_as_json(self, social_db) -> None:
        store = TickFrameStore(social_db)
        store.record(
            _minimal_input(winning_memory_ids=["mem_001", "mem_002", "mem_003"])
        )
        row = social_db.fetchone(
            "SELECT winning_memory_ids_json FROM tick_frames LIMIT 1"
        )
        assert row is not None
        assert "mem_001" in row["winning_memory_ids_json"]
        assert "mem_003" in row["winning_memory_ids_json"]

    def test_prediction_error_channels_serialized(self, social_db) -> None:
        store = TickFrameStore(social_db)
        store.record(
            _minimal_input(
                prediction_error=PredictionErrorChannels(
                    extero=0.7, intero=0.2, mnemonic=0.4
                )
            )
        )
        row = social_db.fetchone(
            "SELECT prediction_error_json FROM tick_frames LIMIT 1"
        )
        assert row is not None
        assert "extero" in row["prediction_error_json"]

    def test_conflicted_flag_persists(self, social_db) -> None:
        store = TickFrameStore(social_db)
        store.record(_minimal_input(conflicted=True))
        row = social_db.fetchone("SELECT conflicted FROM tick_frames LIMIT 1")
        assert row["conflicted"] == 1

    def test_subliminal_tick_record(self, social_db) -> None:
        """An ignited=False frame (subliminal tick) is still a recordable event."""
        store = TickFrameStore(social_db)
        frame = store.record(
            ConsciousFrameInput(ignited=False, reportability="background_only")
        )
        assert frame.ignited is False
        row = social_db.fetchone("SELECT * FROM tick_frames WHERE tick_id = ?", (frame.tick_id,))
        assert row["ignited"] == 0


class TestGetByTickId:
    def test_returns_frame_when_found(self, social_db) -> None:
        store = TickFrameStore(social_db)
        recorded = store.record(
            _minimal_input(winning_memory_ids=["mem_a", "mem_b"])
        )
        fetched = store.get_by_tick_id(recorded.tick_id)
        assert fetched is not None
        assert isinstance(fetched, ConsciousFrame)
        assert fetched.tick_id == recorded.tick_id
        assert fetched.winning_memory_ids == ["mem_a", "mem_b"]

    def test_returns_none_when_not_found(self, social_db) -> None:
        store = TickFrameStore(social_db)
        assert store.get_by_tick_id("nonexistent_tick") is None

    def test_round_trip_prediction_error(self, social_db) -> None:
        store = TickFrameStore(social_db)
        recorded = store.record(
            _minimal_input(
                prediction_error=PredictionErrorChannels(
                    extero=0.7, intero=0.2, mnemonic=0.4
                )
            )
        )
        fetched = store.get_by_tick_id(recorded.tick_id)
        assert fetched is not None
        assert fetched.prediction_error.extero == pytest.approx(0.7)
        assert fetched.prediction_error.intero == pytest.approx(0.2)
        assert fetched.prediction_error.mnemonic == pytest.approx(0.4)


class TestQuery:
    def test_returns_most_recent_first(self, social_db) -> None:
        store = TickFrameStore(social_db)
        store.record(_minimal_input(ts="2026-06-13T00:00:00Z"))
        store.record(_minimal_input(ts="2026-06-13T02:00:00Z"))
        store.record(_minimal_input(ts="2026-06-13T01:00:00Z"))
        results = store.query()
        assert len(results) == 3
        assert results[0].ts == "2026-06-13T02:00:00Z"
        assert results[2].ts == "2026-06-13T00:00:00Z"

    def test_filters_by_reportability(self, social_db) -> None:
        store = TickFrameStore(social_db)
        store.record(_minimal_input(reportability="mentionable"))
        store.record(_minimal_input(reportability="background_only"))
        store.record(_minimal_input(reportability="do_not_surface"))
        results = store.query(reportability="do_not_surface")
        assert len(results) == 1
        assert results[0].reportability == "do_not_surface"

    def test_ignited_only(self, social_db) -> None:
        store = TickFrameStore(social_db)
        store.record(_minimal_input(ignited=True))
        store.record(ConsciousFrameInput(ignited=False))
        store.record(_minimal_input(ignited=True))
        results = store.query(ignited_only=True)
        assert len(results) == 2
        assert all(r.ignited for r in results)

    def test_filters_by_person_id(self, social_db) -> None:
        store = TickFrameStore(social_db)
        store.record(_minimal_input(person_id="kouta"))
        store.record(_minimal_input(person_id="someone_else"))
        results = store.query(person_id="kouta")
        assert len(results) == 1
        assert results[0].person_id == "kouta"

    def test_since_filter(self, social_db) -> None:
        store = TickFrameStore(social_db)
        store.record(_minimal_input(ts="2026-06-10T00:00:00Z"))
        store.record(_minimal_input(ts="2026-06-12T00:00:00Z"))
        results = store.query(since="2026-06-11T00:00:00Z")
        assert len(results) == 1

    def test_limit(self, social_db) -> None:
        store = TickFrameStore(social_db)
        for i in range(5):
            store.record(_minimal_input(ts=f"2026-06-{10 + i:02d}T00:00:00Z"))
        results = store.query(limit=2)
        assert len(results) == 2
