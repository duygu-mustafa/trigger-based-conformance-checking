"""Outcome-based post-processing utilities."""

from __future__ import annotations

import pandas as pd


def _require_columns(frame: pd.DataFrame, required: set[str], frame_name: str) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{frame_name} must include columns: {sorted(missing)}")


def build_model_level_summary_frame(
    tracking_df: pd.DataFrame,
    reintubation_df: pd.DataFrame,
    *,
    stay_id_col: str = "stay_id",
    case_id_col: str = "case_id",
    model_col: str = "model_name",
    score_col: str = "score",
    outcome_flag_col: str = "intubation_after_sbt",
) -> pd.DataFrame:
    """Build a case-level wide table for analysis.

    The output contains one row per stay/case with a score column per model,
    plus the binary reintubation label and the first observed time-to-reintubation.
    """

    required_tracking = {stay_id_col, case_id_col, model_col, score_col}
    _require_columns(tracking_df, required_tracking, "tracking_df")
    _require_columns(reintubation_df, {case_id_col, outcome_flag_col}, "reintubation_df")

    base = tracking_df[[stay_id_col, case_id_col, model_col, score_col]].drop_duplicates().copy()
    score_wide = (
        base.pivot_table(
            index=[stay_id_col, case_id_col],
            columns=model_col,
            values=score_col,
            aggfunc="first",
        )
        .reset_index()
    )

    outcome_cols = [case_id_col, outcome_flag_col]
    if "hours_from_sbt_to_intubation" in reintubation_df.columns:
        outcome_cols.append("hours_from_sbt_to_intubation")
    if "first_sbt_started_ts" in reintubation_df.columns:
        outcome_cols.append("first_sbt_started_ts")
    if "first_intubation_after_sbt_ts" in reintubation_df.columns:
        outcome_cols.append("first_intubation_after_sbt_ts")

    outcome = reintubation_df[outcome_cols].drop_duplicates(subset=[case_id_col]).copy()
    outcome[outcome_flag_col] = outcome[outcome_flag_col].fillna(False).astype(bool)

    merged = score_wide.merge(outcome, on=case_id_col, how="left")
    merged[outcome_flag_col] = merged[outcome_flag_col].fillna(False).astype(bool)
    merged = merged.sort_values([stay_id_col, case_id_col]).reset_index(drop=True)
    return merged


__all__ = [
    "build_model_level_summary_frame",
]

