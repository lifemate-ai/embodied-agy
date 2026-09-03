"""Global-workspace inspired candidate selection.

Phase 2.2 extends the original winner-take-all selection with:
  - PrecisionVector: per-channel weights (replaces fixed 0.45/0.20/0.20/0.15)
  - precision_from_pe_channels: precision allocation from PE z-scores
  - WorkspaceConfig: ignition_threshold + refractory_ticks
  - RefractoryState: post-ignition cooldown that boosts the threshold
  - ScoreBreakdown: per-channel contribution for explainability
  - WorkspaceSelectionResult: structured return with ignited flag

The legacy select_workspace_candidates() signature is preserved as a thin
wrapper — existing callers in store.py keep working unchanged.

See consciousness-mcp/AGENTS.md for vocabulary discipline (functional
language only in technical artifacts).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .predictive import memory_tokens
from .types import Memory


@dataclass(frozen=True)
class WorkspaceCandidate:
    """Candidate for workspace competition."""

    memory: Memory
    relevance: float
    novelty: float
    prediction_error: float
    emotion_boost: float


@dataclass(frozen=True)
class PrecisionVector:
    """Per-channel weights for utility computation.

    Channel mapping:
      relevance         — exteroceptive perception / context match
      novelty           — mnemonic novelty
      prediction_error  — mnemonic prediction error
      emotion           — interoceptive / emotional weighting

    Default values match the legacy fixed weights (0.45 / 0.20 / 0.20 / 0.15)
    so an explicit `precision=None` produces the same selection as before
    Phase 2.2 shipped.
    """

    relevance: float
    novelty: float
    prediction_error: float
    emotion: float

    @classmethod
    def default(cls) -> PrecisionVector:
        return cls(relevance=0.45, novelty=0.20, prediction_error=0.20, emotion=0.15)

    def normalized(self, budget: float = 1.0) -> PrecisionVector:
        total = self.relevance + self.novelty + self.prediction_error + self.emotion
        if total <= 0:
            # Uniform fallback — never blow up on an all-zero vector.
            quarter = budget / 4
            return PrecisionVector(quarter, quarter, quarter, quarter)
        scale = budget / total
        return PrecisionVector(
            relevance=self.relevance * scale,
            novelty=self.novelty * scale,
            prediction_error=self.prediction_error * scale,
            emotion=self.emotion * scale,
        )


def precision_from_pe_channels(
    *,
    extero: float,
    intero: float,
    mnemonic: float,
) -> PrecisionVector:
    """Build a PrecisionVector from per-channel prediction-error z-scores.

    Mapping:
      extero PE   -> relevance weight (perception drives attention)
      intero PE   -> emotion weight   (interoception drives affective weighting)
      mnemonic PE -> split 60/40 between novelty and prediction_error

    Implementation: softmax over |PE| (negative PE is as informative as
    positive PE). All-zero PE falls back to PrecisionVector.default() so
    a quiet tick produces legacy weights rather than uniform 0.25s.
    """
    if extero == 0.0 and intero == 0.0 and mnemonic == 0.0:
        return PrecisionVector.default()

    e_x = math.exp(abs(extero))
    e_i = math.exp(abs(intero))
    e_m = math.exp(abs(mnemonic))
    total = e_x + e_i + e_m
    mnemonic_share = e_m / total
    return PrecisionVector(
        relevance=e_x / total,
        novelty=mnemonic_share * 0.6,
        prediction_error=mnemonic_share * 0.4,
        emotion=e_i / total,
    ).normalized()


@dataclass(frozen=True)
class WorkspaceConfig:
    """Configuration for ignition + refractory dynamics.

    Defaults preserve legacy behavior:
      ignition_threshold=0.0 means every tick ignites (any non-empty
      candidate set produces winners).
      refractory_ticks=0 means no post-ignition cooldown.
    """

    ignition_threshold: float = 0.0
    refractory_ticks: int = 0
    refractory_boost: float = 0.3


@dataclass(frozen=True)
class RefractoryState:
    """Post-ignition cooldown that boosts the effective threshold."""

    remaining_ticks: int

    def is_active(self) -> bool:
        return self.remaining_ticks > 0

    def decay(self) -> RefractoryState:
        return RefractoryState(remaining_ticks=max(0, self.remaining_ticks - 1))


@dataclass(frozen=True)
class ScoreBreakdown:
    """Per-channel contribution to a winner's total score (for explainability)."""

    memory_id: str
    relevance_contribution: float
    novelty_contribution: float
    prediction_error_contribution: float
    emotion_contribution: float
    redundancy_penalty: float
    total: float


@dataclass(frozen=True)
class WorkspaceSelectionResult:
    """Result of select_workspace_candidates_with_ignition.

    winners is empty when the top candidate fails the ignition threshold —
    a subliminal tick. breakdown is empty in that case too; the agent is
    allowed to be non-responsive without explaining a non-winner.
    new_refractory is the cooldown state to thread into the next call:
      - ignited tick installs a fresh RefractoryState(cfg.refractory_ticks)
      - subliminal tick decays any incoming refractory by 1
      - if no incoming refractory and no ignition, new_refractory is None
    """

    winners: list[tuple[WorkspaceCandidate, float]]
    ignited: bool
    breakdown: list[ScoreBreakdown]
    new_refractory: RefractoryState | None


