"""ConsciousFrame + TickFrameStore — Phase 2.3 canonical per-tick record.

A ConsciousFrame is the per-tick record of "what was online in the workspace":
which memories won, which desire was dominant, what the attention target was,
whether the tick ignited or was subliminal, and what action (if any) was
committed. Storage-rich, prompt-poor: FKs to existing source tables, no
payload duplication.

Backs the consciousness architecture's Phase 2.3 from the plan-of-record
at ~/.gemini/plans/jazzy-wishing-starfish.md. The frame's
winning_memory_ids[] entries are EpistemicClaim-projectable refs (Phase 1
integration). prediction_error channels {extero, intero, mnemonic} align
with the Phase 2.2 PrecisionVector mapping.

See consciousness-mcp/AGENTS.md for vocabulary discipline.
"""

from __future__ import annotations

import json
import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from social_core.db import SocialDB
from social_core.time import utc_now

Reportability = Literal["mentionable", "background_only", "do_not_surface"]


class PredictionErrorChannels(BaseModel):
    """Per-channel prediction error magnitudes (z-scored or raw).

    Mapping mirrors workspace.py's precision_from_pe_channels:
      extero  — exteroceptive perception PE
      intero  — interoceptive (body/desire) PE
      mnemonic — memory / association PE
    """

    model_config = ConfigDict(extra="forbid")

    extero: float = 0.0
    intero: float = 0.0
    mnemonic: float = 0.0


class ConsciousFrameInput(BaseModel):
    """Payload for recording a tick frame.

    FK-only by design: winning_memory_ids are refs into memory-mcp,
    attention_target_ref is a tool/target name, dominant_desire is a
    desire name, chosen_action_ref is an action-id from the bottleneck.
    The frame never stores memory payloads or rich state — those live
    in their source tables and are joined when needed.
    """

    model_config = ConfigDict(extra="forbid")

    ts: str | None = None
    person_id: str | None = None
    ignited: bool = False
    conflicted: bool = False
    attention_target_ref: str | None = None
    dominant_desire: str | None = None
    winning_memory_ids: list[str] = Field(default_factory=list)
    prediction_error: PredictionErrorChannels = Field(
        default_factory=PredictionErrorChannels
    )
    affect_summary: str | None = None
    chosen_action_ref: str | None = None
    reportability: Reportability = "mentionable"


class ConsciousFrame(BaseModel):
    """Persisted tick frame, returned by TickFrameStore."""

    model_config = ConfigDict(extra="ignore")

    tick_id: str
    ts: str
    person_id: str | None = None
    ignited: bool = False
    conflicted: bool = False
    attention_target_ref: str | None = None
    dominant_desire: str | None = None
    winning_memory_ids: list[str] = Field(default_factory=list)
    prediction_error: PredictionErrorChannels = Field(
        default_factory=PredictionErrorChannels
    )
    affect_summary: str | None = None
    chosen_action_ref: str | None = None
    reportability: Reportability = "mentionable"
    created_at: str


class TickFrameStore:
    """SQLite-backed store for ConsciousFrame rows over tick_frames table."""

    def __init__(self, db: SocialDB) -> None:
        self._db = db

    def record(self, payload: ConsciousFrameInput) -> ConsciousFrame:
        tick_id = f"tick_{secrets.token_urlsafe(12)}"
        ts = payload.ts or utc_now()
        created_at = utc_now()
        winning_json = json.dumps(payload.winning_memory_ids, ensure_ascii=False)
        pe_json = json.dumps(
            payload.prediction_error.model_dump(), ensure_ascii=False
        )

        self._db.execute(
            """
            INSERT INTO tick_frames(
                tick_id, ts, person_id, ignited, conflicted,
                attention_target_ref, dominant_desire,
                winning_memory_ids_json, prediction_error_json,
                affect_summary, chosen_action_ref, reportability, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tick_id,
                ts,
                payload.person_id,
                1 if payload.ignited else 0,
                1 if payload.conflicted else 0,
                payload.attention_target_ref,
                payload.dominant_desire,
                winning_json,
                pe_json,
                payload.affect_summary,
                payload.chosen_action_ref,
                payload.reportability,
                created_at,
            ),
        )

        return ConsciousFrame(
            tick_id=tick_id,
            ts=ts,
            person_id=payload.person_id,
            ignited=payload.ignited,
            conflicted=payload.conflicted,
            attention_target_ref=payload.attention_target_ref,
            dominant_desire=payload.dominant_desire,
            winning_memory_ids=payload.winning_memory_ids,
            prediction_error=payload.prediction_error,
            affect_summary=payload.affect_summary,
            chosen_action_ref=payload.chosen_action_ref,
            reportability=payload.reportability,
            created_at=created_at,
        )

    def get_by_tick_id(self, tick_id: str) -> ConsciousFrame | None:
        row = self._db.fetchone(
            """
            SELECT tick_id, ts, person_id, ignited, conflicted,
                   attention_target_ref, dominant_desire,
                   winning_memory_ids_json, prediction_error_json,
                   affect_summary, chosen_action_ref, reportability, created_at
            FROM tick_frames WHERE tick_id = ?
            """,
            (tick_id,),
        )
        if row is None:
            return None
        return self._row_to_frame(row)

    def query(
        self,
        *,
        since: str | None = None,
        reportability: Reportability | None = None,
        person_id: str | None = None,
        ignited_only: bool = False,
        limit: int = 50,
    ) -> list[ConsciousFrame]:
        clauses: list[str] = []
        params: list[object] = []
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)
        if reportability is not None:
            clauses.append("reportability = ?")
            params.append(reportability)
        if person_id is not None:
            clauses.append("person_id = ?")
            params.append(person_id)
        if ignited_only:
            clauses.append("ignited = 1")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        rows = self._db.fetchall(
            f"""
            SELECT tick_id, ts, person_id, ignited, conflicted,
                   attention_target_ref, dominant_desire,
                   winning_memory_ids_json, prediction_error_json,
                   affect_summary, chosen_action_ref, reportability, created_at
            FROM tick_frames
            {where}
            ORDER BY ts DESC, created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [self._row_to_frame(row) for row in rows]

    @staticmethod
    def _row_to_frame(row) -> ConsciousFrame:
        try:
            winning_ids = json.loads(row["winning_memory_ids_json"] or "[]")
        except json.JSONDecodeError:
            winning_ids = []
        try:
            pe_raw = json.loads(row["prediction_error_json"] or "{}")
        except json.JSONDecodeError:
            pe_raw = {}
        return ConsciousFrame(
            tick_id=row["tick_id"],
            ts=row["ts"],
            person_id=row["person_id"],
            ignited=bool(row["ignited"]),
            conflicted=bool(row["conflicted"]),
            attention_target_ref=row["attention_target_ref"],
            dominant_desire=row["dominant_desire"],
            winning_memory_ids=winning_ids,
            prediction_error=PredictionErrorChannels(**pe_raw),
            affect_summary=row["affect_summary"],
            chosen_action_ref=row["chosen_action_ref"],
            reportability=row["reportability"],
            created_at=row["created_at"],
        )
