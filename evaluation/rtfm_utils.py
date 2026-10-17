"""Helpers for running the conformance pipeline on the Road Traffic Fine
Management Process (RTFM) event log.

This module adapts a public, non-clinical event log to the interfaces the SBT
pipeline already exposes. Two conventions are worth stating up front:

1. Wide event log. ``conformance/checker.py`` exposes each event row's own
   attribute columns as ``items[...]`` when the trace has **no** ``itemid``
   column (see ``_evaluate_data_condition_status``). The RTFM log is therefore
   passed through as-is -- ``case_id``, ``activity``, ``timestamp`` plus the XES
   attributes -- and must *not* be run through
   ``conformance.event_log_builder.build_event_log()``, which would add an
   ``itemid`` column and disable that path.

2. Column names. ``derive/statistical_analysis.py`` reads a fixed set of column
   names (``stay_id``, ``sbt_attempt``, ``sbt_outcome``,
   ``mandatory_*_constraints``, ...). Those names are reused verbatim here so
   the statistical analysis needs no changes; in this domain they carry
   fine/case semantics rather than ICU-stay semantics.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

CREATE_FINE = "Create Fine"
SEND_FINE = "Send Fine"
PAYMENT = "Payment"
ADD_PENALTY = "Add penalty"
CREDIT_COLLECTION = "Send for Credit Collection"

# Tolerance when comparing paid vs. due, in currency units.
PAYMENT_EPSILON = 0.01


def build_trigger_episodes(
    df_full: pd.DataFrame,
    trigger_activity: str,
    window_hours: float | None = None,
    end_event: str | None = None,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Segment a trace into episodes per method.tex Definition (episode).

    Horizon = earliest of three candidates: next trigger t_next (fallback,
    always applies), fixed window t_Delta (if window_hours set), end-event
    t_phi (first `end_event` strictly after the trigger, if set). Both
    optional boundaries default off -> fallback-only behavior.
    t_next and t_Delta are exclusive; t_phi is inclusive, so the end event
    belongs to the episode it closes. The returned end is always exclusive.

    Generalised copy of ``main._build_trigger_episodes``
    (main.py:68), which hardcodes ``InvasiveVentilationStarted`` as the
    trigger. Copied rather than imported because importing ``main``
    pulls in ``derive.pipeline`` and asserts the MIMIC activity mapping, none of
    which applies here. Keep the two in sync if the segmentation semantics
    change.
    """
    triggers = (
        df_full[df_full["activity"] == trigger_activity]
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    if triggers.empty:
        return []

    trace_end_exclusive = df_full.iloc[-1]["timestamp"] + pd.Timedelta(seconds=1)
    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for idx, row in triggers.iterrows():
        start_ts = row["timestamp"]
        t_next = (
            triggers.iloc[idx + 1]["timestamp"]
            if idx + 1 < len(triggers)
            else trace_end_exclusive
        )
        candidates = [t_next]
        if window_hours is not None:
            candidates.append(start_ts + pd.Timedelta(hours=window_hours))
        if end_event is not None:
            ev = df_full[
                (df_full["activity"] == end_event) & (df_full["timestamp"] > start_ts)
            ]["timestamp"]
            if not ev.empty:
                # Inclusive t_phi as an exclusive bound; t_next still wins a tie.
                candidates.append(ev.min() + pd.Timedelta(1, "ns"))
        windows.append((start_ts, min(candidates)))
    return windows


def compute_segmentation_metrics(
    log: pd.DataFrame,
    trigger_activity: str,
    return_distributions: bool = False,
) -> dict:
    """Descriptive segmentation metrics for one candidate trigger activity.

    Quantifies what choosing `trigger_activity` as the episode trigger does to
    the analysable data, without running conformance checking:

    * coverage — cases lacking the trigger yield zero episodes and drop out;
    * granularity — episodes per case and episode size;
    * prefix loss — events before the first trigger fall outside every window;
    * same-day collapse — RTFM timestamps have day resolution, so repeated
      triggers on one date collapse to a single episode boundary
      (``build_trigger_episodes`` deduplicates on timestamp);
    * label validity — :func:`derive_episode_outcome` reads the amount owed
      from the episode's own ``Create Fine`` row; episodes without one get
      ``due = 0 + expenses`` and bias toward "Success".

    Returns a flat dict of scalars (one comparison-table row per trigger).
    With ``return_distributions=True`` the dict additionally carries the raw
    per-case episode counts and per-episode event counts under ``_dist_*``
    keys (numpy arrays, for plots; pop them before tabulating).
    """
    import numpy as np

    n_cases_total = log["case_id"].nunique()
    n_events_total = len(log)

    eps_per_case: list[int] = []
    ep_event_counts: list[int] = []
    ep_duration_days: list[float] = []
    events_in_covered_cases = 0
    events_covered = 0
    collapsed_triggers = 0
    outcome_counts = {"Success": 0, "Failure": 0}
    eps_without_create_fine = 0

    for _, trace in log.groupby("case_id", sort=False):
        trace = trace.sort_values("timestamp")
        trigger_rows = trace[trace["activity"] == trigger_activity]
        if trigger_rows.empty:
            continue
        collapsed_triggers += len(trigger_rows) - trigger_rows["timestamp"].nunique()
        windows = build_trigger_episodes(trace, trigger_activity)
        events_in_covered_cases += len(trace)

        n_eps_this_case = 0
        for start_ts, end_ts in windows:
            episode = trace[
                (trace["timestamp"] >= start_ts) & (trace["timestamp"] < end_ts)
            ]
            if episode.empty:
                continue
            n_eps_this_case += 1
            ep_event_counts.append(len(episode))
            ep_duration_days.append(
                (episode["timestamp"].max() - start_ts) / pd.Timedelta(days=1)
            )
            events_covered += len(episode)
            label, _ = derive_episode_outcome(episode)
            outcome_counts[label] = outcome_counts.get(label, 0) + 1
            if not (episode["activity"] == CREATE_FINE).any():
                eps_without_create_fine += 1
        eps_per_case.append(n_eps_this_case)

    n_covered = len(eps_per_case)
    n_episodes = len(ep_event_counts)
    eps_arr = np.array(eps_per_case) if eps_per_case else np.array([0])
    size_arr = np.array(ep_event_counts) if ep_event_counts else np.array([0])
    dur_arr = np.array(ep_duration_days) if ep_duration_days else np.array([0.0])
    n_labeled = sum(outcome_counts.values())

    metrics = {
        "trigger": trigger_activity,
        "n_cases_total": n_cases_total,
        "n_cases_covered": n_covered,
        "case_coverage": n_covered / n_cases_total if n_cases_total else 0.0,
        "n_episodes": n_episodes,
        "eps_per_case_mean": float(eps_arr.mean()),
        "eps_per_case_median": float(np.median(eps_arr)),
        "eps_per_case_max": int(eps_arr.max()),
        "multi_episode_case_share": float((eps_arr > 1).mean()),
        "ep_events_mean": float(size_arr.mean()),
        "ep_events_median": float(np.median(size_arr)),
        "ep_events_p90": float(np.percentile(size_arr, 90)),
        "ep_duration_days_mean": float(dur_arr.mean()),
        "ep_duration_days_median": float(np.median(dur_arr)),
        "event_coverage": (
            events_covered / events_in_covered_cases if events_in_covered_cases else 0.0
        ),
        "prefix_loss": (
            1 - events_covered / events_in_covered_cases
            if events_in_covered_cases
            else 0.0
        ),
        "events_lost_to_dropped_cases": n_events_total - events_in_covered_cases,
        "same_day_collapsed_triggers": collapsed_triggers,
        "success_share": (
            outcome_counts.get("Success", 0) / n_labeled if n_labeled else 0.0
        ),
        "eps_without_create_fine": eps_without_create_fine,
        "eps_without_create_fine_share": (
            eps_without_create_fine / n_episodes if n_episodes else 0.0
        ),
    }
    if return_distributions:
        metrics["_dist_eps_per_case"] = eps_arr
        metrics["_dist_ep_events"] = size_arr
    return metrics


def _numeric(episode_df: pd.DataFrame, column: str) -> pd.Series:
    """Return a column as floats, or an empty float series if absent."""
    if column not in episode_df.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(episode_df[column], errors="coerce").dropna()


def _first_ts(episode_df: pd.DataFrame, activity: str) -> pd.Timestamp | None:
    rows = episode_df[episode_df["activity"] == activity]
    return rows["timestamp"].min() if not rows.empty else None


def _last_ts(episode_df: pd.DataFrame, activity: str) -> pd.Timestamp | None:
    rows = episode_df[episode_df["activity"] == activity]
    return rows["timestamp"].max() if not rows.empty else None


def derive_episode_outcome(episode_df: pd.DataFrame) -> tuple[str, dict]:
    """Classify an episode as a good ("Success") or bad ("Failure") outcome.

    An episode is good when the full amount owed was paid *in time*, which the
    process signals through its own escalation events rather than an assumed
    statutory deadline:

        good = paid >= due
               AND (no 'Add penalty', or the last payment preceded it)
               AND no 'Send for Credit Collection'

    Two attribute quirks of the RTFM log drive the arithmetic:

    * ``Add penalty`` **rewrites** ``amount`` to the penalised total, so the
      amount owed is read from the ``Create Fine`` event only, plus the
      ``expense`` booked on ``Send Fine``.
    * ``totalPaymentAmount`` is *cumulative* across payments -- take its max,
      never its sum. ``paymentAmount`` is per-event and is summed, and is used
      only as a fallback for traces that carry no ``totalPaymentAmount``.

    Returns:
        (label, details) where label is exactly "Success" or "Failure" --
        ``derive/statistical_analysis.py:_binarize_label`` substring-matches
        those words -- and details carries the intermediate quantities for
        debugging.
    """
    create_rows = episode_df[episode_df["activity"] == CREATE_FINE]
    base_amount = float(_numeric(create_rows, "amount").iloc[0]) if not _numeric(create_rows, "amount").empty else 0.0
    expense = float(_numeric(episode_df, "expense").sum())
    due = base_amount + expense

    total_paid = _numeric(episode_df, "totalPaymentAmount")
    per_payment = _numeric(episode_df, "paymentAmount")
    if not total_paid.empty and total_paid.max() > 0:
        paid = float(total_paid.max())
    else:
        paid = float(per_payment.sum())

    penalty_ts = _first_ts(episode_df, ADD_PENALTY)
    last_pay_ts = _last_ts(episode_df, PAYMENT)
    credit_collection = bool((episode_df["activity"] == CREDIT_COLLECTION).any())

    paid_in_full = paid >= due - PAYMENT_EPSILON
    paid_before_penalty = penalty_ts is None or (
        last_pay_ts is not None and last_pay_ts < penalty_ts
    )
    good = paid_in_full and paid_before_penalty and not credit_collection

    details = {
        "amount_due": due,
        "amount_paid": paid,
        "paid_in_full": paid_in_full,
        "paid_before_penalty": paid_before_penalty,
        "credit_collection": credit_collection,
        "penalty_ts": penalty_ts,
        "last_payment_ts": last_pay_ts,
    }
    return ("Success" if good else "Failure"), details


def load_severity_map(model_path: str | Path) -> dict[str, str]:
    """Map constraint id -> "mandatory" | "informational" from the model YAML.

    ``severity`` is not part of the Declare schema; ``conformance.rules``
    ignores unknown keys, so it rides along in the same file and is read back
    here to split constraints across the mandatory_/info_ result columns.
    """
    with Path(model_path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    constraints = data.get("constraints", data.get("model", {}).get("constraints", [])) or []
    return {
        str(c["id"]): str(c.get("severity") or "mandatory")
        for c in constraints
        if isinstance(c, dict) and c.get("id")
    }


def to_results_rows(
    case_id: str,
    episode_results: list[dict],
    severity_map: dict[str, str],
) -> list[dict]:
    """Flatten per-episode conformance results into analysis-ready rows.

    Args:
        case_id: The RTFM case identifier (one fine).
        episode_results: One dict per episode, in chronological order, with
            keys ``start``, ``end``, ``outcome`` (the "Success"/"Failure" label),
            ``details`` (from :func:`derive_episode_outcome`) and ``results``
            (a list of ``ConstraintResult``).
        severity_map: From :func:`load_severity_map`.

    Returns:
        One row per episode using the column contract that
        ``derive.statistical_analysis.build_case_level_table`` reads.
    """
    rows: list[dict] = []
    for idx, episode in enumerate(episode_results):
        buckets: dict[tuple[str, str], list[str]] = {
            (severity, outcome): []
            for severity in ("mandatory", "info")
            for outcome in ("violated", "satisfied", "vacuous")
        }
        for result in episode["results"]:
            outcome = result.outcome.value
            if outcome not in ("violated", "satisfied", "vacuous"):
                continue
            severity = severity_map.get(result.constraint_id, "mandatory")
            key = "info" if severity == "informational" else "mandatory"
            buckets[(key, outcome)].append(result.constraint_id)

        next_outcome = (
            episode_results[idx + 1]["outcome"] if idx + 1 < len(episode_results) else ""
        )
        details = episode["details"]
        rows.append(
            {
                "stay_id": case_id,
                "episode_index": idx,
                "episode_start": episode["start"],
                "episode_end": episode["end"],
                # Non-null marker: build_case_level_table filters on this column
                # to keep only episodes where the studied procedure occurred.
                # Every RTFM episode qualifies by construction.
                "sbt_attempt": 1,
                "sbt_outcome": episode["outcome"],
                "next_sbt_outcome": next_outcome,
                "mandatory_violated_constraints": ";".join(buckets[("mandatory", "violated")]),
                "mandatory_satisfied_constraints": ";".join(buckets[("mandatory", "satisfied")]),
                "mandatory_vacuous_constraints": ";".join(buckets[("mandatory", "vacuous")]),
                "info_violated_constraints": ";".join(buckets[("info", "violated")]),
                "info_satisfied_constraints": ";".join(buckets[("info", "satisfied")]),
                "info_vacuous_constraints": ";".join(buckets[("info", "vacuous")]),
                "amount_due": details["amount_due"],
                "amount_paid": details["amount_paid"],
                "paid_in_full": details["paid_in_full"],
                "paid_before_penalty": details["paid_before_penalty"],
                "credit_collection": details["credit_collection"],
            }
        )
    return rows
