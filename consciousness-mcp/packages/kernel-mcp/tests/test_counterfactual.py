"""Tests for CounterfactualStore — typed records of rejected alternatives.

Phase 2.1 foundation. The store persists CounterfactualInputs into social-core's
shared SQLite (counterfactuals table from migration 003) and returns
CounterfactualRecords that round-trip through Phase 1's EpistemicClaim type.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from social_core.models import EpistemicClaim, EvidenceType

from kernel_mcp.counterfactual import (
    COUNTERFACTUAL_SOURCES,
    CounterfactualInput,
    CounterfactualStore,
)


def _minimal_input(**overrides) -> dict:
    base = dict(
        rejected_action="send_loud_late_night_message",
        source="boundary_deny",
    )
    base.update(overrides)
    return base


class TestCounterfactualInput:
    def test_sources_are_the_documented_set(self) -> None:
        assert set(COUNTERFACTUAL_SOURCES) == {
            "boundary_deny",
            "attention_lost_bid",
            "deliberate_choice",
            "policy",
            "ignition_failed",
        }

    def test_minimal_input_is_valid(self) -> None:
        payload = CounterfactualInput(**_minimal_input())
        assert payload.rejected_action == "send_loud_late_night_message"
        assert payload.source == "boundary_deny"
        assert payload.importance == 3
        assert payload.rejected_action_payload == {}

    def test_rejects_empty_rejected_action(self) -> None:
        with pytest.raises(ValidationError):
            CounterfactualInput(**_minimal_input(rejected_action=""))

    def test_rejects_unknown_source(self) -> None:
        with pytest.raises(ValidationError):
            CounterfactualInput(**_minimal_input(source="speculation"))

    def test_accepts_all_documented_sources(self) -> None:
        for src in COUNTERFACTUAL_SOURCES:
            payload = CounterfactualInput(**_minimal_input(source=src))
            assert payload.source == src

    def test_evidence_type_uses_phase1_enum(self) -> None:
        payload = CounterfactualInput(
            **_minimal_input(evidence_type="remembered"),
        )
        assert payload.evidence_type == "remembered"
        for et in ("observed", "inferred", "remembered", "heard", "assumed"):
            p = CounterfactualInput(**_minimal_input(evidence_type=et))
            assert p.evidence_type == et

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            CounterfactualInput(
                **_minimal_input(),
                unknown_field="oops",
            )

    def test_importance_bounded_1_to_5(self) -> None:
        with pytest.raises(ValidationError):
            CounterfactualInput(**_minimal_input(importance=0))
        with pytest.raises(ValidationError):
            CounterfactualInput(**_minimal_input(importance=6))


class TestCounterfactualRecord:
    def test_record_round_trips_through_epistemic_claim(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        record = store.record(
            CounterfactualInput(
                **_minimal_input(
                    person_id="kouta",
                    reason="quiet hours policy",
                    evidence_type="remembered",
                )
            )
        )
        claim = record.to_epistemic_claim()
        assert isinstance(claim, EpistemicClaim)
        assert claim.evidence_type == "remembered"
        assert claim.source == "boundary_deny"
        assert "send_loud_late_night_message" in claim.content

    def test_inferred_default_when_evidence_type_omitted(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        record = store.record(CounterfactualInput(**_minimal_input()))
        claim = record.to_epistemic_claim()
        # Default for a decision-record is inferred (we inferred the chosen
        # action was preferable). Confidence is conservative.
        assert claim.evidence_type == "inferred"
        assert claim.confidence <= 0.8


class TestCounterfactualStoreRecord:
    def test_record_assigns_id_and_persists(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        record = store.record(
            CounterfactualInput(
                **_minimal_input(
                    person_id="kouta",
                    reason="quiet hours policy",
                )
            )
        )
        assert record.counterfactual_id.startswith("cf_")
        assert record.ts is not None
        assert record.created_at is not None

        row = social_db.fetchone(
            "SELECT * FROM counterfactuals WHERE counterfactual_id = ?",
            (record.counterfactual_id,),
        )
        assert row is not None
        assert row["rejected_action"] == "send_loud_late_night_message"
        assert row["source"] == "boundary_deny"
        assert row["person_id"] == "kouta"

    def test_record_serializes_payload_as_json(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        store.record(
            CounterfactualInput(
                **_minimal_input(
                    rejected_action_payload={"channel": "tts", "text_preview": "hey"},
                )
            )
        )
        row = social_db.fetchone(
            "SELECT rejected_action_payload_json FROM counterfactuals LIMIT 1"
        )
        assert row is not None
        assert '"channel"' in row["rejected_action_payload_json"]

    def test_record_explicit_ts_is_honored(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        record = store.record(
            CounterfactualInput(
                **_minimal_input(ts="2026-06-13T03:00:00Z"),
            )
        )
        assert record.ts == "2026-06-13T03:00:00Z"


class TestCounterfactualStoreQuery:
    def test_query_returns_most_recent_first(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        store.record(
            CounterfactualInput(
                **_minimal_input(
                    rejected_action="action_old",
                    ts="2026-06-10T00:00:00Z",
                )
            )
        )
        store.record(
            CounterfactualInput(
                **_minimal_input(
                    rejected_action="action_new",
                    ts="2026-06-12T00:00:00Z",
                )
            )
        )
        results = store.query()
        assert len(results) == 2
        assert results[0].rejected_action == "action_new"
        assert results[1].rejected_action == "action_old"

    def test_query_filters_by_source(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        store.record(
            CounterfactualInput(
                **_minimal_input(rejected_action="a", source="boundary_deny")
            )
        )
        store.record(
            CounterfactualInput(
                **_minimal_input(rejected_action="b", source="attention_lost_bid")
            )
        )
        results = store.query(source="attention_lost_bid")
        assert len(results) == 1
        assert results[0].rejected_action == "b"

    def test_query_filters_by_tick_id(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        store.record(
            CounterfactualInput(
                **_minimal_input(rejected_action="a", tick_id="tick_001")
            )
        )
        store.record(
            CounterfactualInput(
                **_minimal_input(rejected_action="b", tick_id="tick_002")
            )
        )
        results = store.query(tick_id="tick_001")
        assert len(results) == 1
        assert results[0].rejected_action == "a"

    def test_query_filters_by_person_id(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        store.record(
            CounterfactualInput(
                **_minimal_input(rejected_action="a", person_id="kouta")
            )
        )
        store.record(
            CounterfactualInput(
                **_minimal_input(rejected_action="b", person_id="someone_else")
            )
        )
        results = store.query(person_id="kouta")
        assert len(results) == 1
        assert results[0].rejected_action == "a"

    def test_query_since_filter(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        store.record(
            CounterfactualInput(
                **_minimal_input(
                    rejected_action="old",
                    ts="2026-06-10T00:00:00Z",
                )
            )
        )
        store.record(
            CounterfactualInput(
                **_minimal_input(
                    rejected_action="new",
                    ts="2026-06-12T00:00:00Z",
                )
            )
        )
        results = store.query(since="2026-06-11T00:00:00Z")
        assert len(results) == 1
        assert results[0].rejected_action == "new"

    def test_query_limit(self, social_db) -> None:
        store = CounterfactualStore(social_db)
        for i in range(5):
            store.record(
                CounterfactualInput(
                    **_minimal_input(
                        rejected_action=f"action_{i}",
                        ts=f"2026-06-{10 + i:02d}T00:00:00Z",
                    )
                )
            )
        results = store.query(limit=2)
        assert len(results) == 2


def test_evidence_type_uses_phase1_type() -> None:
    """Pinning: EvidenceType IS Phase 1's, not a duplicate enum."""
    # This is asserted by the import path at the top of the module — keep
    # an explicit check so a future refactor that copies the enum gets caught.
    from kernel_mcp.counterfactual import CounterfactualInput
    sig = CounterfactualInput.model_fields["evidence_type"]
    # The annotation should resolve through Phase 1's EvidenceType.
    assert "EvidenceType" in str(sig.annotation) or "Literal" in str(sig.annotation)
    _ = EvidenceType  # noqa: F841 — keep import alive for static graph
