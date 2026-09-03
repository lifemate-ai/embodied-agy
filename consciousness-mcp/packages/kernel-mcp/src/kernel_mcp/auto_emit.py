"""extract_counterfactuals_from_plan — pure function.

Given a ResponsePlan and the InteractionContext it was computed from,
produce CounterfactualInputs describing the alternative(s) the plan
rejected. Caller decides when (or whether) to persist them through
CounterfactualStore.

plan.py is intentionally NOT touched in Phase 2.1; the extractor lives
in consciousness-mcp so the orchestrator stays a pure function. The
caller pattern is:

    plan = plan_response(ctx, user_text=user_text)
    cfs = extract_counterfactuals_from_plan(plan, ctx, tick_id=tick_id)
    for cf in cfs:
        store.record(cf)

See consciousness-mcp/AGENTS.md for vocabulary discipline.
"""

from __future__ import annotations

from interaction_orchestrator_mcp.schemas import (
    InteractionContext,
    PrimaryMove,
    ResponsePlan,
)

from kernel_mcp.counterfactual import (
    CounterfactualInput,
    CounterfactualSource,
)

_OPPOSING_MOVE: dict[PrimaryMove, tuple[str, CounterfactualSource]] = {
    "answer_directly": ("stay_silent", "deliberate_choice"),
    "answer_with_empathy": ("answer_directly", "deliberate_choice"),
    "ask_one_clarifying_question": ("answer_directly", "deliberate_choice"),
    "quietly_prepare": ("act_autonomously", "deliberate_choice"),
    "defer": ("answer_directly", "deliberate_choice"),
    "stay_silent": ("answer_directly", "deliberate_choice"),
    "act_autonomously": ("quietly_prepare", "deliberate_choice"),
    "write_private_reflection": ("speak_to_user", "deliberate_choice"),
    "compose_letter": ("speak_to_user_now", "deliberate_choice"),
    "post_socially_after_review": ("post_unreviewed", "policy"),
}

# Rejections of these actions during quiet hours upgrade from
# deliberate_choice → boundary_deny. They are all forms of audible /
# external communication that policy actively suppresses in quiet hours.
_VERBAL_REJECTIONS = frozenset({
    "answer_directly",
    "speak_to_user",
    "speak_to_user_now",
})


def extract_counterfactuals_from_plan(
    plan: ResponsePlan,
    ctx: InteractionContext,
    *,
    tick_id: str | None = None,
    include_must_avoid: bool = False,
) -> list[CounterfactualInput]:
    """Build CounterfactualInput list from plan + context (pure function).

    Always emits at most one record for the opposing primary_move (if the
    chosen move has a documented opposite in the table above). Optionally
    emits one record per must_avoid item under source='policy'.
    """
    results: list[CounterfactualInput] = []
    chosen = plan.primary_move
    opposing = _OPPOSING_MOVE.get(chosen)
    if opposing is not None:
        rejected_action, default_source = opposing
        source = default_source
        if (
            plan.boundary.quiet_hours_active
            and rejected_action in _VERBAL_REJECTIONS
        ):
            source = "boundary_deny"
        results.append(
            CounterfactualInput(
                tick_id=tick_id,
                person_id=ctx.person_id,
                chosen_action_ref=chosen,
                rejected_action=rejected_action,
                rejected_action_payload={
                    "primary_move_chosen": chosen,
                    "why_this_move": plan.why_this_move,
                },
                reason=plan.why_this_move,
                source=source,
                evidence_type=(
                    "remembered" if source == "boundary_deny" else "inferred"
                ),
            )
        )

    if include_must_avoid:
        for avoid_item in plan.must_avoid:
            results.append(
                CounterfactualInput(
                    tick_id=tick_id,
                    person_id=ctx.person_id,
                    chosen_action_ref=chosen,
                    rejected_action=avoid_item[:200],
                    reason=plan.why_this_move,
                    source="policy",
                    evidence_type="remembered",
                )
            )

    return results
