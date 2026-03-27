from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DeclareTemplate(Enum):
    # Existence (unary)
    EXISTENCE = "Existence"  # Activity must occur at least once.
    ABSENCE = "Absence"  # Activity must never occur.
    EXACTLY = "Exactly"  # Activity must occur an exact number of times.
    INIT = "Init"  # The first event in the trace must be this activity.

    # Positive binary
    RESPONDED_EXISTENCE = "Responded Existence"  # If A occurs, B must occur (order not required).
    RESPONSE = "Response"  # If A occurs, B must occur later.
    ALTERNATE_RESPONSE = "Alternate Response"  # Each A is followed by one B before another A.
    CHAIN_RESPONSE = "Chain Response"  # Each A is immediately followed by B.

    PRECEDENCE = "Precedence"  # B can occur only if A occurred earlier.
    ALTERNATE_PRECEDENCE = "Alternate Precedence"  # Each B must have one unmatched earlier A.
    CHAIN_PRECEDENCE = "Chain Precedence"  # Each B must be immediately preceded by A.

    CO_EXISTENCE = "Co-Existence"  # A and B must either both occur or both be absent.

    SUCCESSION = "Succession"  # Combines precedence and response between A and B.
    ALTERNATE_SUCCESSION = "Alternate Succession"  # Alternate precedence + alternate response.
    CHAIN_SUCCESSION = "Chain Succession"  # Chain precedence + chain response.

    # Negative binary
    NOT_RESPONDED_EXISTENCE = "Not Responded Existence"  # If A occurs, B must not occur at all.
    NOT_RESPONSE = "Not Response"  # If A occurs, B must not occur later.
    NOT_CHAIN_RESPONSE = "Not Chain Response"  # A must not be immediately followed by B.
    NOT_PRECEDENCE = "Not Precedence"  # B must not have A before it.
    NOT_CHAIN_PRECEDENCE = "Not Chain Precedence"  # B must not be immediately preceded by A.
    NOT_CO_EXISTENCE = "Not Co-Existence"  # A and B cannot both occur in one trace.
    NOT_SUCCESSION = "Not Succession"  # A->B succession is forbidden.


UNARY_TEMPLATES = {
    DeclareTemplate.EXISTENCE,
    DeclareTemplate.ABSENCE,
    DeclareTemplate.EXACTLY,
    DeclareTemplate.INIT,
}

NEGATIVE_TEMPLATES = {
    DeclareTemplate.ABSENCE,
    DeclareTemplate.NOT_RESPONDED_EXISTENCE,
    DeclareTemplate.NOT_RESPONSE,
    DeclareTemplate.NOT_CHAIN_RESPONSE,
    DeclareTemplate.NOT_PRECEDENCE,
    DeclareTemplate.NOT_CHAIN_PRECEDENCE,
    DeclareTemplate.NOT_CO_EXISTENCE,
    DeclareTemplate.NOT_SUCCESSION,
}


@dataclass
class TimeCondition:
    min_seconds: Optional[float] = None
    max_seconds: Optional[float] = None

    def is_bounded(self) -> bool:
        return self.min_seconds is not None or self.max_seconds is not None


@dataclass
class DataCondition:
    expression: str


@dataclass
class DeclareConstraint:
    template: DeclareTemplate
    activation: str
    target: Optional[str] = None
    activation_cond: Optional[DataCondition] = None
    correlation_cond: Optional[DataCondition] = None
    time_condition: Optional[TimeCondition] = None
    label: Optional[str] = None

    def __post_init__(self) -> None:
        is_unary = self.template in UNARY_TEMPLATES
        if not is_unary and self.target is None:
            raise ValueError(
                f"Template '{self.template.value}' is binary and requires a target activity."
            )
        if is_unary and self.target is not None:
            raise ValueError(
                f"Template '{self.template.value}' is unary and must not have a target."
            )
        if self.label is None:
            if self.target:
                self.label = f"{self.template.value}[{self.activation}, {self.target}]"
            else:
                self.label = f"{self.template.value}[{self.activation}]"


@dataclass
class DeclareModel:
    name: str
    constraints: list[DeclareConstraint] = field(default_factory=list)

    def add(self, constraint: DeclareConstraint) -> None:
        self.constraints.append(constraint)
