"""Tests for Phase 2.2 workspace.py extensions.

Phase 2.2 adds three dataclasses on top of the existing winner-take-all
selection: PrecisionVector (per-channel weights), WorkspaceConfig
(ignition_threshold + refractory), RefractoryState (cooldown counter).
The new select_workspace_candidates_with_ignition() returns a
WorkspaceSelectionResult that surfaces ignition success + per-channel
breakdown for explainability. The plan-of-record is
~/.gemini/plans/jazzy-wishing-starfish.md.

The existing select_workspace_candidates() signature is preserved as a
thin wrapper for backward compatibility — no caller in store.py is
forced to upgrade in this PR.
"""

from __future__ import annotations

import pytest

from memory_mcp.types import Memory
from memory_mcp.workspace import (
    PrecisionVector,
    RefractoryState,
    ScoreBreakdown,
    WorkspaceCandidate,
    WorkspaceConfig,
    WorkspaceSelectionResult,
    precision_from_pe_channels,
    select_workspace_candidates,
    select_workspace_candidates_with_ignition,
)


def _memory(memory_id: str, content: str = "x") -> Memory:
    return Memory(
        id=memory_id,
        content=content,
        timestamp="2026-06-13T03:00:00+00:00",
        emotion="neutral",
        importance=3,
        category="daily",
    )


def _candidate(
    memory_id: str,
    *,
    relevance: float = 0.5,
    novelty: float = 0.5,
    prediction_error: float = 0.5,
    emotion_boost: float = 0.0,
    content: str | None = None,
) -> WorkspaceCandidate:
    return WorkspaceCandidate(
        memory=_memory(memory_id, content=content or f"content_{memory_id}"),
        relevance=relevance,
        novelty=novelty,
        prediction_error=prediction_error,
        emotion_boost=emotion_boost,
    )


class TestPrecisionVector:
    def test_default_weights_match_legacy_fixed_weights(self) -> None:
        """The default PrecisionVector reproduces the pre-Phase-2.2 weights."""
        pv = PrecisionVector.default()
        assert pv.relevance == pytest.approx(0.45)
        assert pv.novelty == pytest.approx(0.20)
        assert pv.prediction_error == pytest.approx(0.20)
        assert pv.emotion == pytest.approx(0.15)

    def test_weights_sum_to_one_by_construction(self) -> None:
        pv = PrecisionVector.default()
        total = pv.relevance + pv.novelty + pv.prediction_error + pv.emotion
        assert total == pytest.approx(1.0)

    def test_normalize_scales_to_unit_budget(self) -> None:
        pv = PrecisionVector(
            relevance=0.4, novelty=0.4, prediction_error=0.4, emotion=0.4
        ).normalized()
        total = pv.relevance + pv.novelty + pv.prediction_error + pv.emotion
        assert total == pytest.approx(1.0)

    def test_normalize_preserves_ratios(self) -> None:
        pv = PrecisionVector(
            relevance=2.0, novelty=1.0, prediction_error=1.0, emotion=0.0
        ).normalized()
        # 2:1:1:0 → 0.5:0.25:0.25:0.0
        assert pv.relevance == pytest.approx(0.5)
        assert pv.novelty == pytest.approx(0.25)
        assert pv.prediction_error == pytest.approx(0.25)
        assert pv.emotion == pytest.approx(0.0)

    def test_normalize_handles_zero_sum_gracefully(self) -> None:
        """All-zero vector must not blow up; falls back to uniform."""
        pv = PrecisionVector(
            relevance=0.0, novelty=0.0, prediction_error=0.0, emotion=0.0
        ).normalized()
        # No NaN, no crash — uniform fallback
        assert pv.relevance == pytest.approx(0.25)
        assert pv.novelty == pytest.approx(0.25)
        assert pv.prediction_error == pytest.approx(0.25)
        assert pv.emotion == pytest.approx(0.25)


