"""Fit logistic regression models from a regression-ready CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from conformance.outcome_postprocessing import fit_constraint_outcome_logit, fit_score_outcome_logit


IGNORED_BASE_COLUMNS = {
    "stay_id",
    "case_id",
    "model_name",
    "score",
    "intubation_after_sbt",
    "hours_from_sbt_to_intubation",
    "first_sbt_started_ts",
    "first_intubation_after_sbt_ts",
}


def _parse_constraint_list(raw_value: object) -> set[str]:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return set()
    return {token.strip() for token in raw_value.split(";") if token.strip()}


def _build_constraint_feature_frame(
    df: pd.DataFrame,
    *,
    violated_col: str = "violated_constraints",
    satisfied_col: str = "satisfied_constraints",
) -> tuple[pd.DataFrame, list[str]]:
    required = {violated_col, satisfied_col}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing constraint columns: {sorted(missing)}")

    violated_sets = df[violated_col].map(_parse_constraint_list)
    satisfied_sets = df[satisfied_col].map(_parse_constraint_list)
    all_constraints = sorted(set().union(*violated_sets.tolist(), *satisfied_sets.tolist()))

    expanded = df.copy()
    feature_cols: list[str] = []
    for constraint_id in all_constraints:
        violated_name = f"violated__{constraint_id}"
        satisfied_name = f"satisfied__{constraint_id}"
        expanded[violated_name] = violated_sets.map(lambda items, cid=constraint_id: int(cid in items))
        expanded[satisfied_name] = satisfied_sets.map(lambda items, cid=constraint_id: int(cid in items))
        feature_cols.extend([violated_name, satisfied_name])

    return expanded, feature_cols


def _build_stay_level_constraint_matrix(
    tracking_df: pd.DataFrame,
    *,
    stay_id_col: str = "stay_id",
    case_id_col: str = "case_id",
    model_col: str = "model_name",
    score_col: str = "score",
    outcome_col: str = "y",
    violated_col: str = "violated_constraints",
    satisfied_col: str = "satisfied_constraints",
) -> tuple[pd.DataFrame, list[str]]:
    required = {
        stay_id_col,
        case_id_col,
        model_col,
        score_col,
        outcome_col,
        violated_col,
        satisfied_col,
    }
    missing = required - set(tracking_df.columns)
    if missing:
        raise ValueError(f"Tracking data is missing required columns: {sorted(missing)}")

    df = tracking_df.copy()

    # One row per stay/case for base outcome columns.
    base = (
        df.groupby([stay_id_col, case_id_col], as_index=False)
        .agg({outcome_col: "max"})
        .copy()
    )

    # Pivot score into one column per model (e.g., readiness_assessment, sbt_execution).
    score_wide = (
        df.pivot_table(
            index=[stay_id_col, case_id_col],
            columns=model_col,
            values=score_col,
            aggfunc="first",
        )
        .reset_index()
    )
    score_cols = [c for c in score_wide.columns if c not in {stay_id_col, case_id_col}]

    matrix = base.merge(score_wide, on=[stay_id_col, case_id_col], how="left")

    # Determine all model-specific constraint indicator columns first.
    model_constraints: dict[str, set[str]] = {}
    for _, row in df.iterrows():
        model = str(row[model_col])
        bucket = model_constraints.setdefault(model, set())
        bucket.update(_parse_constraint_list(row.get(violated_col)))
        bucket.update(_parse_constraint_list(row.get(satisfied_col)))

    constraint_cols: list[str] = []
    for model_name, cids in sorted(model_constraints.items()):
        for cid in sorted(cids):
            constraint_cols.append(f"{model_name}__violated__{cid}")
            constraint_cols.append(f"{model_name}__satisfied__{cid}")

    matrix = matrix.set_index([stay_id_col, case_id_col])
    for col in constraint_cols:
        matrix[col] = 0

    # Populate binary indicators from per-model constraint lists.
    for _, row in df.iterrows():
        key = (row[stay_id_col], row[case_id_col])
        model = str(row[model_col])

        for cid in _parse_constraint_list(row.get(violated_col)):
            col = f"{model}__violated__{cid}"
            if col in matrix.columns:
                matrix.at[key, col] = 1
        for cid in _parse_constraint_list(row.get(satisfied_col)):
            col = f"{model}__satisfied__{cid}"
            if col in matrix.columns:
                matrix.at[key, col] = 1

    matrix = matrix.reset_index()
    feature_cols = [*score_cols, *constraint_cols]
    return matrix, feature_cols


def _print_binary_metrics(y_true: pd.Series, y_prob: pd.Series, *, title: str) -> None:
    y_true = pd.Series(y_true).astype(int)
    y_prob = pd.Series(y_prob).astype(float)
    y_pred = (y_prob >= 0.5).astype(int)

    print(f"\n{title}")
    print(f"n={len(y_true)} positives={int(y_true.sum())} negatives={int((1 - y_true).sum())}")
    if y_true.nunique() < 2:
        print("Only one class present; ROC-AUC and PR-AUC are undefined.")
        return

    print(f"roc_auc={roc_auc_score(y_true, y_prob):.6f}")
    print(f"pr_auc={average_precision_score(y_true, y_prob):.6f}")
    print(f"brier={brier_score_loss(y_true, y_prob):.6f}")
    print(f"log_loss={log_loss(y_true, y_prob):.6f}")
    print(f"accuracy={accuracy_score(y_true, y_pred):.6f}")
    print(f"balanced_accuracy={balanced_accuracy_score(y_true, y_pred):.6f}")
    print(f"f1={f1_score(y_true, y_pred):.6f}")
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    print(f"confusion_matrix: tn={tn} fp={fp} fn={fn} tp={tp}")


def _cross_validated_probabilities(x: pd.DataFrame, y: pd.Series, *, class_weight: str | None = None) -> pd.Series | None:
    y = pd.Series(y).astype(int)
    class_counts = y.value_counts()
    if len(class_counts) < 2:
        return None

    n_splits = min(5, int(class_counts.min()))
    if n_splits < 2:
        return None

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    model = LogisticRegression(max_iter=5000, class_weight=class_weight)
    probs = cross_val_predict(model, x, y, cv=cv, method="predict_proba")[:, 1]
    return pd.Series(probs, index=y.index)


def _fit_regularized_logistic_model(x: pd.DataFrame, y: pd.Series, *, class_weight: str | None = None) -> pd.Series:
    model = LogisticRegression(max_iter=5000, class_weight=class_weight)
    model.fit(x, y.astype(int))
    coefficients = pd.Series(model.coef_[0], index=x.columns)
    coefficients.loc["const"] = float(model.intercept_[0])
    return coefficients


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit logistic regression on regression-ready CSV data.")
    parser.add_argument(
        "input_csv",
        type=Path,
        help="Path to logistic_regression_ready.csv",
    )
    parser.add_argument(
        "--outcome-col",
        type=str,
        default="y",
        help="Binary outcome column.",
    )
    parser.add_argument(
        "--case-id-col",
        type=str,
        default="case_id",
        help="Case identifier column.",
    )
    parser.add_argument(
        "--single-score-col",
        type=str,
        default=None,
        help="Optional single score column to fit formula (3.6). If omitted, the best available score-like column is used when obvious.",
    )
    parser.add_argument(
        "--all-features",
        action="store_true",
        help="Also fit a multi-feature model using all numeric feature columns.",
    )
    parser.add_argument(
        "--constraint-columns",
        action="store_true",
        help="Expand violated_constraints and satisfied_constraints into binary columns and fit a granular model.",
    )
    parser.add_argument(
        "--tracking-csv",
        type=Path,
        default=None,
        help="Optional weighted_scoring_trace_tracking.csv path to use for constraint-column regression.",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input_csv)

    if args.outcome_col not in df.columns:
        raise ValueError(f"Missing outcome column '{args.outcome_col}'.")

    score_candidates = [
        c
        for c in df.columns
        if c not in {args.case_id_col, args.outcome_col, "stay_id", "intubation_after_sbt", "hours_from_sbt_to_intubation", "first_sbt_started_ts", "first_intubation_after_sbt_ts"}
        and pd.api.types.is_numeric_dtype(df[c])
    ]

    if args.single_score_col is not None:
        score_col = args.single_score_col
    else:
        preferred = [c for c in ["score", "readiness_assessment", "sbt_execution"] if c in df.columns]
        score_col = preferred[0] if preferred else (score_candidates[0] if score_candidates else None)

    if score_col is None:
        raise ValueError("No numeric score column found for the single-score logistic regression.")

    score_frame = df[[args.case_id_col, score_col, args.outcome_col]].dropna().copy()
    score_fit = fit_score_outcome_logit(score_frame, score_col=score_col, outcome_col=args.outcome_col)

    print("Single-score logistic regression")
    print(score_fit.coefficients, flush=True)
    print(score_fit.p_values, flush=True)
    print(score_fit.odds_ratios, flush=True)
    if score_fit.pseudo_r2 is not None:
        print(f"pseudo_r2={score_fit.pseudo_r2:.6f}", flush=True)

    score_eval_x = score_frame[[score_col]]
    score_eval_y = score_frame[args.outcome_col]
    cv_prob = _cross_validated_probabilities(score_eval_x, score_eval_y)
    if cv_prob is not None:
        _print_binary_metrics(score_eval_y, cv_prob, title="Cross-validated metrics for single-score model")
    else:
        print("\nCross-validated metrics skipped: not enough class diversity.")

    if not args.all_features:
        if not args.constraint_columns:
            return

    feature_cols = [
        c
        for c in df.columns
        if c not in IGNORED_BASE_COLUMNS
        and pd.api.types.is_numeric_dtype(df[c])
    ]

    if args.all_features:
        if len(feature_cols) < 2:
            print("Skipping multi-feature regression: not enough numeric feature columns.", flush=True)
        else:
            wide = df[[*feature_cols, args.outcome_col, args.case_id_col]].dropna().copy()
            fit, empirical = fit_constraint_outcome_logit(wide, outcome_col=args.outcome_col, case_id_col=args.case_id_col)

            print("\nMulti-feature logistic regression", flush=True)
            print(fit.coefficients, flush=True)
            print(fit.p_values, flush=True)
            print(fit.odds_ratios, flush=True)
            if fit.pseudo_r2 is not None:
                print(f"pseudo_r2={fit.pseudo_r2:.6f}", flush=True)
            print("\nEmpirical weights", flush=True)
            print(empirical, flush=True)

            multi_x = wide[feature_cols]
            multi_y = wide[args.outcome_col]
            multi_cv_prob = _cross_validated_probabilities(multi_x, multi_y)
            if multi_cv_prob is not None:
                _print_binary_metrics(multi_y, multi_cv_prob, title="Cross-validated metrics for multi-feature model")
            else:
                print("Cross-validated metrics skipped: not enough class diversity.")

    if args.constraint_columns:
        constraint_source = df
        if not {"violated_constraints", "satisfied_constraints"}.issubset(df.columns):
            tracking_path = args.tracking_csv
            if tracking_path is None:
                tracking_path = args.input_csv.parent / "weighted_scoring_trace_tracking.csv"
            if not tracking_path.exists():
                raise ValueError(
                    "Input CSV must include violated_constraints and satisfied_constraints for --constraint-columns, "
                    f"or provide --tracking-csv. Looked for: {tracking_path}"
                )
            constraint_source = pd.read_csv(tracking_path)
            print(f"Using constraint tracking CSV: {tracking_path}", flush=True)

        stay_matrix, constraint_feature_cols = _build_stay_level_constraint_matrix(
            constraint_source,
            case_id_col=args.case_id_col,
            outcome_col=args.outcome_col,
        )
        constraint_rows = stay_matrix[[args.case_id_col, args.outcome_col, *constraint_feature_cols]].dropna().copy()
        constraint_x = constraint_rows[constraint_feature_cols]
        constraint_y = constraint_rows[args.outcome_col]

        print("\nConstraint-column logistic regression", flush=True)
        print(f"stays={len(constraint_rows)}", flush=True)
        print(f"constraint_and_score_features={len(constraint_feature_cols)}", flush=True)

        try:
            fit, empirical = fit_constraint_outcome_logit(
                constraint_rows[[args.case_id_col, *constraint_feature_cols, args.outcome_col]],
                outcome_col=args.outcome_col,
                case_id_col=args.case_id_col,
            )
            print(fit.coefficients, flush=True)
            print(fit.p_values, flush=True)
            print(fit.odds_ratios, flush=True)
            if fit.pseudo_r2 is not None:
                print(f"pseudo_r2={fit.pseudo_r2:.6f}", flush=True)
            print("\nEmpirical weights", flush=True)
            print(empirical.head(30), flush=True)
        except Exception as exc:
            print(f"statsmodels fit skipped for constraint model: {exc}", flush=True)
            coefficients = _fit_regularized_logistic_model(constraint_x, constraint_y, class_weight="balanced")
            ranked = coefficients.drop(labels=["const"], errors="ignore").sort_values(key=lambda s: s.abs(), ascending=False)
            print("Regularized coefficients (class_weight='balanced')", flush=True)
            print(coefficients.sort_values(key=lambda s: s.abs(), ascending=False).head(40), flush=True)
            print("Top absolute coefficients", flush=True)
            print(ranked.head(30), flush=True)

        constraint_cv_prob = _cross_validated_probabilities(constraint_x, constraint_y, class_weight="balanced")
        if constraint_cv_prob is not None:
            _print_binary_metrics(constraint_y, constraint_cv_prob, title="Cross-validated metrics for constraint-column model")
        else:
            print("Cross-validated metrics skipped: not enough class diversity.")


if __name__ == "__main__":
    main()