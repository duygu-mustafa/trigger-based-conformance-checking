# MIMIC-IV pipeline

This document explains how to rebuild the ICU weaning event log and the conformance results from
MIMIC-IV. For the framework overview and the Clinician Studio, see the [README](../README.md).

```
MIMIC-IV (PostgreSQL)
   │  database/materialize_all_icu_events.py
   ▼
raw events            data/final/mimic_raw_data.parquet
   │  prepare_event_log.py  →  derive/pipeline.py
   ▼
canonical event log   data/final/icu_event_log_full.parquet
   │  main.py  →  conformance/checker.py, statistics_R.r, derive/generate_summary.py
   ▼
episode results       data/results/full_results/trigger_results_full.csv
statistics            data/results/full_results/rule_statistics_R2.csv
frontend data         frontend/public/data/{summary,manifest,case_*}.json
```

Run all commands from the repository root with the virtual environment active
(`source .venv/bin/activate`, see `requirements.txt`). Everything under `data/` is generated and
gitignored.

## Prerequisites

- Python 3.14 with `pip install -r requirements.txt`
- R with `Rscript` on the `PATH` (only base R is used)
- PostgreSQL holding MIMIC-IV with the `mimiciv_icu`, `mimiciv_hosp` and `mimiciv_derived`
  (MIMIC-IV concepts) schemas. Connection settings come from `MIMIC_DB_USER`, `MIMIC_DB_PASSWORD`,
  `MIMIC_DB_HOST`, `MIMIC_DB_PORT` and `MIMIC_DB_NAME` (defaults: local server, database `mimiciv`).

## 1. Raw data extraction

```bash
python database/materialize_all_icu_events.py --output data/final/mimic_raw_data.parquet
```

This builds one long-form table in PostgreSQL (`mimiciv_derived.icu_event_level_all`) and exports it.
Its sources are:

- `chartevents`, `datetimeevents`, `inputevents`, `outputevents`, `procedureevents`,
  `ingredientevents`
- `labevents` and `prescriptions` (hormonal replacement drugs only)
- the derived concepts `norepinephrine_equivalent_dose`, `bg` (PaO₂/FiO₂, FiO₂, pH, hemoglobin) and
  `ventilator_setting`

Output columns: `source_table, stay_id, subject_id, event_time, charttime, starttime, endtime,
storetime, itemid, label, value_text, value_num, value_uom`.

| Option | Default | Meaning |
|---|---|---|
| `--output` | `data/final/mimic_raw_data.parquet` | `.parquet`, `.pq`, `.csv` or `.csv.gz` |
| `--icu-schema` / `--hosp-schema` / `--derived-schema` | `mimiciv_icu` / `mimiciv_hosp` / `mimiciv_derived` | Schema names |
| `--table-name` | `icu_event_level_all` | Name of the table created in the derived schema |
| `--keep-existing-table` | off | Reuse the table instead of rebuilding it |
| `--skip-indexes` | off | Do not create the `stay_id` / `event_time` / `itemid` indexes |
| `--sbt-only` | off | Keep only stays with a charted "SBT Started = Yes" (itemid 224715) |

### Death lookup

The outcome rule turns an SBT success into a failure when the patient dies within 48 h
(`derive/death_outcomes.py`). `main.py` reads the death times from `data/stay_deaths.parquet`.
Build that file once:

```bash
python -m derive.death_outcomes extract --raw <raw file with deathtime> --out data/stay_deaths.parquet
```

`extract` needs a raw file with `deathtime` and `died_in_hospital` columns (default
`data/icu_event_level_sbt.parquet`). The current extraction query above does not export these
columns.

## 2. Event log construction

```bash
python prepare_event_log.py \
  --input data/final/mimic_raw_data.parquet \
  --output data/final/icu_event_log_full.parquet \
  --use-all-data
```

Every selected stay goes through `derive.pipeline.raw_to_event_log`:

1. Explicit invasive-ventilation procedure rows (procedureevents 225792) are dropped.
   `InvasiveVentilationStarted` / `InvasiveVentilationEnded` are inferred from ventilator settings
   instead: one start at each onset of a Full Support mode, one end at the next switch away from it.
2. SBT episodes are reconstructed from ventilator-mode transitions (`derive/sbt_episodes.py`): a
   switch to a spontaneous or SBT mode starts an episode, and a lasting return to Full Support ends
   it, with a 120 min debounce. Each episode emits one `SBTStarted`.