class TestPrecisionFromPE:
    def test_higher_pe_channel_gets_higher_weight(self) -> None:
        """When a channel has high z-score PE, its precision (weight) goes up."""
        # extero high, intero low, mnemonic low → extero gets larger weight
        pv = precision_from_pe_channels(
            extero=1.5,
            intero=0.0,
            mnemonic=0.0,
        )
        # extero maps to relevance (perception); intero to emotion;
        # mnemonic to prediction_error/novelty.
        assert pv.relevance > pv.emotion
        assert pv.relevance > pv.prediction_error

    def test_uniform_pe_returns_near_default_weights(self) -> None:
        """All channels equal → weights converge toward default ratios."""
        pv = precision_from_pe_channels(extero=0.0, intero=0.0, mnemonic=0.0)
        default = PrecisionVector.default()
        # When PE is uniform, fall back to defaults.
        assert pv.relevance == pytest.approx(default.relevance, abs=0.05)
        assert pv.emotion == pytest.approx(default.emotion, abs=0.05)


class TestWorkspaceConfig:
    def test_default_disables_ignition_threshold(self) -> None:
        """Default config keeps legacy behavior: always ignite."""
        cfg = WorkspaceConfig()
        assert cfg.ignition_threshold == 0.0

    def test_refractory_defaults_to_zero(self) -> None:
        cfg = WorkspaceConfig()
        assert cfg.refractory_ticks == 0


class TestRefractoryState:
    def test_inactive_state_does_not_block(self) -> None:
        state = RefractoryState(remaining_ticks=0)
        assert state.is_active() is False

    def test_active_state_blocks(self) -> None:
        state = RefractoryState(remaining_ticks=3)
        assert state.is_active() is True

    def test_decay_reduces_by_one(self) -> None:
        assert RefractoryState(remaining_ticks=3).decay().remaining_ticks == 2
        assert RefractoryState(remaining_ticks=1).decay().remaining_ticks == 0
        assert RefractoryState(remaining_ticks=0).decay().remaining_ticks == 0


class TestIgnitionThreshold:
    def test_below_threshold_returns_subliminal_tick(self) -> None:
        """If no candidate scores above ignition_threshold, ignited=False and
        winners is empty (subliminal tick — Kokone allowed to not respond)."""
        cfg = WorkspaceConfig(ignition_threshold=2.0)  # impossibly high
        candidates = [_candidate("m1", relevance=0.5, novelty=0.5)]
        result = select_workspace_candidates_with_ignition(
            candidates, max_results=3, config=cfg
        )
        assert isinstance(result, WorkspaceSelectionResult)
        assert result.ignited is False
        assert result.winners == []

    def test_above_threshold_ignites_and_returns_winners(self) -> None:
        cfg = WorkspaceConfig(ignition_threshold=0.0)
        candidates = [
            _candidate("m1", relevance=0.9, novelty=0.5),
            _candidate("m2", relevance=0.3, novelty=0.5),
        ]
        result = select_workspace_candidates_with_ignition(
            candidates, max_results=2, config=cfg
        )
        assert result.ignited is True
        assert len(result.winners) == 2

    def test_refractory_state_raises_threshold(self) -> None:
        """During refractory period, the effective threshold is boosted."""
        # Base threshold passes (0.0), but during refractory, boost makes it harder.
        cfg = WorkspaceConfig(
            ignition_threshold=0.0,
            refractory_ticks=3,
            refractory_boost=2.0,  # impossibly high during refractory
        )
        candidates = [_candidate("m1", relevance=0.5, novelty=0.5)]
        refractory = RefractoryState(remaining_ticks=2)
        result = select_workspace_candidates_with_ignition(
            candidates, max_results=1, config=cfg, refractory=refractory
        )
        assert result.ignited is False
        assert result.winners == []

    def test_post_ignition_returns_new_refractory(self) -> None:
        """A successful ignition installs a refractory cooldown for next tick."""
        cfg = WorkspaceConfig(refractory_ticks=5)
        candidates = [_candidate("m1", relevance=0.9)]
        result = select_workspace_candidates_with_ignition(
            candidates, max_results=1, config=cfg
        )
        assert result.ignited is True
        assert result.new_refractory is not None
        assert result.new_refractory.remaining_ticks == 5

    def test_failed_ignition_decays_existing_refractory(self) -> None:
        """A subliminal tick does not install a new refractory but
        continues the old one's decay."""
        cfg = WorkspaceConfig(
            ignition_threshold=10.0,  # never ignites
            refractory_ticks=5,
        )
        candidates = [_candidate("m1", relevance=0.5)]
        refractory = RefractoryState(remaining_ticks=3)
        result = select_workspace_candidates_with_ignition(
            candidates, max_results=1, config=cfg, refractory=refractory
        )
        assert result.ignited is False
        assert result.new_refractory is not None
        assert result.new_refractory.remaining_ticks == 2  # decayed


