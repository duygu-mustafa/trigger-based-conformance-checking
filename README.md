# Master Thesis: SBT Conformance Testing Pipeline

This repository implements a complete pipeline for deriving Spontaneous Breathing Trial (SBT) events from ICU data and measuring conformance to a set of declarative rules.

## Workflow Overview

The process has three main stages:

1. **Raw Data Extraction** — Fetch ICU events from the MIMIC-IV database
2. **Event Log Construction** — Build a canonical event log with automatic SBT derivation and conformance gates
3. **Conformance Checking** — Run declarative rules against the event log and compute metrics

---

## 1. Raw Data Extraction

```bash
python database/materialize_all_icu_events.py --output icu_event_level_sbt.parquet
```

### What This Does
- Connects to the MIMIC-IV PostgreSQL database
- Queries multiple event tables: `chartevents`, `datetimeevents`, `ingredientevents`, `inputevents`, `outputevents`, `procedureevents`
- Filters for ICU stays that have at least one documented SBT candidate (derived weaning events)
- Normalizes all raw events into a consistent schema with columns: `source_table`, `itemid`, `event_time`, `value_text`, `value_num`, `value_uom`, `charttime`, `starttime`, `endtime`, `case_id`, `stay_id`, `subject_id`
- Exports to Parquet for efficient downstream processing

### Requirements
- Active PostgreSQL connection to MIMIC-IV (credentials in `database/client.py`)
- `configs/item_dictionary.yaml` — Mapping of MIMIC-IV item IDs to semantic labels

---

## 2. Event Log Construction

### Purpose
Transform raw ICU events into a canonical event log with automatic SBT derivation and conformance-aware gates.

### Key Features
- **Automatic SBT Derivation** — Reconstructs SBT episodes from raw ventilator settings and transitions
- **Invasive Ventilation Gate** — Ensures SBT start events only appear after invasive ventilation has begun
- **Activity Mapping** — Maps raw events to semantic activities using declarative configuration

```bash
python prepare_event_log.py \
  --input icu_event_level_sbt.parquet \
  --output icu_event_log.parquet \
  --sample-source sbt_started_yes_stay_ids.parquet \
  --sample-size 1000 \
  --sample-seed 42
```

### Arguments
| Argument | Default | Description |
|----------|---------|-------------|
| `--input` | `icu_event_level_sbt.parquet` | Raw ICU events (Parquet or CSV) |
| `--output` | `icu_event_log.parquet` | Output canonical event log (Parquet or CSV) |
| `--sample-source` | `sbt_started_yes_stay_ids.parquet` | Parquet file with candidate stay_ids |
| `--sample-size` | 1000 | Number of random stays to process |
| `--sample-seed` | 42 | Random seed for reproducibility |
| `--source-table-filter` | _none_ | Restrict stays to those that contain a given raw `source_table`, such as `ventilator_setting` |
| `--memory-limit` | `4GB` | DuckDB memory limit |
| `--resume` | off | Resume an interrupted run from checkpoint state and temp DB |
| `--state-file` | `<output>.state.json` | Path to checkpoint state JSON |
| `--backup-every` | 200 | Write periodic checkpoint exports every N processed stays (0 disables) |
| `--backup-dir` | `<output_parent>/<output_stem>_checkpoints` | Directory for checkpoint export files |
| `--seed-checkpoint` | _none_ | Seed the output table from an existing parquet checkpoint before continuing |
| `--seed-skip-count` | _none_ | Skip the first N candidate stays when starting from a seeded checkpoint |

To process only stays that have ventilator-setting rows in the materialized raw file, add:

```bash
python prepare_event_log.py --input icu_event_level_sbt.parquet --output icu_event_log.parquet --source-table-filter ventilator_setting
```

### Processing Pipeline

The pipeline (`derive/pipeline.py`) performs these steps for each stay:

1. **Derive Weaning Frame**
   - Extracts all ventilator-setting rows (indicative of mechanical ventilation)
   - Reconstructs weaning/SBT episodes from ventilation status transitions
   - Groups events by stay_id and time

2. **Extract Invasive Ventilation Start Times**
   - Queries raw procedureevents for invasive ventilation marker (itemid=225792)
   - Records the earliest starttime per stay_id
   - **This ensures SBT can only start after invasive ventilation begins**

3. **Build SBT Episodes**
   - Calls thesis-specific SBT episode builder (`derive/sbt_episodes.py`)
   - Returns DataFrame with columns: `stay_id`, `case_id`, `sbt_start_time`, `sbt_end_time`, etc.

4. **Apply Invasive Ventilation Gate**
   - Filters episodes: keep only if `sbt_start_time ≥ invasive_vent_start_time`
   - Suppresses SBT events that would occur before ventilation began
   - **Prevents conformance violation RC-CF-01** (SBTStarted must follow InvasiveVentilationStarted)

5. **Emit SBT Events**
   - Converts filtered episodes to canonical event rows
   - Sets `source_table='sbt_derived'`, `itemid='sbt_status'`, `value_text='Started'`

6. **Activity Mapping**
   - Maps all events (including SBT) to semantic activities via `configs/activity_mapping.yaml`
   - Example: `source=sbt_derived, itemid=sbt_status, value_text=Started` → Activity: `SBTStarted`

7. **Output Canonical Event Log**
   - Aggregates all processed stays into a single event log
   - Schema: `case_id`, `timestamp`, `activity`, `attrs` (metadata)
   - Sorted by timestamp within each case

### Output
- `icu_event_log.parquet` — Canonical event log ready for conformance checking
- Temporary DuckDB files created and cleaned up automatically

### Safe Long-Run Execution on Linux

For long runs, use `tmux` so the process survives terminal disconnects.

