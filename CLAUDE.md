# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a master's thesis research pipeline for **SBT (Spontaneous Breathing Trial) Conformance Checking** against ICU patient data from the MIMIC-IV database. It implements three stages: raw data extraction → event log construction → declarative conformance checking, with a React frontend for visualization.

## Commands

### Python Backend

```bash
# Activate virtual environment first
source .venv/bin/activate

# Run tests
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_correlation_condition.py

# Run a single test
python -m pytest tests/test_correlation_condition.py::TestCorrelationCondition::test_next_day_correlation_condition_satisfied

# Stage 1: Extract raw ICU events (requires PostgreSQL connection to MIMIC-IV)
python database/materialize_all_icu_events.py --output icu_event_level_sbt.parquet

# Stage 2: Build canonical event log
python prepare_event_log.py --input icu_event_level_sbt.parquet --output icu_event_log_full.parquet --use-all-data

# Stage 2 (resumable long run via tmux/nohup)
./run_event_log_safe.sh --backup-every 200
./run_event_log_safe.sh --resume

# Stage 3: Run conformance checking (per-SBT episode)
python main_per_sbt.py

# Stage 3: Incremental conformance over checkpoint files
python main_per_sbt_checkpoints.py --checkpoint-dir data/icu_event_log_checkpoints --results-dir data/results/checkpoint_trigger_results
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # development server
npm run build    # production build
npm run preview  # preview production build
```

## Architecture

### Data Flow

```
MIMIC-IV DB → icu_event_level_sbt.parquet → icu_event_log_full.parquet → conformance_results.csv
                  (database/)                    (prepare_event_log.py            (main_per_sbt.py
                                                  + derive/pipeline.py)            + conformance/)
```

The canonical event log schema has columns: `case_id`, `activity`, `timestamp`, `source_table`, `itemid`, `value_raw`, `value_num`, `unit`, `attrs`, `patient_id`, `stay_id`.

### Key Modules

| Module | Responsibility |
|--------|---------------|
| `database/` | MIMIC-IV PostgreSQL extraction; credentials in `database/client.py` |
| `derive/pipeline.py` | Orchestrates weaning-frame derivation, SBT episode construction, invasive-vent gating, and activity mapping |
| `derive/sbt_episodes.py` | Reconstructs SBT episodes from ventilation status transitions |
| `derive/activity_emitter.py` | Maps raw events to semantic activity names via `configs/activity_mapping.yaml` |
| `conformance/checker.py` | Evaluates individual Declare constraints (LTL templates) against traces |
| `conformance/rules.py` | Loads Declare models from YAML; provides `build_*_model()` factories |
| `conformance/batch_runner.py` | Streams large Parquet/CSV files through DuckDB for per-stay batch processing |
| `conformance/weighted_scoring.py` | Fuzzy/Sugeno weighted conformance scoring (thesis formulas 3.1–3.5) |
| `conformance/results.py` | Data classes: `ConformanceOutcome`, `ConstraintResult`, `TraceResult` |
| `conformance/types.py` | Enum `DeclareTemplate` (all supported templates) and `DeclareConstraint` dataclass |
| `conformance/event_log_builder.py` | Normalizes DataFrames to canonical event-log schema |
| `configs/declare/` | YAML rule definitions grouped by category (readiness_assessment, failure_correction, sbt_execution) |
| `configs/activity_mapping.yaml` | Maps `(source_table, itemid, value_text)` tuples to semantic activity names |
| `frontend/` | React + Vite visualization app; loads pre-generated JSON from `frontend/public/data/` |

### Conformance Rule System

Rules are defined in `configs/declare/*.yaml`. Each rule specifies a `DeclareTemplate`, `activation` activity, optional `target` activity, optional `time_condition`, and optional `correlation_condition` / `activation_condition`. The checker supports 20+ Declare templates including `Response`, `Precedence`, `Chain*`, `Alternate*`, `Not*`, `Existence`, `End`, `Init`, etc.

Weights for Sugeno aggregation are configured in `configs/declare/weights.yaml`.

### Episode Segmentation

`main_per_sbt.py` splits each patient stay into trigger episodes bounded by `InvasiveVentilationStarted` events. Conformance is evaluated per episode (not per full stay), enabling multi-SBT analysis within a single ICU admission.

### Frontend Data Contract

The frontend reads static JSON files served from `frontend/public/data/`:
- `manifest.json` — list of available `case_id`s
- Per-case JSON files for timeline and summary views

The frontend has three views: **Summary** (population-level stats), **Timeline** (per-case investigation), and **Rules** (declarative rule reference).

## Configuration Files

- `configs/activity_mapping.yaml` — Primary mapping table; edit this to add new activities
- `configs/declare/readiness_assessment.yaml` — SBT readiness rules (RC-*)
- `configs/declare/failure_correction.yaml` — Post-failure intervention rules
- `configs/declare/sbt_execution.yaml` — SBT timing/execution rules (SBT-TM-*)
- `configs/declare/weights.yaml` — Per-constraint importance weights for Sugeno scoring
- `configs/item_dictionary.yaml` — MIMIC-IV `itemid` → human-readable label mapping
