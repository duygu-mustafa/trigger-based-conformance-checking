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
    "fit_score_outcome_logit",
    "fit_constraint_outcome_logit",
    "compare_guideline_vs_empirical_weights",
]