```bash
tmux new -s eventlog
python prepare_event_log.py --input icu_event_level_sbt.parquet --output icu_event_log.parquet --backup-every 200
# detach with Ctrl+b then d
```

Reattach later:

```bash
tmux attach -t eventlog
```

If the job is interrupted, resume where it left off:

```bash
python prepare_event_log.py --input icu_event_level_sbt.parquet --output icu_event_log.parquet --resume
```

Alternative without tmux (`nohup`):

```bash
nohup python prepare_event_log.py --input icu_event_level_sbt.parquet --output icu_event_log.parquet --backup-every 200 > prepare_event_log.out 2>&1 &
```

Convenience launcher script (tmux first, nohup fallback):

```bash
./run_event_log_safe.sh
./run_event_log_safe.sh --resume
./run_event_log_safe.sh --seed-checkpoint data/icu_event_log_checkpoints/icu_event_log.checkpoint_0010000.parquet
```

The script writes timestamped logs under `logs/`, starts in a detached `tmux` session when available, and supports pass-through options like `--input`, `--output`, `--backup-every`, `--state-file`, `--backup-dir`, `--memory-limit`, `--seed-checkpoint`, and `--seed-skip-count`.

To restart from the 10,000-stay checkpoint and continue the full build, use:

```bash
./run_event_log_safe.sh --seed-checkpoint data/icu_event_log_checkpoints/icu_event_log.checkpoint_0010000.parquet
```

### Configuration Files
- `configs/activity_mapping.yaml` — Maps raw source/itemid/value combinations to semantic activities

---

## 3. Conformance Checking

### Purpose
Execute declarative process-compliance rules against the event log and compute conformance metrics.

### Command
```bash
python main.py
```

### What This Does

The conformance checker (`main.py` and `conformance/checker.py`) performs these steps:

1. **Load Configuration**
   - Reads declarative rules from `configs/declare/` (YAML format)
   - Rules include: `readiness_assessment.yaml`, `failure_correction.yaml`, `sbt_execution.yaml`, `weights.yaml`

2. **Load Event Log**
   - Reads canonical event log from `icu_event_log.parquet`
   - Extracts trace data: activities per case, with timestamps

3. **Process Each Stay**
   - For each case in the event log:
     - Extract ordered activity sequence
     - Check each declarative constraint (LTL formulas)
     - Record violations with timestamps and details

4. **Aggregate Results**
   - Per-stay conformance score
   - Per-rule violation counts
   - Weighted aggregation via Sugeno fuzzy integral (from `weights.yaml`)

5. **Compute Metrics**
   - **Population KPI** — Weighted average conformance across all stays
   - **Violations Summary** — Breakdown by rule type (must/may/not constraints)
   - **Per-Rule Statistics** — How many stays violated each rule

6. **Export Results**
   - `conformance_results.csv` — Per-stay scores and violation details
   - Console output with population-level KPI

### Declarative Rules

Rules are defined in YAML and encode process constraints as LTL formulas. Example from `configs/declare/readiness_assessment.yaml`:

```yaml
rules:
  RC-CF-01:
    name: "SBT Start requires prior Invasive Ventilation"
    ltl: "!(({SBTStarted})->{InvasiveVentilationStarted})"
    type: "must"
```

### Output
- `conformance_results.csv` — Per-stay conformance scores and violation details
- Console: Population KPI summary
- Example output:
  ```
  Batch Processing: 100%|████████████| 1000/1000 [37:35<00:00,  2.26s/it]
  Successfully processed 1000 stays.
  Population KPI (Sugeno): 0.9120
  Results saved to conformance_results.csv
  ```

---

## Quick Start

### Prerequisites
- Python 3.8+
- PostgreSQL connection to MIMIC-IV (for raw data extraction)
- Candidate stay_ids file (from prior domain analysis)

### Full Pipeline Example

```bash
# Step 1: Extract raw ICU events
python database/materialize_all_icu_events.py --output icu_event_level_sbt.parquet

# Step 2: Build event log (with SBT derivation and conformance gates)
python prepare_event_log.py \
  --input icu_event_level_sbt.parquet \
  --output icu_event_log.parquet \
  --sample-size 1000

# Step 3: Run conformance checking
python main.py
```

### Expected Output
```
Batch Processing: 100%|████████████| 1000/1000 [00:45<00:00,  1.20s/it]
Successfully processed 1000 stays.
Population KPI (Sugeno): 0.91
Results saved to conformance_results.csv
```

---

## Architecture

### Key Modules

| Module | Purpose |
|--------|---------|
| `database/` | Raw data extraction and database utilities |
| `derive/` | Event log construction, SBT derivation, invasive-vent gating |
| `conformance/` | Declarative rule checking and metrics computation |
| `configs/` | YAML configuration for activity mapping, rules, weights |

### Data Flow

```
MIMIC-IV Database
       ↓
[materialize_all_icu_events.py]
       ↓
Raw ICU Events (icu_event_level_sbt.parquet)
       ↓
[prepare_event_log.py → derive/pipeline.py]
  - Derive weaning frame
  - Extract invasive-vent start times
  - Build SBT episodes
  - Apply invasive-vent gate ← **Conformance Guard**
  - Map activities
       ↓
Canonical Event Log (icu_event_log.parquet)
       ↓
[main.py → conformance/checker.py]
  - Load declarative rules
  - Check LTL constraints
  - Compute violations
  - Aggregate metrics
       ↓
Conformance Results (conformance_results.csv)
```

---

## Documentation & Configuration

- **Activity Mapping** — See `configs/activity_mapping.yaml`
- **Declarative Rules** — See `configs/declare/*.yaml`
- **Rule Weights** — See `configs/declare/weights.yaml`
- **Item Dictionary** — See `configs/item_dictionary.yaml` (MIMIC-IV itemid → label mapping)
