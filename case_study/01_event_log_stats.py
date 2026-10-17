"""Event-log characterisation for the MIMIC-IV SBT case study.

Aggregates the canonical event log with DuckDB (streaming, never fully loaded into
pandas), restricted to the stays that the conformance analysis actually covers, so
the log statistics and the conformance population describe the same cohort.

Usage:
    python case_study/01_event_log_stats.py [--force]

`--force` recomputes even when out/log_overview.json already exists.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import yaml

from config import (
    DECLARE_DIR,
    EPISODE_RESULTS,
    EVENT_LOG,
    OUT_DIR,
    ROOT,
    quantile_summary,
    save_fig,
    write_csv,
    write_json,
)

COHORT_CACHE = OUT_DIR / "cohort_stay_ids.parquet"
ACTIVITY_MAPPING = ROOT / "configs" / "activity_mapping.yaml"


def model_activities() -> set[str]:
    """Activity names the Declare models can reason about (activity_mapping.yaml keys)."""
    mapping = yaml.safe_load(ACTIVITY_MAPPING.read_text(encoding="utf-8")) or {}
    return set(mapping.get("mappings", {}).keys())


def build_cohort(con: duckdb.DuckDBPyConnection, force: bool) -> int:
    """Materialise the distinct stay_ids present in the episode results."""
    if COHORT_CACHE.exists() and not force:
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE cohort AS "
            f"SELECT * FROM read_parquet('{COHORT_CACHE.as_posix()}')"
        )
    else:
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE cohort AS "
            f"SELECT DISTINCT stay_id FROM read_csv('{EPISODE_RESULTS.as_posix()}', "
            f"header=true, sample_size=-1) WHERE stay_id IS NOT NULL"
        )
        con.execute(f"COPY cohort TO '{COHORT_CACHE.as_posix()}' (FORMAT PARQUET)")
    return con.execute("SELECT count(*) FROM cohort").fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    overview_path = OUT_DIR / "log_overview.json"
    if overview_path.exists() and not args.force:
        print(f"{overview_path} exists; skipping (use --force to recompute).")
        return

    if not EVENT_LOG.exists():
        raise SystemExit(f"Event log not found: {EVENT_LOG}")

    t0 = time.time()
    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")

    n_cohort_stays = build_cohort(con, args.force)
    print(f"Cohort: {n_cohort_stays:,} stays from {EPISODE_RESULTS.name}")

    log = f"read_parquet('{EVENT_LOG.as_posix()}')"
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW ev AS "
        f"SELECT e.* FROM {log} e SEMI JOIN cohort c ON e.stay_id = c.stay_id"
    )

    model_acts = sorted(model_activities())
    acts_sql = ", ".join("'" + a.replace("'", "''") + "'" for a in model_acts)

    # ---- overview -------------------------------------------------------
    print("Computing overview ...")
    row = con.execute(
        f"""
        SELECT count(*)                          AS n_events,
               count(DISTINCT case_id)           AS n_cases,
               count(DISTINCT stay_id)           AS n_stays,
               count(DISTINCT patient_id)        AS n_patients,
               count(DISTINCT activity)          AS n_activities,
               count(DISTINCT itemid)            AS n_itemids,
               count(DISTINCT source_table)      AS n_source_tables,
               min(timestamp)                    AS first_event,
               max(timestamp)                    AS last_event,
               sum(CASE WHEN activity IN ({acts_sql}) THEN 1 ELSE 0 END) AS n_model_events
        FROM ev
        """
    ).fetchdf().iloc[0]

    overview = {
        "source_log": str(EVENT_LOG),
        "cohort_source": str(EPISODE_RESULTS),
        "n_events": int(row["n_events"]),
        "n_cases": int(row["n_cases"]),
        "n_stays": int(row["n_stays"]),
        "n_patients": int(row["n_patients"]),
        "n_distinct_activities": int(row["n_activities"]),
        "n_distinct_itemids": int(row["n_itemids"]),
        "n_source_tables": int(row["n_source_tables"]),
        "first_event": str(row["first_event"]),
        "last_event": str(row["last_event"]),
        "span_years": round(
            (row["last_event"] - row["first_event"]).days / 365.25, 1
        ),
        "n_model_activity_events": int(row["n_model_events"]),
        "model_activity_share": float(row["n_model_events"]) / float(row["n_events"]),
        "n_model_activities_defined": len(model_acts),
    }

    # ---- activity frequency --------------------------------------------
    print("Computing activity frequency ...")
    act = con.execute(
        f"""
        WITH per_stay AS (
            SELECT activity, stay_id, count(*) AS n
            FROM ev GROUP BY 1, 2
        )
        SELECT activity,
               sum(n)                     AS n_events,
               count(DISTINCT stay_id)    AS n_stays_with_activity,
               median(n)                  AS median_per_stay,
               max(n)                     AS max_per_stay
        FROM per_stay GROUP BY 1 ORDER BY n_events DESC
        """
    ).fetchdf()
    act["share"] = act["n_events"] / overview["n_events"]
    act["stay_coverage"] = act["n_stays_with_activity"] / overview["n_stays"]
    act["is_model_activity"] = act["activity"].isin(model_acts)
    write_csv(act, "activity_frequency.csv")

    model_act = act[act["is_model_activity"]].copy()
    write_csv(model_act, "activity_frequency_model_only.csv")
    overview["n_model_activities_observed"] = int(model_act.shape[0])
    overview["model_activities_never_observed"] = sorted(
        set(model_acts) - set(model_act["activity"])
    )

    # ---- source tables ---------------------------------------------------
    print("Computing source-table distribution ...")
    src = con.execute(
        "SELECT source_table, count(*) AS n_events, count(DISTINCT itemid) AS n_itemids "
        "FROM ev GROUP BY 1 ORDER BY n_events DESC"
    ).fetchdf()
    src["share"] = src["n_events"] / overview["n_events"]
    write_csv(src, "source_table_distribution.csv")

    # ---- trace lengths ---------------------------------------------------
    print("Computing per-stay trace lengths ...")
    per_stay = con.execute(
        f"""
        SELECT stay_id,
               count(*)                    AS n_events,
               count(DISTINCT activity)    AS n_distinct_activities,
               sum(CASE WHEN activity IN ({acts_sql}) THEN 1 ELSE 0 END) AS n_model_events,
               min(timestamp)              AS first_event,
               max(timestamp)              AS last_event
        FROM ev GROUP BY stay_id
        """
    ).fetchdf()
    per_stay["stay_duration_hours"] = (
        per_stay["last_event"] - per_stay["first_event"]
    ).dt.total_seconds() / 3600.0
    write_csv(per_stay, "events_per_stay.csv")

    import pandas as pd

    quantiles = pd.DataFrame(
        [
            quantile_summary(per_stay["n_events"], "events_per_stay"),
            quantile_summary(per_stay["n_model_events"], "model_activity_events_per_stay"),
            quantile_summary(per_stay["n_distinct_activities"], "distinct_activities_per_stay"),
            quantile_summary(per_stay["stay_duration_hours"], "observed_stay_span_hours"),
        ]
    )
    write_csv(quantiles, "events_per_stay_quantiles.csv")

    write_json(overview, "log_overview.json")

    # ---- figures ---------------------------------------------------------
    top = act.head(20).iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, 5.5))
    colors = ["#1f77b4" if m else "#9ecae1" for m in top["is_model_activity"]]
    ax.barh(top["activity"], top["n_events"], color=colors)
    ax.set_xscale("log")
    ax.set_xlabel("Events (log scale)")
    ax.set_title("Top-20 activities by event count")
    ax.legend(
        handles=[
            plt.Rectangle((0, 0), 1, 1, color="#1f77b4", label="model activity"),
            plt.Rectangle((0, 0), 1, 1, color="#9ecae1", label="context activity"),
        ],
        loc="lower right",
    )
    save_fig(fig, "fig_activity_frequency")

    top_model = model_act.head(20).iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, 5.5))
    ax.barh(top_model["activity"], top_model["n_events"], color="#1f77b4")
    ax.set_xscale("log")
    ax.set_xlabel("Events (log scale)")
    ax.set_title("Model-relevant activities by event count")
    save_fig(fig, "fig_model_activity_frequency")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.8))
    ax1.hist(per_stay["n_events"], bins=60, color="#1f77b4")
    ax1.set_xscale("log")
    ax1.set_xlabel("Events per stay (log scale)")
    ax1.set_ylabel("Stays")
    ax1.set_title("Raw event volume per stay")
    positive = per_stay.loc[per_stay["n_model_events"] > 0, "n_model_events"]
    ax2.hist(positive, bins=60, color="#ff7f0e")
    ax2.set_xscale("log")
    ax2.set_xlabel("Model-activity events per stay (log scale)")
    ax2.set_title("Trace length seen by the checker")
    save_fig(fig, "fig_events_per_stay")

    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
