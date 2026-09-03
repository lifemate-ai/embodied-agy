"""CounterfactualStore — typed records of rejected alternatives.

A counterfactual entry is a record of "the action the agent chose NOT to take,
and why". Phase 2.1's first persistent surface. Reuses Phase 1's EvidenceType
enum so each counterfactual can round-trip through an EpistemicClaim — the
agent's epistemic discipline (observed / inferred / remembered / heard /
assumed) extends to its decision traces.

See consciousness-mcp/AGENTS.md for the vocabulary discipline this module
follows. All language here is functional, not phenomenal.
"""

from __future__ import annotations

import json
import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from social_core.db import SocialDB
from social_core.models import EpistemicClaim, EvidenceType
from social_core.time import utc_now

COUNTERFACTUAL_SOURCES = (
    "boundary_deny",
    "attention_lost_bid",
    "deliberate_choice",
    "policy",
    "ignition_failed",
)

CounterfactualSource = Literal[
    "boundary_deny",
    "attention_lost_bid",
    "deliberate_choice",
    "policy",
    "ignition_failed",
]


class CounterfactualInput(BaseModel):
    """Payload for recording a rejected alternative.

    `source` names the gate that produced the rejection. `evidence_type`
    declares how the agent knows the rejected action was inferior (defaults
    to None at the schema, surface-resolves to 'inferred' in EpistemicClaim
    projection — see CounterfactualRecord.to_epistemic_claim).
    """

    model_config = ConfigDict(extra="forbid")

    tick_id: str | None = None
    person_id: str | None = None
    chosen_action_ref: str | None = None
    rejected_action: str = Field(min_length=1)
    rejected_action_payload: dict = Field(default_factory=dict)
    reason: str | None = None
    source: CounterfactualSource
    expected_outcome: str | None = None
    evidence_type: EvidenceType | None = None
    importance: int = Field(default=3, ge=1, le=5)
    ts: str | None = None


class CounterfactualRecord(BaseModel):
    """Persisted counterfactual row, returned by CounterfactualStore.record/query."""

    model_config = ConfigDict(extra="ignore")

    counterfactual_id: str
    tick_id: str | None = None
    ts: str
    person_id: str | None = None
    chosen_action_ref: str | None = None
    rejected_action: str
    rejected_action_payload: dict = Field(default_factory=dict)
    reason: str | None = None
    source: CounterfactualSource
    expected_outcome: str | None = None
    evidence_type: EvidenceType | None = None
    importance: int = Field(default=3, ge=1, le=5)
    created_at: str

    def to_epistemic_claim(self) -> EpistemicClaim:
        """Project this counterfactual as an EpistemicClaim (Phase 1 type).

        Default evidence_type is 'inferred' (we inferred the chosen action
        was preferable). When the row carries an explicit evidence_type
        (e.g. 'remembered' for a policy-driven deny), it is honored.
        Confidence is conservative: 0.6 for inferred, 0.9 for non-inferred
        (an observed/remembered rejection is more certain than an
        inferred-preferable one).
        """
        et = self.evidence_type or "inferred"
        content = (
            f"rejected action '{self.rejected_action}' "
            f"({self.reason or self.source})"
        )
        confidence = 0.6 if et == "inferred" else 0.9
        return EpistemicClaim(
            content=content,
            evidence_type=et,
            source=self.source,
            confidence=confidence,
        )


class CounterfactualStore:
    """SQLite-backed store for CounterfactualRecord rows."""

    def __init__(self, db: SocialDB) -> None:
        self._db = db

    def record(self, payload: CounterfactualInput) -> CounterfactualRecord:
        ts = payload.ts or utc_now()
        created_at = utc_now()
        counterfactual_id = f"cf_{secrets.token_urlsafe(12)}"
        payload_json = json.dumps(payload.rejected_action_payload, ensure_ascii=False)

        self._db.execute(
            """
            INSERT INTO counterfactuals(
                counterfactual_id, tick_id, ts, person_id,
                chosen_action_ref, rejected_action, rejected_action_payload_json,
                reason, source, expected_outcome, evidence_type, importance,
                created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                counterfactual_id,
                payload.tick_id,
                ts,
                payload.person_id,
                payload.chosen_action_ref,
                payload.rejected_action,
                payload_json,
                payload.reason,
                payload.source,
                payload.expected_outcome,
                payload.evidence_type,
                payload.importance,
                created_at,
            ),
        )

        return CounterfactualRecord(
            counterfactual_id=counterfactual_id,
            tick_id=payload.tick_id,
            ts=ts,
            person_id=payload.person_id,
            chosen_action_ref=payload.chosen_action_ref,
            rejected_action=payload.rejected_action,
            rejected_action_payload=payload.rejected_action_payload,
            reason=payload.reason,
            source=payload.source,
            expected_outcome=payload.expected_outcome,
            evidence_type=payload.evidence_type,
            importance=payload.importance,
            created_at=created_at,
        )

    def query(
        self,
        *,
        since: str | None = None,
        source: CounterfactualSource | None = None,
        tick_id: str | None = None,
        person_id: str | None = None,
        limit: int = 50,
    ) -> list[CounterfactualRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if tick_id is not None:
            clauses.append("tick_id = ?")
            params.append(tick_id)
        if person_id is not None:
            clauses.append("person_id = ?")
            params.append(person_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        rows = self._db.fetchall(
            f"""
            SELECT counterfactual_id, tick_id, ts, person_id,
                   chosen_action_ref, rejected_action, rejected_action_payload_json,
                   reason, source, expected_outcome, evidence_type, importance,
                   created_at
            FROM counterfactuals
            {where}
            ORDER BY ts DESC, created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row) -> CounterfactualRecord:
        payload_raw = row["rejected_action_payload_json"] or "{}"
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = {}
        return CounterfactualRecord(
            counterfactual_id=row["counterfactual_id"],
            tick_id=row["tick_id"],
            ts=row["ts"],
            person_id=row["person_id"],
            chosen_action_ref=row["chosen_action_ref"],
            rejected_action=row["rejected_action"],
            rejected_action_payload=payload,
            reason=row["reason"],
            source=row["source"],
            expected_outcome=row["expected_outcome"],
            evidence_type=row["evidence_type"],
            importance=row["importance"],
            created_at=row["created_at"],
        )
