"""Declare Constraint Conformance Checking Module.

This module provides functionality to evaluate Declare process model constraints
against event logs. It supports multiple constraint templates (EXISTENCE, RESPONSE,
PRECEDENCE, NOT_CO_EXISTENCE) and evaluates them with support for temporal
conditions, data conditions, and correlation conditions.

Key Functions:
    - evaluate_constraint: Evaluate a single constraint against a trace
    - check_log_conformance: Check an entire event log against a model
    - _evaluate_data_condition: Parse and evaluate data-based conditions
"""

from __future__ import annotations

import math
import re

import pandas as pd

from conformance.results import ConformanceOutcome, ConstraintResult, TraceResult
from conformance.types import DeclareConstraint, DeclareModel, DeclareTemplate, TimeCondition


def _within_time_window(delta_seconds: float, constraint: DeclareConstraint) -> bool:
    """Check if a time delta falls within the constraint's time window.

    Args:
        delta_seconds: The time difference in seconds to validate.
        constraint: The Declare constraint containing temporal bounds.

    Returns:
        True if delta_seconds is within the constraint's min/max time bounds,
        or if no time condition is specified. False otherwise.
    """
    if constraint.time_condition is None:
        return True

    min_seconds = constraint.time_condition.min_seconds
    max_seconds = constraint.time_condition.max_seconds

    # Check against minimum time bound
    if min_seconds is not None and delta_seconds < float(min_seconds):
        return False
    # Check against maximum time bound
    if max_seconds is not None and delta_seconds > float(max_seconds):
        return False
    return True


def _coerce_value(value_num: object, value_raw: object) -> object:
    """Coerce event values into appropriate types (float or string).

    Attempts to convert values to float if possible, with fallback to string representation.
    This handles mixed data types from medical records where values may be stored in
    different formats.

    Args:
        value_num: Numeric value, typically from a structured field.
        value_raw: Raw string value from unstructured or text field.

    Returns:
        A float if numeric conversion succeeds, string representation if that's the only
        option, or NaN if value is None/empty.
    """
    # Try numeric value first
    if value_num is not None and not pd.isna(value_num):
        try:
            return float(value_num)
        except (TypeError, ValueError):
            pass
    
    # Return NaN if raw value is missing
    if value_raw is None or pd.isna(value_raw):
        return math.nan

    # Try parsing raw text as float
    txt = str(value_raw).strip()
    if txt == "":
        return math.nan
    try:
        return float(txt)
    except ValueError:
        # Return as string if not numeric
        return txt


def _build_items_snapshot(
    trace_df: pd.DataFrame,
    ts: pd.Timestamp,
    observation_window_hours: float | None = None,
) -> dict[int, object]:
    """Build a snapshot of medical items (key-value mapping) up to a given timestamp.

    Extracts the latest value for each unique item ID observed up to the specified time.
    This creates a point-in-time view of medical measurements and statuses.

    Args:
        trace_df: Event log DataFrame with columns: timestamp, itemid, value_num, value_raw.
        ts: The timestamp cutoff; only events at or before this time are included.

    Returns:
        Dictionary mapping item IDs (int) to their latest values as of timestamp ts.
        Empty dict if no items found or itemid column missing.
    """
    # Filter events up to the specified timestamp.
    upto = trace_df[trace_df["timestamp"] <= ts]
    if observation_window_hours is not None and observation_window_hours > 0:
        lower_bound = ts - pd.Timedelta(hours=float(observation_window_hours))
        upto = upto[upto["timestamp"] >= lower_bound]
    if upto.empty or "itemid" not in upto.columns:
        return {}

    # Remove events without item IDs
    upto = upto.dropna(subset=["itemid"]).copy()
    if upto.empty:
        return {}

    # Sort by timestamp and get the latest value for each item
    upto = upto.sort_values("timestamp", kind="stable")
    latest = upto.groupby("itemid", sort=False).tail(1)

    # Build dictionary with coerced values
    out: dict[int, object] = {}
    for _, row in latest.iterrows():
        itemid_raw = row["itemid"]
        value = _coerce_value(row.get("value_num"), row.get("value_raw"))

        # Preserve the original key so string-based item IDs like
        # 'pao2fio2ratio' remain addressable in data conditions.
        out[itemid_raw] = value

        # Also expose a numeric alias when the item ID is numeric or a
        # digit-only string so existing rules using integer references still work.
        try:
            numeric_itemid = int(itemid_raw)
        except (TypeError, ValueError):
            continue
        out[numeric_itemid] = value
    return out


def _first_ts(trace_df: pd.DataFrame, activity: str, ts: pd.Timestamp) -> pd.Timestamp | None:
    """Find the first occurrence of an activity up to a given timestamp.

    Args:
        trace_df: Event log DataFrame with timestamp and activity columns.
        activity: The activity name to search for.
        ts: Upper time bound for the search; only events at or before this time are considered.

    Returns:
        Timestamp of the first occurrence of the activity, or None if not found.
    """
    rows = trace_df[(trace_df["activity"] == activity) & (trace_df["timestamp"] <= ts)]
    if rows.empty:
        return None
    return rows.iloc[0]["timestamp"]


def _sbt_duration_minutes(
    trace_df: pd.DataFrame,
    evaluation_ts: pd.Timestamp,
    activation_ts: pd.Timestamp | None,
) -> float:
    """Calculate the duration of a Spontaneous Breathing Trial (SBT) in minutes.

    Computes elapsed time from SBT activation/start to evaluation time. If explicit
    activation_ts is provided, uses it; otherwise finds the last SBTStarted event.

    Args:
        trace_df: Event log DataFrame with activity and timestamp columns.
        evaluation_ts: The current time point for duration calculation.
        activation_ts: Optional explicit SBT activation timestamp. If None, searches for SBTStarted.

    Returns:
        Duration in minutes, always >= 0.0. Returns 0.0 if no SBT start is found.
    """
    # Use provided activation timestamp if available
    if activation_ts is not None:
        return max(0.0, float((evaluation_ts - activation_ts).total_seconds()) / 60.0)

    # Otherwise, find the last SBTStarted event
    starts = trace_df[(trace_df["activity"] == "SBTStarted") & (trace_df["timestamp"] <= evaluation_ts)]
    if starts.empty:
        return 0.0
    start_ts = starts.iloc[-1]["timestamp"]
    return max(0.0, float((evaluation_ts - start_ts).total_seconds()) / 60.0)


# Keys `_evaluate_data_condition_status` always adds to its extracted values, so a
# failure diagnosis can tell the item readings apart from the temporal context.
_CONTEXT_VALUE_KEYS = frozenset(
    {
        "hours_since_stay_start",
        "hours_since_intubation",
        "ventilation_duration_hours",
        "sbt_duration_min",
    }
)


# How informative each failure cause is, so that the diagnosis reported for an
# activation is the most specific one any candidate target produced.
_CAUSE_PRECEDENCE = {
    "absent": 1,
    "stale": 2,
    "no_payload": 3,
    "partial_payload": 4,
    "unmet": 5,
}