3. Rows are mapped to activities through `configs/activity_mapping.yaml` and labelled through
   `configs/item_dictionary.yaml` (`derive/activity_emitter.py`). Derived activities are added:
   - `SBTFailed`: re-ventilation within 48 h after `SBTStarted`.
   - `SBTSucceeded`: otherwise; marked right-censored if the stay ends first.
   - Readiness criterion activities (`OxygenationMeasured`, `pHMeasured`, …): one per measurement.
   - `AnyFailureIntervention`: a copy of every post-failure intervention event.
4. The rows are normalized to the canonical schema (`conformance/event_log_builder.py`):
   `case_id, activity, timestamp, source_table, itemid, value_raw, value_num, unit, attrs,
   patient_id, stay_id`, ordered by case, timestamp, activity and itemid.

Stays are processed one at a time into a temporary DuckDB database, and progress is written to a
state file.

| Option | Default | Meaning |
|---|---|---|
| `--input` | `data/icu_event_level_sbt.parquet` | Raw events (Parquet or CSV) |
| `--output` | `data/icu_event_log_full.parquet` | Canonical event log (Parquet or CSV) |
| `--source-table-filter` | `ventilator_setting` | Candidate stays are those with at least one row from this `source_table`; pass `""` to use `--sample-source` instead |
| `--use-all-data` | off | Process all candidate stays instead of a random sample |
| `--sample-size` | all | Number of stays to sample |
| `--sample-seed` | `42` | Seed for the sample |
| `--sample-source` | `data/sbt_started_yes_stay_ids.parquet` | Candidate stay ids, used only when `--source-table-filter` is empty |
| `--pin-stay-id` | two example stays | Stays always included in a sample (repeatable) |
| `--memory-limit` | `4GB` | DuckDB memory limit |
| `--resume` | off | Continue an interrupted run from the state file and temporary database |
| `--state-file` | `<output>.state.json` | Checkpoint state |
| `--backup-every` | `200` | Export a checkpoint every N stays (0 disables) |
| `--backup-dir` | `<output dir>/<output stem>_checkpoints` | Checkpoint directory |
| `--seed-checkpoint` | none | Start from an existing checkpoint parquet |
| `--seed-skip-count` | from the checkpoint name | Number of candidate stays the seed checkpoint already covers |

The Studio's *Run Analysis* page reads a small sample built the same way:

```bash
python prepare_event_log.py --sample-size 1000 --output data/icu_event_log_sample.parquet
```

## 3. Conformance checking

```bash
python main.py --workers 4
```

For each stay, `main.py`:

1. Segments the stay into episodes. Each `InvasiveVentilationStarted` opens an episode, which ends at
   the next trigger. `--episode-window-hours` and `--episode-end-event` can close it earlier.
2. Builds the evaluation trace of each constraint: the episode, plus
   `context_window_pre_hours` of earlier events, plus target events up to `context_window_post_hours`
   after the episode.
3. Evaluates all 21 constraints of `configs/declare/readiness_assessment.yaml`, `sbt_execution.yaml`
   and `failure_correction.yaml` with `conformance/checker.py`. `INT-COMPOSITE-01` is the one
   exception: it is evaluated by `_evaluate_composite_for_attempt` at every SBT attempt after the
   first.
4. Reads the episode outcome from the derived `SBTFailed` / `SBTSucceeded` event and applies the
   death rule.

It writes one row per episode. Constraints are split into `mandatory_*` and `info_*` columns (the
`INT-*` rules other than `INT-COMPOSITE-01` go to `info_*`). Columns: `stay_id, episode_index,
episode_start, episode_end, sbt_attempt, sbt_start, sbt_end, sbt_outcome, next_sbt_outcome,
{mandatory,info}_{violated,satisfied,vacuous}_constraints, composite_interventions,
violation_forensics, satisfaction_forensics, …`.

After that, unless `--skip-postprocess` is given, it:

1. runs `Rscript statistics_R.r` → `statistical_analysis_table.csv`, `rule_statistics_R2.csv` (next
   to the output CSV);
2. exports `frontend/public/data/case_<stay_id>.json` and `manifest.json`;
3. builds `frontend/public/data/summary.json` (`derive/generate_summary.py`, which adds
   Bonferroni/FDR corrections);
4. copies the result files to `data/final/results/`.