def _candidate_utility(
    candidate: WorkspaceCandidate,
    redundancy_penalty: float,
    temperature: float,
) -> float:
    temp = max(0.1, min(2.0, temperature))
    utility = (
        0.45 * candidate.relevance
        + 0.2 * candidate.novelty
        + 0.2 * candidate.prediction_error
        + 0.15 * candidate.emotion_boost
        - 0.25 * redundancy_penalty
    )
    return utility / temp


def _redundancy_penalty(memory: Memory, selected: list[Memory]) -> float:
    if not selected:
        return 0.0

    target_tokens = memory_tokens(memory)
    if not target_tokens:
        return 0.0

    overlaps: list[float] = []
    for item in selected:
        item_tokens = memory_tokens(item)
        if not item_tokens:
            continue
        union = target_tokens | item_tokens
        if not union:
            continue
        overlaps.append(len(target_tokens & item_tokens) / len(union))

    if not overlaps:
        return 0.0
    return max(overlaps)


def select_workspace_candidates(
    candidates: list[WorkspaceCandidate],
    max_results: int,
    temperature: float = 0.7,
) -> list[tuple[WorkspaceCandidate, float]]:
    """Select memories through iterative winner-take-all competition.

    Legacy signature preserved for backward compatibility. Calls
    select_workspace_candidates_with_ignition under the hood with the
    default WorkspaceConfig (ignition_threshold=0 → every tick ignites)
    and PrecisionVector.default() (legacy fixed weights). Existing
    callers continue to receive list[(candidate, score)] tuples.
    """
    result = select_workspace_candidates_with_ignition(
        candidates,
        max_results,
        temperature=temperature,
    )
    return result.winners


def select_workspace_candidates_with_ignition(
    candidates: list[WorkspaceCandidate],
    max_results: int,
    *,
    temperature: float = 0.7,
    config: WorkspaceConfig | None = None,
    precision: PrecisionVector | None = None,
    refractory: RefractoryState | None = None,
) -> WorkspaceSelectionResult:
    """Select winners with ignition threshold + refractory + precision weights.

    Greedy iterative competition (same algorithm as legacy) but every
    score is composed from per-channel contributions weighted by `precision`,
    redundancy-penalized, and temperature-divided. The top score is
    compared against an effective ignition threshold (base + refractory
    boost); subliminal ticks return empty winners and an empty breakdown,
    allowing the agent to be non-responsive.
    """
    cfg = config or WorkspaceConfig()
    prec = (precision or PrecisionVector.default()).normalized()

    if max_results <= 0 or not candidates:
        return WorkspaceSelectionResult(
            winners=[],
            ignited=False,
            breakdown=[],
            new_refractory=refractory.decay() if refractory else None,
        )

    effective_threshold = cfg.ignition_threshold
    if refractory is not None and refractory.is_active():
        effective_threshold += cfg.refractory_boost

    temp = max(0.1, min(2.0, temperature))
    selected_pairs: list[tuple[WorkspaceCandidate, float]] = []
    selected_breakdowns: list[ScoreBreakdown] = []
    chosen_memories: list[Memory] = []
    remaining = candidates.copy()

    while remaining and len(selected_pairs) < max_results:
        scored: list[tuple[WorkspaceCandidate, float, ScoreBreakdown]] = []
        for cand in remaining:
            penalty = _redundancy_penalty(cand.memory, chosen_memories)
            r_c = prec.relevance * cand.relevance
            n_c = prec.novelty * cand.novelty
            pe_c = prec.prediction_error * cand.prediction_error
            e_c = prec.emotion * cand.emotion_boost
            pen_c = 0.25 * penalty
            total = (r_c + n_c + pe_c + e_c - pen_c) / temp
            breakdown = ScoreBreakdown(
                memory_id=cand.memory.id,
                relevance_contribution=r_c / temp,
                novelty_contribution=n_c / temp,
                prediction_error_contribution=pe_c / temp,
                emotion_contribution=e_c / temp,
                redundancy_penalty=pen_c / temp,
                total=total,
            )
            scored.append((cand, total, breakdown))

        scored.sort(key=lambda item: item[1], reverse=True)
        best_cand, best_score, best_breakdown = scored[0]
        selected_pairs.append((best_cand, best_score))
        selected_breakdowns.append(best_breakdown)
        chosen_memories.append(best_cand.memory)
        remaining = [c for c in remaining if c.memory.id != best_cand.memory.id]

    top_score = selected_pairs[0][1] if selected_pairs else 0.0
    ignited = top_score >= effective_threshold

    if ignited:
        winners = selected_pairs
        breakdown_out = selected_breakdowns
        new_refractory: RefractoryState | None = RefractoryState(
            remaining_ticks=cfg.refractory_ticks
        )
    else:
        winners = []
        breakdown_out = []
        new_refractory = refractory.decay() if refractory else None

    return WorkspaceSelectionResult(
        winners=winners,
        ignited=ignited,
        breakdown=breakdown_out,
        new_refractory=new_refractory,
    )


def diversity_score(memories: list[Memory]) -> float:
    """Average pairwise diversity in [0, 1]."""
    if len(memories) <= 1:
        return 0.0

    pair_scores: list[float] = []
    for i, left in enumerate(memories):
        left_tokens = memory_tokens(left)
        for right in memories[i + 1 :]:
            right_tokens = memory_tokens(right)
            union = left_tokens | right_tokens
            if not union:
                pair_scores.append(0.0)
                continue
            overlap = len(left_tokens & right_tokens) / len(union)
            pair_scores.append(1.0 - overlap)

    if not pair_scores:
        return 0.0
    return sum(pair_scores) / len(pair_scores)

