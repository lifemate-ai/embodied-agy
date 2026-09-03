"""Tests for extract_counterfactuals_from_plan — pure function.

The plan-of-record is explicit that we do NOT touch plan.py in Phase 2.1.
Instead a pure extractor takes (ResponsePlan, InteractionContext) and emits
CounterfactualInput[]. The caller (e.g. interaction-orchestrator-mcp or the
sleep job) decides when to persist them through CounterfactualStore.
"""

from __future__ import annotations

from interaction_orchestrator_mcp.schemas import (
    AgentStateSummary,
    BoundaryHint,
    InitiativeHint,
    InteractionContext,
    MemoryUseHint,
    PrimaryMove,
    ResponseContract,
    ResponsePlan,
    ToneHint,
    VoiceHint,
)

from kernel_mcp.auto_emit import (
    extract_counterfactuals_from_plan,
)


def _minimal_ctx(person_id: str | None = "kouta") -> InteractionContext:
    return InteractionContext(
        ts="2026-06-13T03:00:00Z",
        local_time="2026-06-13T12:00:00+09:00",
        timezone="Asia/Tokyo",
        person_id=person_id,
        agent_state=AgentStateSummary(ts="2026-06-13T03:00:00Z"),
        response_contract=ResponseContract(),
        prompt_summary="test",
        compact_prompt_block="test",
    )


def _plan(
    primary_move: PrimaryMove = "answer_directly",
    *,
    quiet_hours_active: bool = False,
    must_avoid: list[str] | None = None,
) -> ResponsePlan:
    return ResponsePlan(
        primary_move=primary_move,
        why_this_move="test reason",
        tone=ToneHint(),
        memory_use=MemoryUseHint(),
        initiative=InitiativeHint(),
        boundary=BoundaryHint(quiet_hours_active=quiet_hours_active),
        voice=VoiceHint(),
        must_include=[],
        must_avoid=must_avoid or [],
    )


class TestOpposingMove:
    def test_answer_directly_rejects_stay_silent(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("answer_directly"), _minimal_ctx()
        )
        assert len(results) == 1
        assert results[0].rejected_action == "stay_silent"
        assert results[0].chosen_action_ref == "answer_directly"

    def test_stay_silent_rejects_answer_directly(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("stay_silent"), _minimal_ctx()
        )
        assert len(results) == 1
        assert results[0].rejected_action == "answer_directly"

    def test_write_private_reflection_rejects_speak_to_user(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("write_private_reflection"), _minimal_ctx()
        )
        assert len(results) == 1
        assert results[0].rejected_action == "speak_to_user"

    def test_defer_rejects_answer_directly(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("defer"), _minimal_ctx()
        )
        assert len(results) == 1
        assert results[0].rejected_action == "answer_directly"


class TestSourceClassification:
    def test_default_source_is_deliberate_choice(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("answer_directly"), _minimal_ctx()
        )
        assert results[0].source == "deliberate_choice"

    def test_quiet_hours_upgrades_speech_rejection_to_boundary_deny(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("write_private_reflection", quiet_hours_active=True),
            _minimal_ctx(),
        )
        assert results[0].source == "boundary_deny"

    def test_quiet_hours_upgrades_stay_silent_speech_rejection(self) -> None:
        # stay_silent rejects "answer_directly"; if quiet hours, source should
        # be boundary_deny.
        results = extract_counterfactuals_from_plan(
            _plan("stay_silent", quiet_hours_active=True),
            _minimal_ctx(),
        )
        assert results[0].source == "boundary_deny"

    def test_quiet_hours_does_not_upgrade_internal_only_rejection(self) -> None:
        # answer_with_empathy rejects answer_directly (also speech). Use a
        # case where neither side is louder: ask_one_clarifying_question
        # rejects answer_directly — both verbal. quiet_hours should still
        # upgrade (rejection of "answer_directly" = rejection of verbal output).
        # But for "act_autonomously rejects quietly_prepare", neither is
        # verbal; no upgrade.
        results = extract_counterfactuals_from_plan(
            _plan("act_autonomously", quiet_hours_active=True),
            _minimal_ctx(),
        )
        # The rejected action ("quietly_prepare") is not louder; source
        # stays deliberate_choice.
        assert results[0].source == "deliberate_choice"


class TestEvidenceType:
    def test_inferred_when_deliberate_choice(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("answer_directly"), _minimal_ctx()
        )
        assert results[0].evidence_type == "inferred"

    def test_remembered_when_boundary_deny(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("write_private_reflection", quiet_hours_active=True),
            _minimal_ctx(),
        )
        assert results[0].evidence_type == "remembered"


class TestMustAvoidOptIn:
    def test_must_avoid_not_emitted_by_default(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("answer_directly", must_avoid=["generic reassurance", "diagnosis"]),
            _minimal_ctx(),
        )
        # Only the opposing-move counterfactual emitted.
        assert len(results) == 1

    def test_must_avoid_emitted_when_opted_in(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("answer_directly", must_avoid=["generic reassurance", "diagnosis"]),
            _minimal_ctx(),
            include_must_avoid=True,
        )
        assert len(results) == 3  # 1 opposing + 2 must_avoid
        policy_results = [r for r in results if r.source == "policy"]
        assert len(policy_results) == 2
        assert {r.rejected_action for r in policy_results} == {
            "generic reassurance",
            "diagnosis",
        }


class TestContextPassthrough:
    def test_person_id_from_context(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("answer_directly"), _minimal_ctx(person_id="someone_else")
        )
        assert results[0].person_id == "someone_else"

    def test_tick_id_passed_through(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("answer_directly"),
            _minimal_ctx(),
            tick_id="tick_abc123",
        )
        assert results[0].tick_id == "tick_abc123"

    def test_reason_from_why_this_move(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("answer_directly"), _minimal_ctx()
        )
        assert results[0].reason == "test reason"

    def test_payload_includes_chosen_move_and_why(self) -> None:
        results = extract_counterfactuals_from_plan(
            _plan("answer_directly"), _minimal_ctx()
        )
        payload = results[0].rejected_action_payload
        assert payload["primary_move_chosen"] == "answer_directly"
        assert payload["why_this_move"] == "test reason"
