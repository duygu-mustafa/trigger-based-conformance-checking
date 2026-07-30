import pandas as pd
import numpy as np
import json
from pathlib import Path
from scipy.stats import fisher_exact
from statsmodels.stats.multitest import multipletests

def load_conformance_data(file_path: Path) -> pd.DataFrame:
    """Load the trigger-episode results."""
    return pd.read_csv(file_path)

def load_inter_episode_rules(
    config_path: Path = Path("configs/declare/failure_correction.yaml"),
) -> set[str]:
    """Rule IDs flagged `outcome_scope: next_episode` in the Declare config.

    These rules activate on SBTFailed, which is definitionally the same-episode
    outcome (circular). Their exposure is therefore tested against the *next*
    episode's outcome instead.
    """
    import yaml
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    constraints = data.get("constraints", data.get("model", {}).get("constraints", [])) or []
    return {
        str(c["id"])
        for c in constraints
        if isinstance(c, dict) and c.get("outcome_scope") == "next_episode" and c.get("id")
    }

def _binarize_label(x) -> float:
    """1 = Success, 0 = Failure, NaN = unknown/censored/no attempt.

    Substring matching mirrors classify_outcome() in statistics_R.r so both
    implementations classify pipeline labels ("Success", "Success
    (Right-Censored: Stay Ended)", "Failure (Reventilated <48h)") identically.
    """
    if pd.isnull(x):
        return np.nan
    label = str(x).lower()
    if "success" in label:
        return 1.0
    if "failure" in label:
        return 0.0
    return np.nan

