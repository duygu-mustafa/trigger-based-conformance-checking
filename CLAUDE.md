# CLAUDE.md

Master's thesis: Trigger-Based Declarative Conformance Checking (applied to SBT/weaning on MIMIC-IV).

- Read only the files directly relevant to the task. Don't explore speculatively.
- Prefer targeted file reads over broad codebase searches.
- Don't summarize work already visible in the conversation.

## Data Flow
```
MIMIC-IV → mimic_raw_data.parquet → icu_event_log_full.parquet → trigger_results_full.csv
            (database/)              (prepare_event_log.py      (main.py + conformance/
                                      + derive/pipeline.py)      + statistics_R.r)
```

Canonical schema: `case_id`, `activity`, `timestamp`, `source_table`, `itemid`, `value_raw`, `value_num`, `unit`, `attrs`, `patient_id`, `stay_id`.

## Key Modules
- `database/` — PostgreSQL extraction
- `derive/pipeline.py` — weaning-frame derivation, SBT episodes, activity mapping
- `derive/sbt_episodes.py` — SBT episodes from vent status transitions
- `derive/activity_emitter.py` — maps events to activities via `configs/activity_mapping.yaml`
- `conformance/checker.py` — evaluates Declare constraints against traces
- `conformance/rules.py` — loads Declare models from YAML
- `conformance/batch_runner.py` — DuckDB view over the event file, queried per stay
- `conformance/weighted_scoring.py` — optional Fuzzy/Sugeno weighted scoring (not in thesis method)
- `statistics_R.r` — outcome-association stats called by main.py
- `api.py` — FastAPI backend for the Clinician Studio
- `experimental/` — automata engine, not used by the pipeline
- `conformance/event_log_builder.py` — normalizes DataFrames to canonical schema
- `conformance/types.py` — `DeclareTemplate` enum, `DeclareConstraint` dataclass
- `frontend/` — React + Vite app (Clinician Studio); reads JSON from `frontend/public/data/`

## Configs
- `configs/activity_mapping.yaml` — event → activity mapping
- `configs/declare/readiness_assessment.yaml` — RC-* rules
- `configs/declare/failure_correction.yaml` — post-failure rules
- `configs/declare/sbt_execution.yaml` — SBT timing rules
- `configs/declare/weights.yaml` — importance weights (optional scoring, Studio severity bars)
- `configs/item_dictionary.yaml` — itemid → label mapping

## Episode Segmentation
`main.py` splits stays into episodes bounded by `InvasiveVentilationStarted`. Conformance per episode.

## Frontend
Clinician Studio pages: Upload Log, Rule Library, Rule Builder, Run Analysis, Results (Frequencies, Statistics, Patients, Insights). Serves `manifest.json`, `summary.json`, `insights.json` + per-case JSON from `frontend/public/data/`.

## Docs
`README.md` (overview + Studio), `docs/PIPELINE.md` (pipeline), `case_study/README.md`, `evaluation/README.md`, `experimental/README.md`.
