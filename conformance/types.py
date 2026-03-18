from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DeclareTemplate(Enum):
    # Existence (unary)
    EXISTENCE = "Existence"
    ABSENCE = "Absence"
    EXACTLY = "Exactly"
    INIT = "Init"

    # Positive binary
    RESPONDED_EXISTENCE = "Responded Existence"
    RESPONSE = "Response"
    ALTERNATE_RESPONSE = "Alternate Response"
    CHAIN_RESPONSE = "Chain Response"

    PRECEDENCE = "Precedence"
    ALTERNATE_PRECEDENCE = "Alternate Precedence"
    CHAIN_PRECEDENCE = "Chain Precedence"

    CO_EXISTENCE = "Co-Existence"

    SUCCESSION = "Succession"
    ALTERNATE_SUCCESSION = "Alternate Succession"
    CHAIN_SUCCESSION = "Chain Succession"

    # Negative binary
    NOT_RESPONDED_EXISTENCE = "Not Responded Existence"
    NOT_RESPONSE = "Not Response"
    NOT_CHAIN_RESPONSE = "Not Chain Response"
    NOT_PRECEDENCE = "Not Precedence"
    NOT_CHAIN_PRECEDENCE = "Not Chain Precedence"
    NOT_CO_EXISTENCE = "Not Co-Existence"
    NOT_SUCCESSION = "Not Succession"


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
