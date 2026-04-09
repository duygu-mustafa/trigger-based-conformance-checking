"""Outcome-based post-processing utilities for thesis formulas (3.6)-(3.7)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class LogisticFitSummary:
    """Compact container for key logistic regression outputs."""

    coefficients: pd.Series
    p_values: pd.Series
    odds_ratios: pd.Series
    pseudo_r2: float | None
    model: Any


def _require_columns(frame: pd.DataFrame, required: set[str], frame_name: str) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{frame_name} must include columns: {sorted(missing)}")


def build_score_outcome_frame(
    score_df: pd.DataFrame,
    reintubation_df: pd.DataFrame,
    *,
    case_id_col: str = "case_id",
    score_col: str = "score",
    outcome_flag_col: str = "intubation_after_sbt",
    outcome_col: str = "y",
) -> pd.DataFrame:
    """Merge a score table with a binary reintubation outcome.

    This returns a long, regression-ready table with one row per input score
    row and a binary target column derived from the reintubation summary.
    """

    _require_columns(score_df, {case_id_col, score_col}, "score_df")
    _require_columns(reintubation_df, {case_id_col, outcome_flag_col}, "reintubation_df")

    outcome = reintubation_df[[case_id_col, outcome_flag_col]].drop_duplicates(subset=[case_id_col]).copy()
    outcome[outcome_flag_col] = outcome[outcome_flag_col].fillna(False).astype(bool)

    merged = score_df.copy().merge(outcome, on=case_id_col, how="left")
    merged[outcome_flag_col] = merged[outcome_flag_col].fillna(False).astype(bool)
    merged[outcome_col] = merged[outcome_flag_col].astype(int)
    return merged


def build_model_level_regression_frame(
    tracking_df: pd.DataFrame,
    reintubation_df: pd.DataFrame,
    *,
    stay_id_col: str = "stay_id",
    case_id_col: str = "case_id",
    model_col: str = "model_name",
    score_col: str = "score",
    outcome_flag_col: str = "intubation_after_sbt",
    outcome_col: str = "y",
) -> pd.DataFrame:
    """Build a case-level wide table for logistic regression.

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
    outcome[outcome_col] = outcome[outcome_flag_col].astype(int)

    merged = score_wide.merge(outcome, on=case_id_col, how="left")
    merged[outcome_flag_col] = merged[outcome_flag_col].fillna(False).astype(bool)
    merged[outcome_col] = merged[outcome_col].fillna(0).astype(int)
    merged = merged.sort_values([stay_id_col, case_id_col]).reset_index(drop=True)
    return merged


def _fit_logit(y: pd.Series, x: pd.DataFrame) -> LogisticFitSummary:
    """Fit logistic regression with statsmodels and return key statistics."""

    try:
        import statsmodels.api as sm
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "statsmodels is required for outcome post-processing. Install with `pip install statsmodels`."
        ) from exc

    x_design = sm.add_constant(x, has_constant="add")
    model = sm.Logit(y.astype(float), x_design.astype(float))
    fitted = model.fit(disp=False)

    params = fitted.params
    pvalues = fitted.pvalues
    odds_ratios = np.exp(params)
    pseudo_r2 = None
    if hasattr(fitted, "prsquared"):
        pseudo_r2 = float(fitted.prsquared)

    return LogisticFitSummary(
        coefficients=params,
        p_values=pvalues,
        odds_ratios=odds_ratios,
        pseudo_r2=pseudo_r2,
        model=fitted,
    )


def fit_score_outcome_logit(
    score_outcome_df: pd.DataFrame,
    *,
    score_col: str = "score",
    outcome_col: str = "y",
) -> LogisticFitSummary:
    """Fit formula (3.6): y_t ~ Score(t).

    Returns beta_1 significance and other logistic diagnostics.
    """

    required = {score_col, outcome_col}
    if not required.issubset(score_outcome_df.columns):
        raise ValueError(f"score_outcome_df must include columns: {sorted(required)}")

    clean = score_outcome_df[[score_col, outcome_col]].dropna().copy()
    y = clean[outcome_col]
    x = clean[[score_col]]
    return _fit_logit(y=y, x=x)


