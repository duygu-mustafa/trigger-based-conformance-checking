from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ConformanceOutcome(Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    VACUOUS = "vacuous"
    NOT_EVALUATED = "not_evaluated"


@dataclass
class ConstraintResult:
    case_id: str
    constraint_id: str
    outcome: ConformanceOutcome
    num_activations: int = 0
    num_fulfilled: int = 0
    num_violated: int = 0
    activation_ts: Optional[str] = None
    target_ts: Optional[str] = None
    violation_reason: Optional[str] = None
    violation_deltas: dict[str, float] = field(default_factory=dict)
    satisfaction_deltas: dict[str, float] = field(default_factory=dict)
    delay_seconds: Optional[float] = None
    # Why an activation failed, counted over the activations of this constraint.
    # "absent": no target event at all before the activation.
    # "stale": a target event exists but lies outside the time condition.
    # "no_payload" / "partial_payload": the correlation condition is false because
    #   all / some of the items it reads are missing (a documentation gap).
    # "unmet": the correlation condition is false on readings that are all present.
    # Only recorded for the precedence family.
    violation_causes: dict[str, int] = field(default_factory=dict)
    # Values the correlation condition read at the first activation whose most
    # specific failure cause was "unmet". Empty otherwise.
    violation_values: dict[str, float] = field(default_factory=dict)


@dataclass
class TraceResult:
    case_id: str
    constraint_results: list[ConstraintResult] = field(default_factory=list)

    @property
    def is_conformant(self) -> bool:
        return all(r.outcome != ConformanceOutcome.VIOLATED for r in self.constraint_results)
