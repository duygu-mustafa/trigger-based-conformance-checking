from __future__ import annotations

import pandas as pd

from conformance.results import ConformanceOutcome, ConstraintResult, TraceResult
from conformance.types import DeclareConstraint, DeclareModel, DeclareTemplate


def evaluate_constraint(case_id: str, trace_df: pd.DataFrame, constraint: DeclareConstraint) -> ConstraintResult:
    cid = constraint.label or f"{constraint.template.value}:{constraint.activation}:{constraint.target}"

    if constraint.template == DeclareTemplate.PRECEDENCE:
        target_rows = trace_df[trace_df["activity"] == constraint.target]
        if target_rows.empty:
            return ConstraintResult(case_id=case_id, constraint_id=cid, outcome=ConformanceOutcome.VACUOUS)

        act_rows = trace_df[trace_df["activity"] == constraint.activation]
        if act_rows.empty:
            return ConstraintResult(
                case_id=case_id,
                constraint_id=cid,
                outcome=ConformanceOutcome.VIOLATED,
                num_activations=int(len(target_rows)),
                num_violated=int(len(target_rows)),
                violation_reason="Activation activity missing while target exists",
            )

        ok = act_rows.iloc[0]["timestamp"] < target_rows.iloc[0]["timestamp"]
        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.SATISFIED if ok else ConformanceOutcome.VIOLATED,
            num_activations=1,
            num_fulfilled=1 if ok else 0,
            num_violated=0 if ok else 1,
            activation_ts=str(act_rows.iloc[0]["timestamp"]),
            target_ts=str(target_rows.iloc[0]["timestamp"]),
            violation_reason=None if ok else "Activation does not precede target",
        )

    if constraint.template == DeclareTemplate.NOT_CO_EXISTENCE:
        act_rows = trace_df[trace_df["activity"] == constraint.activation]
        target_rows = trace_df[trace_df["activity"] == constraint.target]
        violated = (not act_rows.empty) and (not target_rows.empty)
        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.VIOLATED if violated else ConformanceOutcome.SATISFIED,
            num_activations=int(len(act_rows)),
            num_fulfilled=0 if violated else int(len(act_rows)),
            num_violated=int(len(act_rows)) if violated else 0,
            activation_ts=str(act_rows.iloc[0]["timestamp"]) if not act_rows.empty else None,
            target_ts=str(target_rows.iloc[0]["timestamp"]) if not target_rows.empty else None,
            violation_reason="Both activities co-exist in trace" if violated else None,
        )

    return ConstraintResult(
        case_id=case_id,
        constraint_id=cid,
        outcome=ConformanceOutcome.NOT_EVALUATED,
        violation_reason=f"Template not implemented: {constraint.template.value}",
    )


def check_log_conformance(event_log_df: pd.DataFrame, model: DeclareModel) -> list[TraceResult]:
    results: list[TraceResult] = []

    for case_id, trace in event_log_df.groupby("case_id"):
        trace_sorted = trace.sort_values("timestamp")
        constraint_results = [
            evaluate_constraint(case_id=str(case_id), trace_df=trace_sorted, constraint=c)
            for c in model.constraints
        ]
        results.append(TraceResult(case_id=str(case_id), constraint_results=constraint_results))

    return results