| Option | Default | Meaning |
|---|---|---|
| `--input` | `data/final/icu_event_log_full.parquet` | Canonical event log |
| `--output` | `data/results/full_results/trigger_results_full.csv` | Episode results CSV |
| `--workers` | `4` | Worker processes (1 = sequential) |
| `--resume` | off | Skip stays already in the output CSV and append |
| `--episode-window-hours` | none | Fixed observation window per episode |
| `--episode-end-event` | none | Activity whose first occurrence ends the episode |
| `--no-segmentation` | off | Ablation: one evaluation trace per stay |
| `--stay-ids` | none | File with one stay id per line; restricts the run |
| `--skip-postprocess` | off | Stop after the CSV (no R statistics, export or summary) |
| `--postprocess-only` | off | Rerun only the post-processing on an existing `--output` |

### Long runs

The full cohort takes hours. The launchers in `scripts/` start the job in a detached `tmux` session
(or with `nohup`) and log to `logs/`:

```bash
scripts/run_event_log_safe.sh            # prepare_event_log.py --use-all-data, checkpoints every 200 stays
scripts/run_event_log_safe.sh --resume
scripts/run_conformance_safe.sh          # main.py
scripts/run_conformance_safe.sh --resume
tmux attach -t conformance               # or: tail -f logs/main_<timestamp>.log
```

Pass `--help` to a launcher to see all options; `--dry-run` prints the command without running it.
`scripts/run_benchmark_safe.sh` does the same for `evaluation/benchmark_scalability.py`.

### Outcome statistics outside the pipeline

`python derive/statistical_analysis.py` repeats the association analysis in Python. It reads
`data/results/full_results/trigger_results_full.csv`, runs both vacuity treatments (vacuous
episodes excluded, and pooled with satisfied), and writes the CSVs next to the input. The case-study
scripts build on it.

## Declare rule format

Rules live in `configs/declare/*.yaml` and are loaded by `conformance/rules.py`. For example:

```yaml
model:
  name: readiness_assessment
  data_conditions:
    ph_ok:
      title: "pH criterion met"
      expression: "items['ph_bg'] > 7.25"
  constraints:
    - id: RC-DP-02
      label: "pH criterion must be met at SBT start"
      template: PRECEDENCE            # any DeclareTemplate name (conformance/types.py)
      activation: SBTStarted
      target: pHMeasured
      target_selection: last          # any | earliest | latest (aliases: first, last)
      correlation_condition: ph_ok    # named data condition or inline expression
      context_window_pre_hours: 24    # evaluation context before the episode
      time_condition:
        min_hours: -24
        max_hours: 0
```

Other keys:

| Key | Meaning |
|---|---|
| `activation_condition` | Condition on the activation event |
| `context_window_post_hours` | Context window after the episode |
| `outcome_scope: next_episode` | Test the rule against the next episode's outcome |
| `*_display` | Human-readable labels for the Studio |

Conditions read item values through `items[<itemid>]` and can use the context variables listed in
`readiness_assessment.yaml`. `configs/declare/weights.yaml` holds importance scores that only the
optional weighted scoring (`conformance/weighted_scoring.py`) and the Studio's severity bars use.

## API reference (`api.py`)

The server runs at `http://localhost:8000`; the Vite dev server proxies `/api/*` to it.

| Endpoint | Description |
|---|---|
| `GET /api/rules` | Predefined rules as structured JSON (without `DISABLED_RULE_IDS`) |
| `GET /api/activities` | Activity names from `activity_mapping.yaml`, grouped by category |
| `GET /api/item_labels` | itemid → label lookup |
| `GET /api/item_search` | Search MIMIC-IV items by label (falls back to the item dictionary without a database) |
| `POST /api/query` | Preview a `SELECT` query on MIMIC-IV (read-only session, 10 s timeout) |
| `POST /api/run` | Start an analysis job on a sample of `data/icu_event_log_sample.parquet` |
| `GET /api/jobs/{id}` | Job status and result |
| `DELETE /api/jobs/{id}` | Cancel a job |
| `POST /api/upload_log` | Upload and parse an XES log (kept in memory) |
| `DELETE /api/upload_log/{id}` | Drop an uploaded log |
| `POST /api/run_uploaded` | Check custom rules on an uploaded log |
| `GET /api/case/{stay_id}` | Events of one stay from the sample event log |

## Tests

```bash
python -m pytest tests/          # checker semantics, target selection, pipeline sanity, XES upload
python -m pytest experimental/   # cross-checks against the experimental automata engine
```
