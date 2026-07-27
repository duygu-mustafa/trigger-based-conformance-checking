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

def get_rule_binary(row: pd.Series, rule_id: str) -> float:
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
    """
    satisfied = str(row.get("mandatory_satisfied_constraints", "")).split(";") + \
                str(row.get("info_satisfied_constraints", "")).split(";")
    violated = str(row.get("mandatory_violated_constraints", "")).split(";") + \
               str(row.get("info_violated_constraints", "")).split(";")

    satisfied = [s for s in satisfied if s]
    violated = [v for v in violated if v]

    if rule_id in violated:
        return 1.0
    if rule_id in satisfied:
        return 0.0
    return np.nan

def build_case_level_table(df: pd.DataFrame) -> pd.DataFrame:
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
            case_data[rule_id] = get_rule_binary(row, rule_id)
            
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

if __name__ == "__main__":
    input_csv = Path("data/results/trigger_results.csv")
    if input_csv.exists():
        df = load_conformance_data(input_csv)
        print(f"Loaded {len(df)} trigger episodes.")
        
        # 1. Generate Case-Level Table
        df_cases = build_case_level_table(df)
        print(f"Created analysis table with {len(df_cases)} SBT cases.")
        
        # Identify rules from the columns of the case-level table
        exclude_cols = {"stay_id", "episode_index", "outcome", "next_outcome"}
        all_rules_list = sorted([col for col in df_cases.columns if col not in exclude_cols])

        inter_episode_rules = load_inter_episode_rules()
        print(f"Inter-episode rules (tested against next episode's outcome): {sorted(inter_episode_rules)}")

        # 2. Perform Statistical Analysis for each rule
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

            row = {
                "rule_name": rule_id,
                "outcome_variable": "next_episode" if is_inter else "same_episode",
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
                "used_continuity_correction": stats["continuity_correction"]
            }
            summary_rows.append(row)
            
        df_summary = pd.DataFrame(summary_rows)
        
        # # 3. Multiple Testing Correction (no longer applied — raw p-value used)
        # if not df_summary.empty:
        #     df_summary["p_bonf"] = np.minimum(df_summary["p_raw"] * len(df_summary), 1.0)
        #     _rej, p_fdr, _as1, _as2 = multipletests(df_summary["p_raw"], method="fdr_bh")
        #     df_summary["p_fdr"] = p_fdr
        #     df_summary["significant_bonf"] = df_summary["p_bonf"] < 0.05
        #     df_summary["significant_fdr"] = df_summary["p_fdr"] < 0.05
            
        # 4. Save Results
        output_table_path = Path("data/results/statistical_analysis_table.csv")
        df_cases.to_csv(output_table_path, index=False)
        
        output_summary_path = Path("data/results/statistical_results_summary.csv")
        df_summary.to_csv(output_summary_path, index=False)
        
        print(f"Analysis table saved to {output_table_path}")
        print(f"Statistical summary saved to {output_summary_path}")
        
        # Example output
        if not df_summary.empty:
            print("\nTop findings (by raw p-value):")
            print(df_summary.sort_values("p_raw").head(10)[["rule_name", "outcome_variable", "p_raw", "or", "n_censored"]])
        else:
            print("No rules to analyze.")
    else:
        print(f"Input file {input_csv} not found.")