def _unmet_cause(condition_values: dict[str, object]) -> str:
    """Tell a criterion assessed and not met from one whose payload is missing.

    A correlation condition also evaluates to false when the items it reads are
    absent from the observation window, which is a documentation gap rather than a
    clinical finding. "no_payload" names the case where every reading is missing and
    "partial_payload" the case where only some are, which a disjunctive criterion can
    reach without its outcome being decidable. "unmet" is reserved for a condition
    that was false on readings that were all present.
    """
    readings = [v for k, v in condition_values.items() if k not in _CONTEXT_VALUE_KEYS]
    if not readings:
        return "unmet"
    n_missing = 0
    for value in readings:
        if isinstance(value, str):
            continue
        try:
            if math.isnan(float(value)):
                n_missing += 1
        except (TypeError, ValueError):
            continue
    if n_missing == 0:
        return "unmet"
    return "no_payload" if n_missing == len(readings) else "partial_payload"


def _build_eval_context(
    trace_df: pd.DataFrame,
    eval_ts: pd.Timestamp,
    activation_ts: pd.Timestamp | None = None,
    observation_window_hours: float | None = None,
) -> dict[str, object]:
    """Build a comprehensive evaluation context for data condition checking.

    Creates a dictionary containing clinical variables such as medical item values,
    time since intubation, ventilation duration, and previous SBT outcomes. This
    context is used when evaluating data-dependent conditions in constraints.

    Args:
        trace_df: Event log DataFrame containing all events for a patient stay.
        eval_ts: The timestamp at which to evaluate the context (point-in-time snapshot).
        activation_ts: Optional explicit timestamp for SBT activation; used in SBT duration calculation.

    Returns:
        Dictionary with keys:
            - items: Dict of medical item ID -> latest value pairs
            - hours_since_intubation: Float hours since intubation event (0 if not intubated)
            - ventilation_duration_hours: Float hours on invasive ventilation
            - previous_SBT_failed: Bool indicating if previous SBT attempts failed
            - is_chronic: Bool for chronic ventilation dependency
            - high_risk_flag: Bool for high-risk status (currently always False)
            - vent_mode: String mode identifier from item 223848
            - sbt_duration_min: Float minutes of current SBT duration
    """
    # Get snapshot of medical items (measurements) at evaluation time
    items = _build_items_snapshot(
        trace_df,
        eval_ts,
        observation_window_hours=observation_window_hours,
    )

    # Find key clinical milestones (using derived start instead of intubation item)
    intubation_ts = _first_ts(trace_df, "InvasiveVentilationStarted", eval_ts)
    invasive_vent_ts = intubation_ts

    # Calculate time elapsed since clinical events
    # stay_start is the first event in the trace (trace_df is already sorted)
    stay_start_ts = trace_df.iloc[0]["timestamp"] if not trace_df.empty else None
    hours_since_stay_start = (
        float((eval_ts - stay_start_ts).total_seconds()) / 3600.0 if stay_start_ts is not None else 0.0
    )

    hours_since_intubation = (
        float((eval_ts - intubation_ts).total_seconds()) / 3600.0 if intubation_ts is not None else 0.0
    )
    ventilation_duration_hours = (
        float((eval_ts - invasive_vent_ts).total_seconds()) / 3600.0
        if invasive_vent_ts is not None
        else 0.0
    )

    # Use derived ventilation duration if available as a virtual item
    documented_vent_minutes = items.get('derived_invasive_ventilation_start')
    if isinstance(documented_vent_minutes, (float, int)) and not math.isnan(float(documented_vent_minutes)):
        ventilation_duration_hours = max(ventilation_duration_hours, float(documented_vent_minutes) / 60.0)

    # Check prior SBT outcomes (failure or incompletion)
    prior = trace_df[trace_df["timestamp"] < eval_ts]
    sbt_failed_prior = False
    if not prior.empty:
        sbt_failed_prior = (
            (prior["activity"] == "SBTFailed").any()
            or (prior["activity"] == "SBTStopped").any()
        )

    # Check if patient is marked as chronic ventilation dependent
    chronic_prior = False
    if not prior.empty:
        value_raw = prior.get("value_raw", pd.Series(index=prior.index, dtype=object)).astype(str).str.lower()
        chronic_prior = ((prior["activity"] == "SBTDeferred") & value_raw.str.contains("chronic vent dependent", na=False)).any()

    # Extract ventilation mode from item 223848
    vent_mode = items.get(223848)
    if not isinstance(vent_mode, str):
        vent_mode = ""

    return {
        "items": items,
        "hours_since_stay_start": hours_since_stay_start,
        "hours_since_intubation": hours_since_intubation,
        "ventilation_duration_hours": ventilation_duration_hours,
        "previous_SBT_failed": bool(sbt_failed_prior),
        "is_chronic": bool(chronic_prior),
        "high_risk_flag": False,
        "vent_mode": vent_mode,
        "sbt_duration_min": _sbt_duration_minutes(trace_df, eval_ts, activation_ts),
    }


