from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any
from .templates import DeclareTemplate, UNARY_TEMPLATES, NEGATIVE_TEMPLATES


@dataclass
class TimeCondition:
    """Metric time constraint between activation and target event."""
    min_seconds: Optional[float] = None   # None = no lower bound
    max_seconds: Optional[float] = None   # None = no upper bound

    def is_bounded(self) -> bool:
        return self.min_seconds is not None or self.max_seconds is not None

    def __repr__(self) -> str:
        lo = self.min_seconds if self.min_seconds is not None else 0
        hi = self.max_seconds if self.max_seconds is not None else "∞"
        return f"[{lo}s, {hi}s]"


@dataclass
class DataCondition:
    """
    A data predicate expressed as a string expression.
    Evaluated against event payload at runtime via eval() or a custom parser.

    For activation_cond:  variables refer to activation event attributes.
                          e.g. "RSBI < 105"  or  "vasopressor_dose <= 0.1"

    For correlation_cond: variables prefixed with A. refer to activation payload,
                          B. refer to target payload.
                          e.g. "A.FiO2 <= 0.4 and B.PEEP <= 5"
    """
    expression: str

    def __repr__(self) -> str:
        return f"DataCondition('{self.expression}')"


@dataclass
class DeclareConstraint:
    # ── Core (control-flow perspective) ──────────────────────────────────────
    template: DeclareTemplate
    activation: str
    target: Optional[str] = None

    # ── Data perspective ──────────────────────────────────────────────────────
    activation_cond: Optional[DataCondition] = None   # predicate on activation payload
    correlation_cond: Optional[DataCondition] = None  # predicate on (activation, target) payloads

    # ── Time perspective ──────────────────────────────────────────────────────
    time_condition: Optional[TimeCondition] = None    # metric time between activation → target

    # ── Metadata ──────────────────────────────────────────────────────────────
    label: Optional[str] = None

    # --- YOUR EXTENSIONS (uncomment when ready) ---
    # priority: Priority = Priority.P2_PROTOCOL

    def __post_init__(self):
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

    # ── Convenience properties ────────────────────────────────────────────────
    @property
    def is_negative(self) -> bool:
        return self.template in NEGATIVE_TEMPLATES

    @property
    def has_time_constraint(self) -> bool:
        return self.time_condition is not None and self.time_condition.is_bounded()

    @property
    def has_data_constraint(self) -> bool:
        return self.activation_cond is not None or self.correlation_cond is not None

    @property
    def is_multi_perspective(self) -> bool:
        return self.has_time_constraint or self.has_data_constraint

    def __repr__(self) -> str:
        parts = [f"template={self.template.value}", f"activation={self.activation}"]
        if self.target:
            parts.append(f"target={self.target}")
        if self.activation_cond:
            parts.append(f"act_cond={self.activation_cond}")
        if self.correlation_cond:
            parts.append(f"cor_cond={self.correlation_cond}")
        if self.has_time_constraint:
            parts.append(f"time={self.time_condition}")
        return f"DeclareConstraint({', '.join(parts)})"
