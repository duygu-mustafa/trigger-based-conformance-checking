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


@dataclass
class TraceResult:
    case_id: str
    constraint_results: list[ConstraintResult] = field(default_factory=list)

    @property
    def is_conformant(self) -> bool:
        return all(r.outcome != ConformanceOutcome.VIOLATED for r in self.constraint_results)