def _to_python_expression(expression: str) -> str:
    """Convert a Declare expression to valid Python syntax.

    Translates logical operators (AND/OR/NOT), booleans (TRUE/FALSE), and
    item access syntax into Python-compatible syntax for evaluation.

    Args:
        expression: Declare model expression string with logical operators.

    Returns:
        Python expression string ready for eval().
    """
    expr = expression
    # Convert Declare logical operators to Python equivalents
    expr = re.sub(r"\bAND\b", " and ", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\bOR\b", " or ", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\bNOT\b", " not ", expr, flags=re.IGNORECASE)
    # Convert boolean constants
    expr = re.sub(r"\bTRUE\b", " True ", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\bFALSE\b", " False ", expr, flags=re.IGNORECASE)
    # Convert item access from Declare syntax to function call
    # Supports both numeric items[220210] and string items['sbt_outcome']
    expr = re.sub(r"items\[['\"]?(\w+)['\"]?\]", r"__item('\1')", expr)
    return expr


def _evaluate_data_condition(
    trace_df: pd.DataFrame,
    row: pd.Series,
    expression: str,
    activation_ts: pd.Timestamp | None = None,
    target_ts: pd.Timestamp | None = None,
    observation_window_hours: float | None = None,
) -> tuple[bool, str | None, dict[str, float]]:
    value, _, error, values = _evaluate_data_condition_status(
        trace_df,
        row,
        expression,
        activation_ts=activation_ts,
        target_ts=target_ts,
        observation_window_hours=observation_window_hours,
    )
    return value, error, values


def _evaluate_data_condition_status(
    trace_df: pd.DataFrame,
    row: pd.Series,
    expression: str,
    activation_ts: pd.Timestamp | None = None,
    target_ts: pd.Timestamp | None = None,
    observation_window_hours: float | None = None,
) -> tuple[bool, bool, str | None, dict[str, float]]:
    """Evaluate a data condition expression against event log state at a point in time.

    Parses and executes a Declare data condition (e.g., "items[225792] > 10") in the
    context of a specific event. Variables available in conditions include medical
    items, time durations, SBT history flags, and temporal references.

    Args:
        trace_df: Full event log DataFrame for building evaluation context.
        row: The event row at which to evaluate the condition.
        expression: Declare data condition expression string (e.g., "items[12345] == 'value'").
        activation_ts: Optional explicit timestamp for SBT activation tracking.
        target_ts: Optional explicit timestamp for target event (for correlation conditions).
        observation_window_hours: Optional window in hours for observation-based conditions.

    Returns:
        Tuple of (evaluation_result, is_vacuous, error_message, values):
            - evaluation_result: True/False if condition evaluates to boolean
            - is_vacuous: True when the condition cannot be evaluated because
              required items are missing from the observation window
            - error_message: String describing any evaluation error, or None if successful
            - values: Dictionary mapping item IDs or variable names to their extracted values
    """
    # Empty expressions always evaluate to true
    if not expression.strip():
        return True, False, None, {}

    # Build context with all clinical variables at evaluation time
    eval_ts = row["timestamp"]
    ctx = _build_eval_context(
        trace_df,
        eval_ts=eval_ts,
        activation_ts=activation_ts,
        observation_window_hours=observation_window_hours,
    )
    items = ctx["items"]

    # Uploaded wide logs (XES) carry data in per-event attribute columns rather than
    # an itemid/value_num long form, so expose the current event row's own attributes
    # as items. A data condition on such a log tests the activation/target event itself.
    if "itemid" not in trace_df.columns:
        for col, val in row.items():
            if col in ("case_id", "activity", "timestamp") or pd.isna(val):
                continue
            try:
                items[col] = float(val)
            except (TypeError, ValueError):
                items[col] = str(val)

    # Track values used in the expression for delta analysis
    extracted_values = {}

    # If a bounded observation window is requested, only treat the condition as
    # vacuous when every referenced item is missing from the observation window.
    # Partial data should still be allowed to satisfy OR-based rules.
    if observation_window_hours is not None:
        refs = re.findall(r"items\[['\"]?(\w+)['\"]?\]", expression)
        if refs:
            all_missing = True
            for ref in refs:
                if ref.isdigit():
                    if int(ref) not in items:
                        continue
                elif ref not in items:
                    continue
                all_missing = False
                break
            if all_missing:
                return False, True, None, {}

    # Helper function to safely retrieve item values
    def __item(itemid: str | int) -> object:
        # Support both numeric and string keys
        key = int(itemid) if isinstance(itemid, str) and itemid.isdigit() else itemid
        val = items.get(key, math.nan)
        extracted_values[str(key)] = val
        return val

    # Helper functions for date arithmetic
    def __date(ts: object) -> object:
        """Extract date from a Timestamp or datetime object."""
        if isinstance(ts, pd.Timestamp):
            return ts.date()
        if hasattr(ts, 'date'):
            return ts.date()
        return None
    
    def __timedelta(**kwargs) -> object:
        """Create a timedelta object for date arithmetic."""
        return pd.Timedelta(**kwargs)

    # Set up local namespace with all available variables for eval()
    local_scope = {
        "__item": __item,
        "__date": __date,
        "__timedelta": __timedelta,
        "date": __date,
        "timedelta": __timedelta,
        "hours_since_stay_start": ctx["hours_since_stay_start"],
        "hours_since_intubation": ctx["hours_since_intubation"],
        "ventilation_duration_hours": ctx["ventilation_duration_hours"],
        "previous_SBT_failed": ctx["previous_SBT_failed"],
        "is_chronic": ctx["is_chronic"],
        "high_risk_flag": ctx["high_risk_flag"],
        "vent_mode": ctx["vent_mode"],
        "sbt_duration_min": ctx["sbt_duration_min"],
        "activation_ts": activation_ts,
        "target_ts": target_ts,
        "True": True,
        "False": False,
    }
    
    # Also add non-item variables to extracted values
    for k in ["hours_since_stay_start", "hours_since_intubation", "ventilation_duration_hours", "sbt_duration_min"]:
        extracted_values[k] = local_scope[k]

    # Convert to Python syntax and evaluate
    py_expr = _to_python_expression(expression)
    try:
        value = eval(py_expr, {"__builtins__": {}}, local_scope)
    except Exception as exc:
        return False, False, f"Condition evaluation failed: {exc}", extracted_values

    # Ensure boolean result
    if isinstance(value, bool):
        return value, False, None, extracted_values
    return bool(value), False, None, extracted_values


def _filter_activation_rows(
    trace_df: pd.DataFrame,
    activation_rows: pd.DataFrame,
    constraint: DeclareConstraint,
    observation_window_hours: float | None = None,
) -> tuple[pd.DataFrame, str | None]:
    """Filter activation rows based on activation condition expression.

    For constraints with data conditions that guard when they activate (e.g.,
    "only check this constraint if patient meets criteria X"), this filters
    the activation events to only those satisfying the guard condition.

    Args:
        trace_df: Full event log for context when evaluating conditions.
        activation_rows: DataFrame of candidate activation events.
        constraint: Declare constraint with optional activation_cond.

    Returns:
        Tuple of (filtered_rows, eval_error):
            - filtered_rows: Subset of activation_rows passing the condition
            - eval_error: Error message if condition evaluation failed, None otherwise
    """
    # No condition to filter, return all rows
    if constraint.activation_cond is None:
        return activation_rows, None

    # Evaluate condition for each activation row
    expr = constraint.activation_cond.expression
    keep_indices: list[int] = []
    eval_error: str | None = None

    for idx, row in activation_rows.iterrows():
        ok, err, _ = _evaluate_data_condition(
            trace_df,
            row,
            expr,
            observation_window_hours=observation_window_hours,
        )
        if err is not None and eval_error is None:
            eval_error = err
        if ok:
            keep_indices.append(idx)

    # Return filtered rows or empty DataFrame if none match
    if not keep_indices:
        return activation_rows.iloc[0:0], eval_error
    return activation_rows.loc[keep_indices], eval_error


def _evaluate_constraint_impl(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate a single Declare constraint against a patient's event trace.

    Supports multiple constraint templates:
        - EXISTENCE: Required activity must occur (optionally satisfying a condition)
        - RESPONSE: When activation occurs, target must follow (within time window)
        - PRECEDENCE: When activation occurs, target must have occurred before it
        - NOT_CO_EXISTENCE: Activation and target cannot both occur

    Args:
        case_id: Patient/case identifier for result tracking.
        trace_df: Event log DataFrame for a single patient, sorted by timestamp.
        constraint: Declare constraint object with template, activities, and conditions.

    Returns:
        ConstraintResult object with outcome, counts, and violation details.
    """
    # Create constraint identifier for tracking results
    cid = (
        getattr(constraint, "id", None)
        or constraint.label
        or f"{constraint.template.value}:{constraint.activation}:{constraint.target}"
    )

    def _observation_window_hours() -> float | None:
        raw = getattr(constraint, "observation_window_hours", None)
        if raw is not None:
            try:
                val = float(raw)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass

        # Backward-compatible fallback for readiness data rules.
        if isinstance(cid, str) and cid.startswith("RC-DP-"):
            return 24.0
        return None

    observation_window_hours = _observation_window_hours()

    def _rows_for(activity: str | None) -> pd.DataFrame:
        if activity is None:
            return trace_df.iloc[0:0]
        return trace_df[trace_df["activity"] == activity]

    def _candidate_activations() -> tuple[pd.DataFrame, str | None]:
        rows = _rows_for(constraint.activation)
        if rows.empty:
            return rows, None
        return _filter_activation_rows(
            trace_df,
            rows,
            constraint,
            observation_window_hours=observation_window_hours,
        )

    def _target_matches(
        target_row: pd.Series,
        activation_ts: pd.Timestamp,
        *,
        require_after: bool,
        require_before: bool,
        require_adjacent: bool,
        directional_time: bool,
    ) -> tuple[bool, str | None, float | None, dict[str, float], str | None]:
        """Return (matched, error, time_delta, condition_values, failure_cause).

        `failure_cause` is None on a match and otherwise names why the candidate
        did not discharge the activation: "stale" for a target outside the time
        condition, "unmet" for one whose correlation condition is false.
        """
        target_ts = target_row["timestamp"]
        if require_after and not (target_ts > activation_ts):
            return False, None, None, {}, "stale"
        if require_before and not (target_ts < activation_ts):
            return False, None, None, {}, "stale"

        if require_adjacent:
            # Adjacency is guaranteed by caller selecting the direct predecessor/successor.
            pass

        delta_seconds = float((target_ts - activation_ts).total_seconds())
        time_delta = delta_seconds if directional_time else abs(delta_seconds)

        if not _within_time_window(time_delta, constraint):
            return False, None, time_delta, {}, "stale"

        if constraint.correlation_cond is not None:
            corr_ok, corr_err, corr_values = _evaluate_data_condition(
                trace_df,
                target_row,
                constraint.correlation_cond.expression,
                activation_ts=activation_ts,
                target_ts=target_ts,
            )
            if corr_err is not None:
                return False, corr_err, time_delta, corr_values, "unmet"
            if not corr_ok:
                return False, None, time_delta, corr_values, _unmet_cause(corr_values)
            return True, None, time_delta, corr_values, None

        return True, None, time_delta, {}, None

    target_selection = getattr(constraint, "target_selection", None) or "any"

    def _select_candidates(
        candidates: pd.DataFrame,
        activation_ts: pd.Timestamp,
        *,
        directional_time: bool,
    ) -> pd.DataFrame:
        """Apply the target-selection mode (method.tex, Def. "Target selection").

        Under "earliest"/"latest" the candidate sequence M_i is the target rows
        whose timestamp differs from the activation's and whose delta lies in
        the time condition, in trace order; only its first (m_1) or last (m_k)
        element is kept. Ties among simultaneous candidates follow trace order.
        Under "any" the candidates are returned unchanged.
        """
        if target_selection == "any" or candidates.empty:
            return candidates
        deltas = (candidates["timestamp"] - activation_ts).dt.total_seconds()
        if not directional_time:
            deltas = deltas.abs()
        in_window = (candidates["timestamp"] != activation_ts) & deltas.map(
            lambda d: _within_time_window(float(d), constraint)
        ).astype(bool)
        in_window_rows = candidates[in_window]
        if target_selection == "earliest":
            return in_window_rows.head(1)
        return in_window_rows.tail(1)

    # ============ EXISTENCE / ABSENCE / EXACTLY / INIT / END (unary) ============
    if constraint.template == DeclareTemplate.EXISTENCE:
        # AtLeastOne(x) = G(start -> F x): activated once, at the start of the
        # trace, and fulfilled by any occurrence of x. An activation condition
        # restricts which occurrences of x count; without one, every x counts.
        if trace_df.empty:
            return ConstraintResult(case_id=case_id, constraint_id=cid, outcome=ConformanceOutcome.VACUOUS)
        start_ts = str(trace_df.iloc[0]["timestamp"])
        act_rows = _rows_for(constraint.activation)

        first_eval_error = None
        satisfaction_deltas = {}
        qualifying = act_rows
        if constraint.activation_cond is not None and not act_rows.empty:
            keep_idx: list[int] = []
            for idx, row in act_rows.iterrows():
                cond_true, _is_vacuous, eval_err, vals = _evaluate_data_condition_status(
                    trace_df,
                    row,
                    constraint.activation_cond.expression,
                    observation_window_hours=observation_window_hours,
                )
                if eval_err is not None and first_eval_error is None:
                    first_eval_error = eval_err
                if cond_true:
                    keep_idx.append(idx)
                    if not satisfaction_deltas:
                        satisfaction_deltas = vals
            qualifying = act_rows.loc[keep_idx] if keep_idx else act_rows.iloc[0:0]

        ok = not qualifying.empty
        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.SATISFIED if ok else ConformanceOutcome.VIOLATED,
            num_activations=1,
            num_fulfilled=1 if ok else 0,
            num_violated=0 if ok else 1,
            activation_ts=start_ts,
            target_ts=str(qualifying.iloc[0]["timestamp"]) if ok else None,
            satisfaction_deltas=satisfaction_deltas if ok else {},
            violation_reason=(None if ok else "Activity never occurs in the trace")
            if first_eval_error is None
            else first_eval_error,
        )

    if constraint.template == DeclareTemplate.ABSENCE:
        act_rows, activation_eval_error = _candidate_activations()
        violated = int(len(act_rows))
        ok = violated == 0
        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.SATISFIED if ok else ConformanceOutcome.VIOLATED,
            num_activations=int(len(act_rows)),
            num_fulfilled=0 if not ok else 1,
            num_violated=violated,
            activation_ts=str(act_rows.iloc[0]["timestamp"]) if not act_rows.empty else None,
            violation_reason=(None if ok else "Forbidden activity occurred")
            if activation_eval_error is None
            else activation_eval_error,
        )

    if constraint.template == DeclareTemplate.AT_MOST_ONE:
        act_rows, activation_eval_error = _candidate_activations()
        count = int(len(act_rows))
        ok = count <= 1
        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.SATISFIED if ok else ConformanceOutcome.VIOLATED,
            num_activations=count,
            num_fulfilled=1 if ok else 0,
            num_violated=0 if ok else count - 1,
            activation_ts=str(act_rows.iloc[0]["timestamp"]) if not act_rows.empty else None,
            violation_reason=(None if ok else "Activity must occur at most once")
            if activation_eval_error is None
            else activation_eval_error,
        )

    if constraint.template == DeclareTemplate.INIT:
        if trace_df.empty:
            return ConstraintResult(case_id=case_id, constraint_id=cid, outcome=ConformanceOutcome.VACUOUS)

        first_row = trace_df.sort_values("timestamp", kind="stable").iloc[0]
        ok = bool(first_row["activity"] == constraint.activation)
        eval_error = None
        violation_deltas = {}
        if ok and constraint.activation_cond is not None:
            ok, eval_error, violation_deltas = _evaluate_data_condition(
                trace_df,
                first_row,
                constraint.activation_cond.expression,
                observation_window_hours=observation_window_hours,
            )

        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.SATISFIED if ok else ConformanceOutcome.VIOLATED,
            num_activations=1,
            num_fulfilled=1 if ok else 0,
            num_violated=0 if ok else 1,
            activation_ts=str(first_row["timestamp"]),
            violation_deltas=violation_deltas if not ok else {},
            satisfaction_deltas=violation_deltas if ok else {},
            violation_reason=(None if ok else "First event does not satisfy INIT")
            if eval_error is None
            else eval_error,
        )

    if constraint.template == DeclareTemplate.END:
        if trace_df.empty:
            return ConstraintResult(case_id=case_id, constraint_id=cid, outcome=ConformanceOutcome.VACUOUS)

        last_row = trace_df.sort_values("timestamp", kind="stable").iloc[-1]
        ok = bool(last_row["activity"] == constraint.activation)
        eval_error = None
        violation_deltas = {}
        if ok and constraint.activation_cond is not None:
            ok, eval_error, violation_deltas = _evaluate_data_condition(
                trace_df,
                last_row,
                constraint.activation_cond.expression,
                observation_window_hours=observation_window_hours,
            )

        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.SATISFIED if ok else ConformanceOutcome.VIOLATED,
            num_activations=1,
            num_fulfilled=1 if ok else 0,
            num_violated=0 if ok else 1,
            activation_ts=str(last_row["timestamp"]),
            violation_deltas=violation_deltas if not ok else {},
            satisfaction_deltas=violation_deltas if ok else {},
            violation_reason=(None if ok else "Last event does not satisfy END")
            if eval_error is None
            else eval_error,
        )

    # ============ RESPONSE FAMILY ============
    if constraint.template in {
        DeclareTemplate.RESPONSE,
        DeclareTemplate.ALTERNATE_RESPONSE,
        DeclareTemplate.CHAIN_RESPONSE,
        DeclareTemplate.NOT_RESPONSE,
        DeclareTemplate.NOT_CHAIN_RESPONSE,
    }:
        act_rows, activation_eval_error = _candidate_activations()
        if act_rows.empty:
            return ConstraintResult(case_id=case_id, constraint_id=cid, outcome=ConformanceOutcome.VACUOUS)

        target_rows = _rows_for(constraint.target)

        fulfilled = 0
        violated = 0
        first_violation_ts = None
        first_match_target_ts = None
        first_corr_error = None
        violation_deltas = {}
        satisfaction_deltas = {}
        delay_seconds = None

        for i, (_, act_row) in enumerate(act_rows.iterrows()):
            act_ts = act_row["timestamp"]
            next_act_ts = (
                act_rows.iloc[i + 1]["timestamp"]
                if constraint.template == DeclareTemplate.ALTERNATE_RESPONSE and i + 1 < len(act_rows)
                else None
            )

            if constraint.template in {
                DeclareTemplate.CHAIN_RESPONSE,
                DeclareTemplate.NOT_CHAIN_RESPONSE,
            }:
                succ = trace_df[trace_df["timestamp"] > act_ts].head(1)
                candidates = succ[succ["activity"] == constraint.target] if not succ.empty else succ
            else:
                candidates = target_rows[target_rows["timestamp"] > act_ts]
                if next_act_ts is not None:
                    candidates = candidates[candidates["timestamp"] < next_act_ts]
                candidates = _select_candidates(candidates, act_ts, directional_time=True)

            matched = False
            best_effort_forensics = None
            
            for _, target_row in candidates.iterrows():
                ok_match, corr_error, delta, vals, _cause = _target_matches(
                    target_row,
                    act_ts,
                    require_after=True,
                    require_before=False,
                    require_adjacent=constraint.template
                    in {
                        DeclareTemplate.CHAIN_RESPONSE,
                        DeclareTemplate.NOT_CHAIN_RESPONSE,
                    },
                    directional_time=True,
                )
                
                # Keep track of the first target we see for forensics if we never find a valid match
                if best_effort_forensics is None:
                    best_effort_forensics = (delta, vals)
                    
                if corr_error is not None and first_corr_error is None:
                    first_corr_error = corr_error
                if ok_match:
                    matched = True
                    if delay_seconds is None:
                        delay_seconds = delta
                    if first_match_target_ts is None:
                        first_match_target_ts = str(target_row["timestamp"])
                    break

            is_negative = constraint.template in {
                DeclareTemplate.NOT_RESPONSE,
                DeclareTemplate.NOT_CHAIN_RESPONSE,
            }

            if (matched and not is_negative) or ((not matched) and is_negative):
                fulfilled += 1
                # Capture satisfaction forensics
                if best_effort_forensics:
                    _, satisfaction_deltas = best_effort_forensics
                elif matched:
                    satisfaction_deltas = vals
            else:
                violated += 1
                if first_violation_ts is None:
                    first_violation_ts = str(act_ts)
                    if not matched and not is_negative:
                        if best_effort_forensics:
                            delay_seconds, violation_deltas = best_effort_forensics
                        else:
                            _, _, _, violation_deltas = _evaluate_data_condition_status(
                                trace_df, act_row, "True"
                            )
                    elif matched and is_negative:
                        violation_deltas = vals
                        delay_seconds = delta

        ok = violated == 0
        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.SATISFIED if ok else ConformanceOutcome.VIOLATED,
            num_activations=int(len(act_rows)),
            num_fulfilled=int(fulfilled),
            num_violated=int(violated),
            activation_ts=str(act_rows.iloc[0]["timestamp"]) if not act_rows.empty else first_violation_ts,
            target_ts=first_match_target_ts,
            violation_deltas=violation_deltas if not ok else {},
            satisfaction_deltas=satisfaction_deltas if ok else {},
            delay_seconds=delay_seconds,
            violation_reason=(
                None
                if ok
                else (
                    "One or more activations violate response ordering"
                    if constraint.template
                    in {
                        DeclareTemplate.RESPONSE,
                        DeclareTemplate.ALTERNATE_RESPONSE,
                        DeclareTemplate.CHAIN_RESPONSE,
                    }
                    else "Forbidden response pattern detected"
                )
            )
            if activation_eval_error is None and first_corr_error is None
            else (activation_eval_error or first_corr_error),
        )

    # ============ RESPONDED EXISTENCE ============
    if constraint.template in {
        DeclareTemplate.RESPONDED_EXISTENCE,
        DeclareTemplate.NOT_RESPONDED_EXISTENCE,
    }:
        act_rows, activation_eval_error = _candidate_activations()
        if act_rows.empty:
            return ConstraintResult(case_id=case_id, constraint_id=cid, outcome=ConformanceOutcome.VACUOUS)

        target_rows = _rows_for(constraint.target)
        fulfilled = 0
        violated = 0
        first_violation_ts = None
        first_match_target_ts = None
        first_corr_error = None
        is_negative = constraint.template == DeclareTemplate.NOT_RESPONDED_EXISTENCE
        violation_deltas = {}
        satisfaction_deltas = {}

        for _, act_row in act_rows.iterrows():
            act_ts = act_row["timestamp"]
            matched = False
            for _, target_row in target_rows.iterrows():
                ok_match, corr_error, delta, vals, _cause = _target_matches(
                    target_row,
                    act_ts,
                    require_after=False,
                    require_before=False,
                    require_adjacent=False,
                    directional_time=False,
                )
                if corr_error is not None and first_corr_error is None:
                    first_corr_error = corr_error
                if ok_match:
                    matched = True
                    if first_match_target_ts is None:
                        first_match_target_ts = str(target_row["timestamp"])
                    break

            if (matched and not is_negative) or ((not matched) and is_negative):
                fulfilled += 1
                if matched:
                    satisfaction_deltas = vals
            else:
                violated += 1
                if first_violation_ts is None:
                    first_violation_ts = str(act_ts)
                    if matched and is_negative:
                        violation_deltas = vals

        ok = violated == 0
        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.SATISFIED if ok else ConformanceOutcome.VIOLATED,
            num_activations=int(len(act_rows)),
            num_fulfilled=int(fulfilled),
            num_violated=int(violated),
            activation_ts=str(act_rows.iloc[0]["timestamp"]) if not act_rows.empty else first_violation_ts,
            target_ts=first_match_target_ts,
            violation_deltas=violation_deltas if not ok else {},
            satisfaction_deltas=satisfaction_deltas if ok else {},
            violation_reason=(
                None
                if ok
                else (
                    "Target activity missing for responded existence"
                    if not is_negative
                    else "Forbidden co-occurrence found for not responded existence"
                )
            )
            if activation_eval_error is None and first_corr_error is None
            else (activation_eval_error or first_corr_error),
        )

    # ============ PRECEDENCE FAMILY ============
    # Semantics: for each activation (the trigger, e.g. SBTStarted), check that
    # target (the precondition, e.g. InvasiveVentilationStarted) occurred before it.
    # Activation iterates; candidates are drawn from target rows before activation_ts.
    if constraint.template in {
        DeclareTemplate.PRECEDENCE,
        DeclareTemplate.ALTERNATE_PRECEDENCE,
        DeclareTemplate.CHAIN_PRECEDENCE,
        DeclareTemplate.NOT_PRECEDENCE,
        DeclareTemplate.NOT_CHAIN_PRECEDENCE,
    }:
        act_rows = _rows_for(constraint.activation)
        if act_rows.empty:
            return ConstraintResult(case_id=case_id, constraint_id=cid, outcome=ConformanceOutcome.VACUOUS)

        if constraint.activation_cond is not None:
            act_rows, activation_eval_error = _filter_activation_rows(trace_df, act_rows, constraint)
        else:
            activation_eval_error = None

        if act_rows.empty:
            return ConstraintResult(case_id=case_id, constraint_id=cid, outcome=ConformanceOutcome.VACUOUS)

        target_rows = _rows_for(constraint.target)
        fulfilled = 0
        violated = 0
        first_violation_ts = None
        first_match_activation_ts = None
        first_match_target_ts = None
        first_corr_error = None
        violation_deltas = {}
        satisfaction_deltas = {}
        delay_seconds = None
        violation_causes: dict[str, int] = {}
        violation_values: dict[str, float] = {}

        for _, act_row in act_rows.iterrows():
            act_ts = act_row["timestamp"]

            if constraint.template in {
                DeclareTemplate.CHAIN_PRECEDENCE,
                DeclareTemplate.NOT_CHAIN_PRECEDENCE,
            }:
                prev = trace_df[trace_df["timestamp"] < act_ts].tail(1)
                candidates = prev[prev["activity"] == constraint.target] if not prev.empty else prev
            else:
                candidates = target_rows[target_rows["timestamp"] < act_ts]
                if constraint.template == DeclareTemplate.ALTERNATE_PRECEDENCE:
                    prev_act = act_rows[act_rows["timestamp"] < act_ts].tail(1)
                    if not prev_act.empty:
                        prev_act_ts = prev_act.iloc[0]["timestamp"]
                        candidates = candidates[candidates["timestamp"] > prev_act_ts]

            had_targets = not candidates.empty
            candidates = _select_candidates(candidates, act_ts, directional_time=True)

            matched = False
            # Why this activation was not discharged, if it was not: "absent" when
            # no candidate target exists at all, "stale" when targets exist but
            # target selection found none inside the time condition, otherwise the
            # cause reported by the last candidate examined.
            if candidates.empty:
                cause = "stale" if had_targets else "absent"
            else:
                cause = None
            cause_values: dict[str, float] = {}
            for _, cand_row in candidates.iterrows():
                ok_match, corr_error, delta, vals, cand_cause = _target_matches(
                    cand_row,
                    act_ts,
                    require_after=False,
                    require_before=True,
                    require_adjacent=constraint.template
                    in {DeclareTemplate.CHAIN_PRECEDENCE, DeclareTemplate.NOT_CHAIN_PRECEDENCE},
                    directional_time=True,
                )
                if corr_error is not None and first_corr_error is None:
                    first_corr_error = corr_error
                if ok_match:
                    matched = True
                    if first_match_activation_ts is None:
                        first_match_activation_ts = str(act_ts)
                    if first_match_target_ts is None:
                        first_match_target_ts = str(cand_row["timestamp"])
                    break
                # Keep the most specific diagnosis across the candidates examined.
                if _CAUSE_PRECEDENCE.get(cand_cause, 0) > _CAUSE_PRECEDENCE.get(cause, 0):
                    cause = cand_cause
                if cand_cause == "unmet" and vals:
                    cause_values = vals

            is_negative = constraint.template in {
                DeclareTemplate.NOT_PRECEDENCE,
                DeclareTemplate.NOT_CHAIN_PRECEDENCE,
            }
            if (matched and not is_negative) or ((not matched) and is_negative):
                fulfilled += 1
                if matched:
                    satisfaction_deltas = vals
            else:
                violated += 1
                if not matched and not is_negative and cause is not None:
                    violation_causes[cause] = violation_causes.get(cause, 0) + 1
                    if cause_values and not violation_values:
                        violation_values = cause_values
                if first_violation_ts is None:
                    first_violation_ts = str(act_ts)
                    if not matched and not is_negative:
                        _, _, _, violation_deltas = _evaluate_data_condition_status(
                            trace_df, act_row, "True"
                        )
                    elif matched and is_negative:
                        violation_deltas = vals
                        delay_seconds = abs(delta) if delta is not None else None

        ok = violated == 0
        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.SATISFIED if ok else ConformanceOutcome.VIOLATED,
            num_activations=int(len(act_rows)),
            num_fulfilled=int(fulfilled),
            num_violated=int(violated),
            activation_ts=first_match_activation_ts,
            target_ts=first_match_target_ts if first_match_target_ts is not None else first_violation_ts,
            violation_deltas=violation_deltas if not ok else {},
            satisfaction_deltas=satisfaction_deltas if ok else {},
            delay_seconds=delay_seconds,
            violation_causes=violation_causes,
            violation_values=violation_values,
            violation_reason=(
                None
                if ok
                else (
                    "Precedence relation violated"
                    if constraint.template
                    in {
                        DeclareTemplate.PRECEDENCE,
                        DeclareTemplate.ALTERNATE_PRECEDENCE,
                        DeclareTemplate.CHAIN_PRECEDENCE,
                    }
                    else "Forbidden precedence relation detected"
                )
            )
            if activation_eval_error is None and first_corr_error is None
            else (activation_eval_error or first_corr_error),
        )

    # ============ CO-EXISTENCE FAMILY ============
    if constraint.template in {DeclareTemplate.CO_EXISTENCE, DeclareTemplate.NOT_CO_EXISTENCE}:
        act_rows, activation_eval_error = _candidate_activations()
        target_rows = _rows_for(constraint.target)

        first_corr_error = None
        violation_deltas = {}
        if constraint.correlation_cond is not None and not target_rows.empty:
            keep_target_idx: list[int] = []
            for idx, row in target_rows.iterrows():
                ok_corr, corr_err, corr_vals = _evaluate_data_condition(
                    trace_df,
                    row,
                    constraint.correlation_cond.expression,
                )
                if corr_err is not None and first_corr_error is None:
                    first_corr_error = corr_err
                if ok_corr:
                    keep_target_idx.append(idx)
                    violation_deltas = corr_vals # Last matched
            target_rows = target_rows.loc[keep_target_idx] if keep_target_idx else target_rows.iloc[0:0]

        # NotCoExistence is activated only by the activation activity; CoExistence
        # by either activity. Without an activation the constraint holds vacuously.
        if act_rows.empty and (
            constraint.template == DeclareTemplate.NOT_CO_EXISTENCE or target_rows.empty
        ):
            return ConstraintResult(case_id=case_id, constraint_id=cid, outcome=ConformanceOutcome.VACUOUS)

        if constraint.template == DeclareTemplate.CO_EXISTENCE:
            ok = (act_rows.empty and target_rows.empty) or ((not act_rows.empty) and (not target_rows.empty))
            violated = 0 if ok else max(int(len(act_rows)), int(len(target_rows)), 1)
            return ConstraintResult(
                case_id=case_id,
                constraint_id=cid,
                outcome=ConformanceOutcome.SATISFIED if ok else ConformanceOutcome.VIOLATED,
                num_activations=int(len(act_rows)),
                num_fulfilled=1 if ok else 0,
                num_violated=violated,
                activation_ts=str(act_rows.iloc[0]["timestamp"]) if not act_rows.empty else None,
                target_ts=str(target_rows.iloc[0]["timestamp"]) if not target_rows.empty else None,
                violation_reason=(None if ok else "Co-existence requires both activities or neither")
                if activation_eval_error is None and first_corr_error is None
                else (activation_eval_error or first_corr_error),
            )

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
            violation_deltas=violation_deltas if violated else {},
            violation_reason=("Both activities co-exist in trace" if violated else None)
            if activation_eval_error is None and first_corr_error is None
            else (activation_eval_error or first_corr_error),
        )

    # ============ SUCCESSION FAMILY ============
    if constraint.template in {
        DeclareTemplate.SUCCESSION,
        DeclareTemplate.ALTERNATE_SUCCESSION,
        DeclareTemplate.CHAIN_SUCCESSION,
        DeclareTemplate.NOT_SUCCESSION,
        DeclareTemplate.NOT_CHAIN_SUCCESSION,
    }:
        # k(x, y) = k_response(x, y) AND k_precedence(x, y), where the precedence
        # component is activated by y and looks back for x (tab:declare_templates),
        # so its roles are swapped relative to the constraint's.
        mapped = {
            DeclareTemplate.SUCCESSION: (DeclareTemplate.RESPONSE, DeclareTemplate.PRECEDENCE),
            DeclareTemplate.ALTERNATE_SUCCESSION: (
                DeclareTemplate.ALTERNATE_RESPONSE,
                DeclareTemplate.ALTERNATE_PRECEDENCE,
            ),
            DeclareTemplate.CHAIN_SUCCESSION: (DeclareTemplate.CHAIN_RESPONSE, DeclareTemplate.CHAIN_PRECEDENCE),
            DeclareTemplate.NOT_SUCCESSION: (DeclareTemplate.NOT_RESPONSE, DeclareTemplate.NOT_PRECEDENCE),
            DeclareTemplate.NOT_CHAIN_SUCCESSION: (
                DeclareTemplate.NOT_CHAIN_RESPONSE,
                DeclareTemplate.NOT_CHAIN_PRECEDENCE,
            ),
        }
        response_t, precedence_t = mapped[constraint.template]

        response_result = _evaluate_constraint_impl(
            case_id=case_id,
            trace_df=trace_df,
            constraint=DeclareConstraint(
                template=response_t,
                activation=constraint.activation,
                target=constraint.target,
                activation_cond=constraint.activation_cond,
                correlation_cond=constraint.correlation_cond,
                time_condition=constraint.time_condition,
                label=f"{cid}::response_component",
            ),
        )
        # The activation and correlation conditions are stated over the x -> y
        # direction and apply to the response component only. The time window
        # is mirrored, since the precedence component measures from y back to x.
        tc = constraint.time_condition
        mirrored_tc = (
            TimeCondition(
                min_seconds=-tc.max_seconds if tc.max_seconds is not None else None,
                max_seconds=-tc.min_seconds if tc.min_seconds is not None else None,
            )
            if tc is not None
            else None
        )
        precedence_result = _evaluate_constraint_impl(
            case_id=case_id,
            trace_df=trace_df,
            constraint=DeclareConstraint(
                template=precedence_t,
                activation=constraint.target,
                target=constraint.activation,
                time_condition=mirrored_tc,
                label=f"{cid}::precedence_component",
            ),
        )

        if (
            response_result.outcome == ConformanceOutcome.VACUOUS
            and precedence_result.outcome == ConformanceOutcome.VACUOUS
        ):
            outcome = ConformanceOutcome.VACUOUS
        elif (
            response_result.outcome == ConformanceOutcome.VIOLATED
            or precedence_result.outcome == ConformanceOutcome.VIOLATED
        ):
            outcome = ConformanceOutcome.VIOLATED
        else:
            outcome = ConformanceOutcome.SATISFIED

        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=outcome,
            num_activations=max(response_result.num_activations, precedence_result.num_activations),
            num_fulfilled=min(response_result.num_fulfilled, precedence_result.num_fulfilled),
            num_violated=response_result.num_violated + precedence_result.num_violated,
            activation_ts=response_result.activation_ts or precedence_result.activation_ts,
            target_ts=response_result.target_ts or precedence_result.target_ts,
            violation_deltas=(
                response_result.violation_deltas or precedence_result.violation_deltas
            ) if outcome == ConformanceOutcome.VIOLATED else {},
            delay_seconds=(
                response_result.delay_seconds or precedence_result.delay_seconds
            ) if outcome == ConformanceOutcome.VIOLATED else None,
            violation_reason=(
                None
                if outcome != ConformanceOutcome.VIOLATED
                else (
                    response_result.violation_reason
                    or precedence_result.violation_reason
                    or "Succession relation violated"
                )
            ),
        )

    # Template not supported
    return ConstraintResult(
        case_id=case_id,
        constraint_id=cid,
        outcome=ConformanceOutcome.NOT_EVALUATED,
        violation_reason=f"Template not implemented: {constraint.template.value}",
    )


def evaluate_existence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `EXISTENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_absence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `ABSENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_at_most_one_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `AT_MOST_ONE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_init_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `INIT` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_end_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `END` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_responded_existence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `RESPONDED_EXISTENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_response_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `RESPONSE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_alternate_response_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `ALTERNATE_RESPONSE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_chain_response_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `CHAIN_RESPONSE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_precedence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `PRECEDENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_alternate_precedence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `ALTERNATE_PRECEDENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_chain_precedence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `CHAIN_PRECEDENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_co_existence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `CO_EXISTENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_succession_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `SUCCESSION` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_alternate_succession_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `ALTERNATE_SUCCESSION` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_chain_succession_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `CHAIN_SUCCESSION` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_not_responded_existence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `NOT_RESPONDED_EXISTENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_not_response_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `NOT_RESPONSE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_not_chain_response_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `NOT_CHAIN_RESPONSE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_not_precedence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `NOT_PRECEDENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_not_chain_precedence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `NOT_CHAIN_PRECEDENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_not_co_existence_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `NOT_CO_EXISTENCE` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_not_succession_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `NOT_SUCCESSION` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


def evaluate_not_chain_succession_rule(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Evaluate `NOT_CHAIN_SUCCESSION` constraints."""
    return _evaluate_constraint_impl(case_id=case_id, trace_df=trace_df, constraint=constraint)


_TEMPLATE_EVALUATORS: dict[
    DeclareTemplate,
    callable,
] = {
    DeclareTemplate.EXISTENCE: evaluate_existence_rule,
    DeclareTemplate.ABSENCE: evaluate_absence_rule,
    DeclareTemplate.AT_MOST_ONE: evaluate_at_most_one_rule,
    DeclareTemplate.INIT: evaluate_init_rule,
    DeclareTemplate.END: evaluate_end_rule,
    DeclareTemplate.RESPONDED_EXISTENCE: evaluate_responded_existence_rule,
    DeclareTemplate.RESPONSE: evaluate_response_rule,
    DeclareTemplate.ALTERNATE_RESPONSE: evaluate_alternate_response_rule,
    DeclareTemplate.CHAIN_RESPONSE: evaluate_chain_response_rule,
    DeclareTemplate.PRECEDENCE: evaluate_precedence_rule,
    DeclareTemplate.ALTERNATE_PRECEDENCE: evaluate_alternate_precedence_rule,
    DeclareTemplate.CHAIN_PRECEDENCE: evaluate_chain_precedence_rule,
    DeclareTemplate.CO_EXISTENCE: evaluate_co_existence_rule,
    DeclareTemplate.SUCCESSION: evaluate_succession_rule,
    DeclareTemplate.ALTERNATE_SUCCESSION: evaluate_alternate_succession_rule,
    DeclareTemplate.CHAIN_SUCCESSION: evaluate_chain_succession_rule,
    DeclareTemplate.NOT_RESPONDED_EXISTENCE: evaluate_not_responded_existence_rule,
    DeclareTemplate.NOT_RESPONSE: evaluate_not_response_rule,
    DeclareTemplate.NOT_CHAIN_RESPONSE: evaluate_not_chain_response_rule,
    DeclareTemplate.NOT_PRECEDENCE: evaluate_not_precedence_rule,
    DeclareTemplate.NOT_CHAIN_PRECEDENCE: evaluate_not_chain_precedence_rule,
    DeclareTemplate.NOT_CO_EXISTENCE: evaluate_not_co_existence_rule,
    DeclareTemplate.NOT_SUCCESSION: evaluate_not_succession_rule,
    DeclareTemplate.NOT_CHAIN_SUCCESSION: evaluate_not_chain_succession_rule,
}


def evaluate_constraint(
    case_id: str,
    trace_df: pd.DataFrame,
    constraint: DeclareConstraint,
) -> ConstraintResult:
    """Dispatch constraint evaluation to a template-specific evaluator function."""
    evaluator = _TEMPLATE_EVALUATORS.get(constraint.template)
    if evaluator is None:
        cid = (
            getattr(constraint, "id", None)
            or constraint.label
            or f"{constraint.template.value}:{constraint.activation}:{constraint.target}"
        )
        return ConstraintResult(
            case_id=case_id,
            constraint_id=cid,
            outcome=ConformanceOutcome.NOT_EVALUATED,
            violation_reason=f"Template not implemented: {constraint.template.value}",
        )
    return evaluator(case_id=case_id, trace_df=trace_df, constraint=constraint)


def check_log_conformance(
    event_log_df: pd.DataFrame,
    model: DeclareModel,
) -> list[TraceResult]:
    """Check an entire event log for conformance to a Declare process model.

    Evaluates all constraints in the model against each case/trace in the event log,
    aggregating results by case.

    Args:
        event_log_df: DataFrame with columns: case_id, activity, timestamp, and optional
                      data columns (itemid, value_num, value_raw, etc.). Must be grouped
                      by case_id for trace-level evaluation.
        model: DeclareModel containing constraints to check.

    Returns:
        List of TraceResult objects, one per unique case_id in event_log_df. Each
        TraceResult contains ConstraintResult objects for all evaluated constraints.
    """
    results: list[TraceResult] = []

    # Evaluate all constraints for each patient trace
    for case_id, trace in event_log_df.groupby("case_id"):
        trace_sorted = trace.sort_values("timestamp", kind="stable")
        # Evaluate each constraint against this case's trace
        constraint_results = [
            evaluate_constraint(case_id=str(case_id), trace_df=trace_sorted, constraint=c)
            for c in model.constraints
        ]
        results.append(TraceResult(case_id=str(case_id), constraint_results=constraint_results))

    return results