def binarize_outcome(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert categorical outcomes to binary.
    1 = Success (No Revent <48h / Last State: SBT)
    0 = Failure (Reventilated <48h or Last State: Invasive Vent)

    Also binarizes `next_sbt_outcome` (outcome of episode i+1) into
    `next_outcome_binary` for inter-episode rules; NaN = censored
    (no subsequent episode, or no evaluable SBT in it).
    """
    df["outcome_binary"] = df["sbt_outcome"].apply(_binarize_label)
    if "next_sbt_outcome" in df.columns:
        df["next_outcome_binary"] = df["next_sbt_outcome"].apply(_binarize_label)
    else:
        df["next_outcome_binary"] = np.nan
    return df

def get_rule_binary(row: pd.Series, rule_id: str, pool_vacuous: bool = False) -> float:
    """
    Encode rule state to binary (1, 0, or NaN).

    For all rules:
    - 1: VIOLATED (activated, corrective action absent)
    - 0: SATISFIED (activated, corrective action present)
    - NaN: VACUOUS (never activated) or absent — excluded from the 2x2

    Vacuous episodes are excluded rather than pooled with satisfied: for a
    failure-activated rule (Response(SBTFailed, X)), vacuous means "no SBT
    failure occurred", a different population from "failure occurred and was
    corrected". Pooling them makes exposure a proxy for the outcome.

    pool_vacuous=True disables that differentiation: vacuous satisfactions are
    counted as satisfied (0) alongside activated satisfactions. Use to compare
    against the activations-only encoding.
    """
    satisfied = str(row.get("mandatory_satisfied_constraints", "")).split(";") + \
                str(row.get("info_satisfied_constraints", "")).split(";")
    violated = str(row.get("mandatory_violated_constraints", "")).split(";") + \
               str(row.get("info_violated_constraints", "")).split(";")
    vacuous = str(row.get("mandatory_vacuous_constraints", "")).split(";") + \
              str(row.get("info_vacuous_constraints", "")).split(";")

    satisfied = [s for s in satisfied if s]
    violated = [v for v in violated if v]
    vacuous = [v for v in vacuous if v]

    if rule_id in violated:
        return 1.0
    if rule_id in satisfied:
        return 0.0
    if pool_vacuous and rule_id in vacuous:
        return 0.0
    return np.nan

def build_case_level_table(df: pd.DataFrame, pool_vacuous: bool = False) -> pd.DataFrame:
    """Transform trace results to case-level analysis table."""
    # Filter to cases with an actual SBT attempt
    df_sbt = df[df["sbt_attempt"].notnull() & (df["sbt_attempt"] != "")].copy()
    
    df_sbt = binarize_outcome(df_sbt)
    
    # Identify all unique rules across both mandatory and info lists
    all_rules = set()
    for col in ["mandatory_violated_constraints", "mandatory_satisfied_constraints", 
                "info_violated_constraints", "info_satisfied_constraints",
                "mandatory_vacuous_constraints", "info_vacuous_constraints"]:
        if col in df_sbt.columns:
            # Ensure the column is treated as string before using .str accessor
            unique_vals = df_sbt[col].dropna().astype(str).str.split(";").explode().unique()
            all_rules.update(unique_vals)
    all_rules = {r for r in all_rules if r and r != "nan" and isinstance(r, str)}
    
    case_rows = []
    for _, row in df_sbt.iterrows():
        case_data = {
            "stay_id": row["stay_id"],
            "episode_index": row["episode_index"],
            "outcome": row["outcome_binary"],
            "next_outcome": row["next_outcome_binary"],
        }
        
        for rule_id in sorted(all_rules):
            case_data[rule_id] = get_rule_binary(row, rule_id, pool_vacuous)
            
        case_rows.append(case_data)
        
    return pd.DataFrame(case_rows)

def generate_contingency_table(df_cases: pd.DataFrame, rule_id: str, outcome_col: str = "outcome"):
    """
    Generate 2x2 table for a specific rule vs outcome.
    Outcome = 1 (Success - No Revent <48h) | Outcome = 0 (Failure)
    
    Interpretations:
    - Adherence (RC-DP): Rule=1 (Satisfied), Rule=0 (Violated)
        OR > 1: Adherence associated with Success
    - Safety (SBT-DP, INT): Rule=1 (Violated/Exposed), Rule=0 (Satisfied/Vacuous)
        OR > 1: Violation associated with Success (unlikely)
        OR < 1: Violation associated with Failure
        
    Contingency Table Structure:
                          Outcome=1 (Success) | Outcome=0 (Failure)
    Rule=1 (Satisfied/Exposed) | a                  | b
    Rule=0 (Violated/Unexposed)| c                  | d
    """
    # Drop rows where either rule or outcome is NaN. For inter-episode rules
    # (outcome_col="next_outcome") the NaN-drop is the censoring step: episodes
    # without a subsequent evaluable episode are excluded.
    valid = df_cases[[rule_id, outcome_col]].dropna()

    a = len(valid[(valid[rule_id] == 1) & (valid[outcome_col] == 1)])
    b = len(valid[(valid[rule_id] == 1) & (valid[outcome_col] == 0)])
    c = len(valid[(valid[rule_id] == 0) & (valid[outcome_col] == 1)])
    d = len(valid[(valid[rule_id] == 0) & (valid[outcome_col] == 0)])

    n_censored = int(df_cases[rule_id].notna().sum() - len(valid))
    return a, b, c, d, n_censored

def calculate_stats(a, b, c, d):
    """
    Calculate Fisher's Exact Test, Odds Ratio, Risk Ratio, and 95% CIs.
    Applies continuity correction (0.5) if any cell is zero for OR/RR and SE.
    """
    # 1. Fisher's Exact P-value (always exact)
    _odds, p_raw = fisher_exact([[a, b], [c, d]], alternative="two-sided")
    
    # Check for zero cells
    has_zero = (a == 0 or b == 0 or c == 0 or d == 0)
    
    # Apply continuity correction for effect sizes if needed
    ac, bc, cc, dc = (a + 0.5, b + 0.5, c + 0.5, d + 0.5) if has_zero else (a, b, c, d)
    
    # 2. Odds Ratio (OR)
    # OR = (a/b) / (c/d) = (ad) / (bc)
    denom = bc * cc
    if denom == 0:
        odds_ratio = np.inf
    else:
        odds_ratio = (ac * dc) / denom
    
    # OR Confidence Interval (Woolf's method)
    # SE(ln(OR)) = sqrt(1/a + 1/b + 1/c + 1/d)
    try:
        se_ln_or = np.sqrt(1/ac + 1/bc + 1/cc + 1/dc)
        ln_or = np.log(odds_ratio)
        or_ci_low = np.exp(ln_or - 1.96 * se_ln_or)
        or_ci_high = np.exp(ln_or + 1.96 * se_ln_or)
    except:
        or_ci_low, or_ci_high = np.nan, np.nan

    # 3. Risk Ratio (RR)
    # RR = [a/(a+b)] / [c/(c+d)]
    risk_exposed = ac / (ac + bc)
    risk_unexposed = cc / (cc + dc)
    if risk_unexposed == 0:
        risk_ratio = np.inf
    else:
        risk_ratio = risk_exposed / risk_unexposed
        
    # RR Confidence Interval
    # SE(ln(RR)) = sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d))
    try:
        se_ln_rr = np.sqrt(1/ac - 1/(ac+bc) + 1/cc - 1/(cc+dc))
        ln_rr = np.log(risk_ratio)
        rr_ci_low = np.exp(ln_rr - 1.96 * se_ln_rr)
        rr_ci_high = np.exp(ln_rr + 1.96 * se_ln_rr)
    except:
        rr_ci_low, rr_ci_high = np.nan, np.nan
        
    # 4. Expected Counts (for reporting/validation)
    n = a + b + c + d
    expected_a = ((a + b) * (a + c)) / n if n > 0 else 0
    
    return {
        "p_raw": p_raw,
        "or_point": odds_ratio,
        "or_ci_low": or_ci_low,
        "or_ci_high": or_ci_high,
        "rr_point": risk_ratio,
        "rr_ci_low": rr_ci_low,
        "rr_ci_high": rr_ci_high,
        "expected_a": expected_a,
        "continuity_correction": has_zero
    }

def load_constraint_labels(
    config_dir: Path = Path("configs/declare"),
) -> dict[str, str]:
    """Map constraint id -> human label from all Declare YAMLs (frontend 'Clinical Rule')."""
    import yaml
    labels: dict[str, str] = {}
    for cfg in config_dir.glob("*.yaml"):
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        constraints = data.get("constraints", data.get("model", {}).get("constraints", [])) or []
        for c in constraints:
            if isinstance(c, dict) and c.get("id"):
                labels[str(c["id"])] = str(c.get("label") or c.get("id"))
    return labels


def _classify(or_val, or_low, or_high, p) -> str:
    """Frontend 'Clinical Relevance': significant + CI wholly one side of 1."""
    if p is None or pd.isnull(p) or p >= 0.05:
        return "inconclusive"
    if pd.isnull(or_low) or pd.isnull(or_high):
        return "inconclusive"
    if or_val < 1 and or_high < 1:
        return "useful"      # violation tracks failure -> rule protective
    if or_val > 1 and or_low > 1:
        return "harmful"     # violation tracks success -> flag
    return "inconclusive"


def export_frontend_csv(df_summary: pd.DataFrame, labels: dict[str, str], out_path: Path) -> None:
    """CSV mirroring the frontend StatsDeepDive table, sorted by p-value."""
    def fmt_ci(v, lo, hi):
        if pd.isnull(v):
            return ""
        return f"{v:.2f} [{lo:.2f}, {hi:.2f}]" if not (pd.isnull(lo) or pd.isnull(hi)) else f"{v:.2f}"

    rows = []
    for _, r in df_summary.iterrows():
        rel = _classify(r["or"], r["or_ci_low"], r["or_ci_high"], r["p_raw"])
        rows.append({
            "clinical_rule": labels.get(r["rule_name"], r["rule_name"]),
            "constraint_id": r["rule_name"],
            "outcome_variable": r["outcome_variable"],
            "exposed_violated": int(r["n_exposed"]),
            "unexposed_satisfied": int(r["n_unexposed"]),
            "OR_95CI": fmt_ci(r["or"], r["or_ci_low"], r["or_ci_high"]),
            "RR_95CI": fmt_ci(r["rr"], r["rr_ci_low"], r["rr_ci_high"]),
            "p_value": f"{r['p_raw']:.2e}",
            "clinical_relevance": rel,
            "significant": r["p_raw"] < 0.05,
        })
    out = pd.DataFrame(rows).sort_values("p_value")
    out.to_csv(out_path, index=False)
    print(f"  frontend-style -> {out_path}")


def export_r_compatible_stats(df_summary: pd.DataFrame, out_path: Path) -> None:
    """Rewrite summary with the column names generate_summary.py / R expect.

    generate_summary reads fisher_p, or_low, or_high, rr_low, rr_high; our
    internal summary uses p_raw, or_ci_low/high, rr_ci_low/high. Rename so the
    frontend summary.json can be regenerated from this run.
    """
    out = df_summary.rename(columns={
        "p_raw": "fisher_p",
        "or_ci_low": "or_low", "or_ci_high": "or_high",
        "rr_ci_low": "rr_low", "rr_ci_high": "rr_high",
    })[[
        "rule_name", "outcome_variable", "n_censored", "n_exposed", "n_unexposed",
        "a", "b", "c", "d", "fisher_p", "or", "or_low", "or_high", "rr", "rr_low", "rr_high",
    ]]
    out.to_csv(out_path, index=False)
    print(f"  R/frontend-compatible stats -> {out_path}")


def run_analysis(df: pd.DataFrame, pool_vacuous: bool, inter_episode_rules: set[str],
                 out_table: Path, out_summary: Path) -> pd.DataFrame:
    """Build case table + per-rule stats for one vacuous-handling mode, write both CSVs."""
    df_cases = build_case_level_table(df, pool_vacuous=pool_vacuous)
    print(f"[{'pooled' if pool_vacuous else 'activations-only'}] "
          f"analysis table with {len(df_cases)} SBT cases.")

    exclude_cols = {"stay_id", "episode_index", "outcome", "next_outcome"}
    all_rules_list = sorted([col for col in df_cases.columns if col not in exclude_cols])

    summary_rows = []
    for rule_id in all_rules_list:
        is_inter = rule_id in inter_episode_rules
        outcome_col = "next_outcome" if is_inter else "outcome"
        a, b, c, d, n_censored = generate_contingency_table(df_cases, rule_id, outcome_col)
        n_exposed = a + b
        n_unexposed = c + d
        if (n_exposed + n_unexposed) == 0:
            continue
        stats = calculate_stats(a, b, c, d)
        summary_rows.append({
            "rule_name": rule_id,
            "outcome_variable": "next_episode" if is_inter else "same_episode",
            "vacuous_mode": "pooled" if pool_vacuous else "activations_only",
            "n_censored": n_censored,
            "n_exposed": n_exposed,
            "n_unexposed": n_unexposed,
            "a": a, "b": b, "c": c, "d": d,
            "expected_a": stats["expected_a"],
            "p_raw": stats["p_raw"],
            "or": stats["or_point"],
            "or_ci_low": stats["or_ci_low"],
            "or_ci_high": stats["or_ci_high"],
            "rr": stats["rr_point"],
            "rr_ci_low": stats["rr_ci_low"],
            "rr_ci_high": stats["rr_ci_high"],
            "used_continuity_correction": stats["continuity_correction"],
        })

    df_summary = pd.DataFrame(summary_rows)
    df_cases.to_csv(out_table, index=False)
    df_summary.to_csv(out_summary, index=False)
    print(f"  table   -> {out_table}")
    print(f"  summary -> {out_summary}")
    return df_summary


if __name__ == "__main__":
    input_csv = Path("data/results/full_results/trigger_results_full.csv")
    out_dir = input_csv.parent
    if not input_csv.exists():
        print(f"Input file {input_csv} not found.")
        raise SystemExit(1)

    df = load_conformance_data(input_csv)
    print(f"Loaded {len(df)} trigger episodes.")
    inter_episode_rules = load_inter_episode_rules()
    print(f"Inter-episode rules (tested against next episode's outcome): {sorted(inter_episode_rules)}")

    labels = load_constraint_labels()

    results = {}
    for pool, tag in [(False, "activations_only"), (True, "pooled")]:
        results[tag] = run_analysis(
            df, pool, inter_episode_rules,
            out_table=out_dir / f"statistical_analysis_table_{tag}.csv",
            out_summary=out_dir / f"statistical_results_summary_{tag}.csv",
        )

    # Frontend-style findings CSV for the activations-only run
    export_frontend_csv(
        results["activations_only"], labels,
        out_dir / "findings_frontend_activations_only.csv",
    )
    # R/frontend-compatible stats -> feed generate_summary.py --stats-csv
    export_r_compatible_stats(
        results["activations_only"],
        out_dir / "rule_statistics_activations_only.csv",
    )

    # Side-by-side comparison keyed on rule_name (OR under each mode)
    combined = pd.concat(results.values(), ignore_index=True)
    both_path = out_dir / "statistical_results_summary_both.csv"
    combined.to_csv(both_path, index=False)
    print(f"  combined (both modes, long form) -> {both_path}")

    if not combined.empty:
        pivot = combined.pivot_table(
            index=["rule_name", "outcome_variable"], columns="vacuous_mode",
            values=["or", "p_raw", "n_exposed"], aggfunc="first")
        print("\nSide-by-side (OR / p_raw / n_exposed per mode):")
        print(pivot.to_string())
