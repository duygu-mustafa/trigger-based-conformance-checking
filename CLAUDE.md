# CLAUDE.md

Master's thesis: SBT Conformance Checking on MIMIC-IV.

- Read only the files directly relevant to the task. Don't explore speculatively.
- Prefer targeted file reads over broad codebase searches.
- Don't summarize work already visible in the conversation.

## Data Flow
```
MIMIC-IV → icu_event_level_sbt.parquet → icu_event_log_full.parquet → conformance_results.csv
             (database/)                    (prepare_event_log.py      (main_per_sbt.py
                                             + derive/pipeline.py)      + conformance/)
```

Canonical schema: `case_id`, `activity`, `timestamp`, `source_table`, `itemid`, `value_raw`, `value_num`, `unit`, `attrs`, `patient_id`, `stay_id`.

## Key Modules
- `database/` — PostgreSQL extraction
- `derive/pipeline.py` — weaning-frame derivation, SBT episodes, activity mapping
- `derive/sbt_episodes.py` — SBT episodes from vent status transitions
- `derive/activity_emitter.py` — maps events to activities via `configs/activity_mapping.yaml`
- `conformance/checker.py` — evaluates Declare constraints against traces
- `conformance/rules.py` — loads Declare models from YAML
- `conformance/batch_runner.py` — DuckDB streaming per-stay batch processing
- `conformance/weighted_scoring.py` — Fuzzy/Sugeno weighted scoring
- `conformance/event_log_builder.py` — normalizes DataFrames to canonical schema
- `conformance/types.py` — `DeclareTemplate` enum, `DeclareConstraint` dataclass
- `frontend/` — React + Vite app; reads JSON from `frontend/public/data/`

## Configs
- `configs/activity_mapping.yaml` — event → activity mapping
- `configs/declare/readiness_assessment.yaml` — RC-* rules
- `configs/declare/failure_correction.yaml` — post-failure rules
- `configs/declare/sbt_execution.yaml` — SBT timing rules
- `configs/declare/weights.yaml` — Sugeno importance weights
- `configs/item_dictionary.yaml` — itemid → label mapping

## Episode Segmentation
`main_per_sbt.py` splits stays into episodes bounded by `InvasiveVentilationStarted`. Conformance per episode.

## Frontend
Three views: Summary (population stats), Timeline (per-case), Rules (reference). Serves `manifest.json` + per-case JSON from `frontend/public/data/`.
