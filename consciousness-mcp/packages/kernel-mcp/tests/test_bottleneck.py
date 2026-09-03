"""Tests for ActionBottleneck — one external action per tick (Phase 2.3).

The bottleneck is THE load-bearing piece per critique B finding 1 of the
plan-of-record: LLM verbal output becomes a first-class gated action,
side-channeling is closed. Second-action attempts in the same tick_id are
deferred and recorded as counterfactuals with source='attention_lost_bid'.
"""

from __future__ import annotations

import pytest

from kernel_mcp.bottleneck import (
    ActionBottleneck,
    CommitActionResult,
)
from kernel_mcp.counterfactual import CounterfactualStore
from kernel_mcp.frame import (
    ConsciousFrameInput,
    TickFrameStore,
)


@pytest.fixture
def bottleneck(social_db):
    frames = TickFrameStore(social_db)
    cfs = CounterfactualStore(social_db)
    return ActionBottleneck(
        db=social_db,
        frame_store=frames,
        counterfactual_store=cfs,
    )


@pytest.fixture
def fresh_tick(social_db):
    frames = TickFrameStore(social_db)
    frame = frames.record(ConsciousFrameInput(person_id="kouta", ignited=True))
    return frame.tick_id


class TestFirstCommit:
    def test_first_commit_succeeds(self, bottleneck, fresh_tick) -> None:
        result = bottleneck.commit_action(
            tick_id=fresh_tick, action_ref="say_hello"
        )
        assert isinstance(result, CommitActionResult)
        assert result.ok is True
        assert result.deferred is False
        assert result.tick_id == fresh_tick
        assert result.action_ref == "say_hello"
        assert result.counterfactual_id is None

    def test_first_commit_persists_chosen_action_ref(
        self, bottleneck, fresh_tick, social_db
    ) -> None:
        bottleneck.commit_action(tick_id=fresh_tick, action_ref="say_hello")
        row = social_db.fetchone(
            "SELECT chosen_action_ref FROM tick_frames WHERE tick_id = ?",
            (fresh_tick,),
        )
        assert row["chosen_action_ref"] == "say_hello"


class TestSecondCommit:
    def test_second_commit_is_deferred(self, bottleneck, fresh_tick) -> None:
        bottleneck.commit_action(tick_id=fresh_tick, action_ref="first_action")
        result = bottleneck.commit_action(
            tick_id=fresh_tick, action_ref="second_action"
        )
        assert result.ok is False
        assert result.deferred is True
        assert result.action_ref == "second_action"
        assert result.counterfactual_id is not None

    def test_second_commit_writes_counterfactual(
        self, bottleneck, fresh_tick, social_db
    ) -> None:
        bottleneck.commit_action(tick_id=fresh_tick, action_ref="first_action")
        bottleneck.commit_action(tick_id=fresh_tick, action_ref="second_action")
        row = social_db.fetchone(
            "SELECT * FROM counterfactuals WHERE tick_id = ? AND rejected_action = ?",
            (fresh_tick, "second_action"),
        )
        assert row is not None
        assert row["source"] == "attention_lost_bid"
        assert row["evidence_type"] == "remembered"
        assert row["chosen_action_ref"] == "first_action"

    def test_second_commit_does_not_overwrite_chosen_action(
        self, bottleneck, fresh_tick, social_db
    ) -> None:
        bottleneck.commit_action(tick_id=fresh_tick, action_ref="first_action")
        bottleneck.commit_action(tick_id=fresh_tick, action_ref="second_action")
        row = social_db.fetchone(
            "SELECT chosen_action_ref FROM tick_frames WHERE tick_id = ?",
            (fresh_tick,),
        )
        assert row["chosen_action_ref"] == "first_action"

    def test_third_commit_also_deferred(
        self, bottleneck, fresh_tick, social_db
    ) -> None:
        bottleneck.commit_action(tick_id=fresh_tick, action_ref="first")
        r2 = bottleneck.commit_action(tick_id=fresh_tick, action_ref="second")
        r3 = bottleneck.commit_action(tick_id=fresh_tick, action_ref="third")
        assert r2.deferred is True
        assert r3.deferred is True
        # Both deferred actions get distinct counterfactual ids.
        assert r2.counterfactual_id != r3.counterfactual_id
        deferred_cfs = social_db.fetchall(
            "SELECT rejected_action FROM counterfactuals WHERE tick_id = ?",
            (fresh_tick,),
        )
        assert {row["rejected_action"] for row in deferred_cfs} == {
            "second",
            "third",
        }


class TestPayload:
    def test_action_payload_persisted_in_counterfactual(
        self, bottleneck, fresh_tick, social_db
    ) -> None:
        bottleneck.commit_action(tick_id=fresh_tick, action_ref="first")
        bottleneck.commit_action(
            tick_id=fresh_tick,
            action_ref="second",
            action_payload={"channel": "tts", "text": "hey"},
        )
        row = social_db.fetchone(
            "SELECT rejected_action_payload_json FROM counterfactuals WHERE tick_id = ?",
            (fresh_tick,),
        )
        assert '"channel"' in row["rejected_action_payload_json"]

    def test_person_id_propagated_to_counterfactual(
        self, bottleneck, fresh_tick, social_db
    ) -> None:
        bottleneck.commit_action(tick_id=fresh_tick, action_ref="first")
        bottleneck.commit_action(
            tick_id=fresh_tick,
            action_ref="second",
            person_id="kouta",
        )
        row = social_db.fetchone(
            "SELECT person_id FROM counterfactuals WHERE tick_id = ?",
            (fresh_tick,),
        )
        assert row["person_id"] == "kouta"


class TestErrors:
    def test_commit_to_nonexistent_tick_raises(self, bottleneck) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            bottleneck.commit_action(
                tick_id="tick_nonexistent_xyz", action_ref="say_hello"
            )


class TestIsolation:
    def test_separate_ticks_do_not_interfere(self, social_db, bottleneck) -> None:
        frames = TickFrameStore(social_db)
        tick_a = frames.record(ConsciousFrameInput()).tick_id
        tick_b = frames.record(ConsciousFrameInput()).tick_id

        result_a = bottleneck.commit_action(tick_id=tick_a, action_ref="action_a")
        result_b = bottleneck.commit_action(tick_id=tick_b, action_ref="action_b")

        assert result_a.ok is True
        assert result_b.ok is True
        assert result_a.deferred is False
        assert result_b.deferred is False