class TestPrecisionInfluencesSelection:
    def test_high_relevance_precision_picks_relevance_winner(self) -> None:
        pv = PrecisionVector(
            relevance=1.0, novelty=0.0, prediction_error=0.0, emotion=0.0
        )
        candidates = [
            _candidate("rel_high", relevance=0.9, novelty=0.0),
            _candidate("nov_high", relevance=0.0, novelty=0.9),
        ]
        result = select_workspace_candidates_with_ignition(
            candidates, max_results=1, precision=pv
        )
        assert result.winners[0][0].memory.id == "rel_high"

    def test_high_novelty_precision_picks_novelty_winner(self) -> None:
        pv = PrecisionVector(
            relevance=0.0, novelty=1.0, prediction_error=0.0, emotion=0.0
        )
        candidates = [
            _candidate("rel_high", relevance=0.9, novelty=0.0),
            _candidate("nov_high", relevance=0.0, novelty=0.9),
        ]
        result = select_workspace_candidates_with_ignition(
            candidates, max_results=1, precision=pv
        )
        assert result.winners[0][0].memory.id == "nov_high"


class TestScoreBreakdown:
    def test_breakdown_emitted_per_winner(self) -> None:
        candidates = [
            _candidate("m1", relevance=0.8),
            _candidate("m2", relevance=0.6),
        ]
        result = select_workspace_candidates_with_ignition(
            candidates, max_results=2
        )
        assert len(result.breakdown) == 2
        for b in result.breakdown:
            assert isinstance(b, ScoreBreakdown)

    def test_breakdown_channel_contributions_sum_to_score(self) -> None:
        candidates = [
            _candidate("m1", relevance=0.8, novelty=0.4, prediction_error=0.2)
        ]
        result = select_workspace_candidates_with_ignition(
            candidates, max_results=1
        )
        b = result.breakdown[0]
        reconstructed = (
            b.relevance_contribution
            + b.novelty_contribution
            + b.prediction_error_contribution
            + b.emotion_contribution
            - b.redundancy_penalty
        )
        assert reconstructed == pytest.approx(b.total)

    def test_breakdown_winner_id_matches_memory(self) -> None:
        candidates = [_candidate("specific_id", relevance=0.7)]
        result = select_workspace_candidates_with_ignition(
            candidates, max_results=1
        )
        assert result.breakdown[0].memory_id == "specific_id"


class TestBackwardCompatibility:
    def test_legacy_select_workspace_candidates_still_returns_list_of_tuples(self) -> None:
        """The legacy signature must continue to work — no caller forced to upgrade."""
        candidates = [
            _candidate("m1", relevance=0.8),
            _candidate("m2", relevance=0.6),
        ]
        result = select_workspace_candidates(candidates, max_results=2)
        # Still a list of (candidate, score) tuples.
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(item, tuple) for item in result)
        assert all(len(item) == 2 for item in result)

    def test_legacy_signature_picks_winners_consistent_with_ignition_api(self) -> None:
        candidates = [
            _candidate("strong", relevance=0.9),
            _candidate("weak", relevance=0.1),
        ]
        legacy = select_workspace_candidates(candidates, max_results=1)
        modern = select_workspace_candidates_with_ignition(
            candidates, max_results=1
        )
        assert legacy[0][0].memory.id == modern.winners[0][0].memory.id
