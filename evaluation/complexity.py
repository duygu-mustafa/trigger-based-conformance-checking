"""Structural complexity measure for Declare constraints.

Assigns each ``DeclareConstraint`` a composite score

    C(r) = w_template + n_clauses + n_attributes + t_time

whose components mirror the cost structure of ``conformance/checker.py``:

* ``w_template`` — template family weight, graded by how the evaluator scans
  the trace: unary templates need a single pass over the activation rows (1);
  unordered binary templates additionally scan the target rows (2); ordered
  binary templates run the activation x target candidate loops (3); alternate/
  chain variants also inspect the events between activation and target (4).
* ``n_clauses`` — number of atomic predicates across the activation and
  correlation conditions. Every predicate is evaluated per activation (and per
  candidate target for correlation conditions).
* ``n_attributes`` — number of distinct event attributes referenced as
  ``items[...]``. Each attribute forces a lookup in the per-evaluation item
  snapshot (``checker._build_items_snapshot``).
* ``t_time`` — 1 if a time window is attached (per-candidate timestamp
  arithmetic in ``checker._within_time_window``), else 0.

The score is deliberately unweighted beyond the template grades: it is a
predictor to be validated empirically (per-rule runtime vs. score), not a cost
model calibrated in advance.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from conformance.types import DeclareConstraint, DeclareTemplate, UNARY_TEMPLATES

# Ordered binary templates: evaluator loops activations and, per activation,
# filters/scans candidate targets by timestamp.
_ORDERED_TEMPLATES = {
    DeclareTemplate.RESPONSE,
    DeclareTemplate.PRECEDENCE,
    DeclareTemplate.SUCCESSION,
    DeclareTemplate.NOT_RESPONSE,
    DeclareTemplate.NOT_PRECEDENCE,
    DeclareTemplate.NOT_SUCCESSION,
}

# Alternate/chain variants: additionally scan events between activation and
# target (intermediate-activation checks / immediate-neighbour checks).
_ALTERNATE_CHAIN_TEMPLATES = {
    DeclareTemplate.ALTERNATE_RESPONSE,
    DeclareTemplate.CHAIN_RESPONSE,
    DeclareTemplate.ALTERNATE_PRECEDENCE,
    DeclareTemplate.CHAIN_PRECEDENCE,
    DeclareTemplate.ALTERNATE_SUCCESSION,
    DeclareTemplate.CHAIN_SUCCESSION,
    DeclareTemplate.NOT_CHAIN_RESPONSE,
    DeclareTemplate.NOT_CHAIN_PRECEDENCE,
    DeclareTemplate.NOT_CHAIN_SUCCESSION,
}

_ITEMS_ATTR_RE = re.compile(r"items\[\s*['\"]([^'\"]+)['\"]\s*\]")


def template_weight(template: DeclareTemplate) -> int:
    if template in UNARY_TEMPLATES:
        return 1
    if template in _ALTERNATE_CHAIN_TEMPLATES:
        return 4
    if template in _ORDERED_TEMPLATES:
        return 3
    # Remaining binary templates are unordered existence checks
    # (RESPONDED_EXISTENCE, CO_EXISTENCE and their negations).
    return 2


def count_clauses(expression: str | None) -> int:
    """Count atomic predicates in a data-condition expression.

    Parses the expression as Python (the checker evaluates these strings with
    ``eval`` after light rewriting) and counts comparison operators and
    membership tests. ``and``/``or``/``not`` combine predicates and are not
    counted themselves. Falls back to splitting on ``and``/``or`` if the
    expression is not valid Python.
    """
    if not expression or not str(expression).strip():
        return 0
    text = str(expression)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return len(re.split(r"\b(?:and|or)\b", text))

    clauses = sum(
        len(node.ops) for node in ast.walk(tree) if isinstance(node, ast.Compare)
    )
    # Expression parses but has no comparison (e.g. a bare boolean flag) — one clause.
    return clauses if clauses > 0 else 1


def referenced_attributes(*expressions: str | None) -> set[str]:
    attrs: set[str] = set()
    for expression in expressions:
        if expression:
            attrs.update(_ITEMS_ATTR_RE.findall(str(expression)))
    return attrs


@dataclass
class ComplexityBreakdown:
    rule_id: str
    template: str
    w_template: int
    n_clauses: int
    n_attributes: int
    t_time: int

    @property
    def score(self) -> int:
        return self.w_template + self.n_clauses + self.n_attributes + self.t_time

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "template": self.template,
            "w_template": self.w_template,
            "n_clauses": self.n_clauses,
            "n_attributes": self.n_attributes,
            "t_time": self.t_time,
            "complexity": self.score,
        }


def complexity(constraint: DeclareConstraint) -> ComplexityBreakdown:
    activation_expr = constraint.activation_cond.expression if constraint.activation_cond else None
    correlation_expr = constraint.correlation_cond.expression if constraint.correlation_cond else None
    return ComplexityBreakdown(
        rule_id=getattr(constraint, "id", None) or constraint.label or "",
        template=constraint.template.value,
        w_template=template_weight(constraint.template),
        n_clauses=count_clauses(activation_expr) + count_clauses(correlation_expr),
        n_attributes=len(referenced_attributes(activation_expr, correlation_expr)),
        t_time=1 if (constraint.time_condition and constraint.time_condition.is_bounded()) else 0,
    )