def fit_constraint_outcome_logit(
    constraint_matrix_df: pd.DataFrame,
    *,
    outcome_col: str = "y",
    case_id_col: str | None = "case_id",
) -> tuple[LogisticFitSummary, pd.DataFrame]:
    """Fit formula (3.7): y_t ~ x_{t,c} and derive empirical weights.

    Empirical weights are based on absolute coefficients normalized to [0, 1].
    """

    if outcome_col not in constraint_matrix_df.columns:
        raise ValueError(f"constraint_matrix_df must include outcome column '{outcome_col}'.")

    excluded = {outcome_col}
    if case_id_col is not None and case_id_col in constraint_matrix_df.columns:
        excluded.add(case_id_col)

    feature_cols = [c for c in constraint_matrix_df.columns if c not in excluded]
    if not feature_cols:
        raise ValueError("No constraint feature columns found for formula (3.7).")

    clean = constraint_matrix_df[[*feature_cols, outcome_col]].dropna().copy()
    fit = _fit_logit(y=clean[outcome_col], x=clean[feature_cols])

    alpha = fit.coefficients.drop(labels=["const"], errors="ignore")
    alpha_abs = alpha.abs()
    alpha_max = float(alpha_abs.max()) if not alpha_abs.empty else 0.0
    if alpha_max > 0:
        w_emp_norm = alpha_abs / alpha_max
    else:
        w_emp_norm = alpha_abs.copy()

    empirical = pd.DataFrame(
        {
            "constraint_id": alpha.index,
            "alpha": alpha.values,
            "alpha_abs": alpha_abs.values,
            "w_emp": w_emp_norm.values,
            "p_value": fit.p_values.reindex(alpha.index).values,
            "odds_ratio": fit.odds_ratios.reindex(alpha.index).values,
        }
    )
    empirical = empirical.sort_values("alpha_abs", ascending=False).reset_index(drop=True)
    return fit, empirical


def compare_guideline_vs_empirical_weights(
    guideline_weights: pd.DataFrame,
    empirical_weights: pd.DataFrame,
    *,
    guideline_id_col: str = "constraint_id",
    guideline_weight_col: str = "w_max",
    empirical_id_col: str = "constraint_id",
    empirical_weight_col: str = "w_emp",
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compare guideline weights and empirical calibrated weights.

    Returns a joined table plus Pearson and Spearman correlations.
    """

    g_required = {guideline_id_col, guideline_weight_col}
    e_required = {empirical_id_col, empirical_weight_col}
    if not g_required.issubset(guideline_weights.columns):
        raise ValueError(f"guideline_weights missing columns: {sorted(g_required)}")
    if not e_required.issubset(empirical_weights.columns):
        raise ValueError(f"empirical_weights missing columns: {sorted(e_required)}")

    joined = guideline_weights[[guideline_id_col, guideline_weight_col]].merge(
        empirical_weights[[empirical_id_col, empirical_weight_col]],
        left_on=guideline_id_col,
        right_on=empirical_id_col,
        how="inner",
    )
    joined = joined.rename(
        columns={
            guideline_weight_col: "w_guideline",
            empirical_weight_col: "w_empirical",
        }
    )
    if empirical_id_col != guideline_id_col:
        joined = joined.drop(columns=[empirical_id_col])

    pearson = float(joined["w_guideline"].corr(joined["w_empirical"], method="pearson"))
    spearman = float(joined["w_guideline"].corr(joined["w_empirical"], method="spearman"))
    summary = {
        "n_constraints": float(len(joined)),
        "pearson_corr": pearson,
        "spearman_corr": spearman,
    }

    return joined.sort_values("w_guideline", ascending=False), summary


__all__ = [
    "LogisticFitSummary",
    "build_score_outcome_frame",
    "build_model_level_regression_frame",
    "fit_score_outcome_logit",
    "fit_constraint_outcome_logit",
    "compare_guideline_vs_empirical_weights",
]
