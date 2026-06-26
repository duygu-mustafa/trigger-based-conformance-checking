# Methodological Overview: Clinical Conformance Checking for SBT Weaning

## 1. Domain & Research Objective

This pipeline automates **conformance checking** of clinical practice against established guidelines for **Spontaneous Breathing Trial (SBT)** weaning from mechanical ventilation in the ICU. The reference guidelines are derived from Akella et al. (2022). The pipeline processes real patient data from the **MIMIC-IV** database and evaluates, for each patient, whether ventilation weaning episodes comply with three categories of clinical rules: readiness assessment, SBT execution, and failure correction.

---

## 2. Overall Pipeline Architecture

The pipeline is composed of **five sequential stages**, each implemented as a standalone module:

```
MIMIC-IV PostgreSQL  ──[1]──>  Raw ICU Events (Parquet)
                                    │
                               [2] DuckDB batch
                                    │
                               Canonical Event Log (Parquet)
                                    │
                               [3] Custom Declare Engine
                                    │
                               Conformance Results (CSV + JSON)
                                    │
                               [4] R Statistics
                                    │
                               Statistical Report
                                    │
                               [5] React Dashboard
```

---

## 3. Stage 1 — Data Extraction (`database/`)

**File:** `materialize_all_icu_events.py`

**Purpose:** Extract denormalized patient events from MIMIC-IV PostgreSQL into a single Parquet file.

**Methodology:**

1. Connects to MIMIC-IV via `psycopg2` using credentials from environment variables.
2. Issues a `UNION ALL` query across seven source tables:
   - `chartevents` — vital signs, clinical observations
   - `datetimeevents` — datetimes of clinical events
   - `inputevents` — fluid inputs, drug administrations
   - `outputevents` — fluid outputs
   - `procedureevents` — procedures
   - `ingredientevents` — medication ingredients
   - Derived tables: `norepinephrine_equivalent_dose`, `bg` (blood gases), `ventilator_setting`, `ventilation`
3. Computes derived SBT triggers inline via SQL window functions (`LAG`) on ventilator mode transitions.
4. Streams results with `fetchmany` and writes to Parquet via PyArrow with ZSTD compression.
5. Supports optional filter to only SBT-candidate stays.

**Output schema:** 20-column denormalized table keyed by `stay_id` and `charttime`.

---

## 4. Stage 2 — Event Log Construction (`derive/`, `prepare_event_log.py`)

**Purpose:** Transform raw ICU data into a canonical event log with semantically meaningful activities and derived SBT episodes.

### 4.1 Ventilation Synthesis & Invasive Vent Inference (`derive/pipeline.py`)

Before SBT derivation, the pipeline performs two preparatory transformations on the raw event log:

**a) Remove explicit procedure events.** Rows from `procedureevents` with `itemid = 225792` (the raw "Invasive Ventilation" procedure code) are dropped entirely. This enforces that all ventilation semantics are derived from physiological settings rather than administrative codes.

**b) Synthesize invasive ventilation start/end events from ventilator settings.** The function `_full_support_start_times_from_settings()` (`pipeline.py:329`) detects transitions on the binary `is_full_support` signal (SBT-candidate vs. everything else):

1. For each row, determines SBT-candidate status via `_is_sbt_candidate_state()` (`pipeline.py:308`): True if the mode matches `{Ambient, SPONT, CPAP, CPAP/PSV, Pressure Support, Standby, Spontaneous}`, or ASV with `plateau_pressure - PEEP ≤ 8 cmH₂O`.
2. `is_full_support = NOT _is_sbt_candidate_state(...)` — a binary classification where "full support" captures every non-SBT-candidate mode.
3. **Start condition** (`start_mask`): `is_full_support = True AND (prev ≠ True OR prev is NaN)` — fires on the first full-support row **or** any transition into full support.
4. **End condition** (`end_mask`): `prev = True AND current ≠ True` — fires on a transition *out of* full support (into SBT-candidate mode).
5. Each start is paired with the first subsequent end to form `(full_support_start, full_support_end)` blocks, where `end = None` if the episode is ongoing at end of data.
6. Synthetic rows are emitted for each pair: `"derived_invasive_ventilation_start"` at the start timestamp, `"derived_invasive_ventilation_end"` at the end timestamp (if present).

These synthetic rows are concatenated back into the raw event stream for downstream activity mapping.

> **Note on downstream episode segmentation:** The blocks above define *individual Full Support periods*. Conformance checking in `main_per_sbt.py:46` uses `_build_trigger_episodes()`, which rebases windows from each `InvasiveVentilationStarted` to the **next** `InvasiveVentilationStarted` (or end of trace). This means the conformance window spans the entire clinical episode: Full Support → SBT → recovery, rather than ending at the Full-Support-to-SBT transition. The result is that each episode analyzed for conformance runs from **one invasive ventilation start to the next invasive ventilation start**, matching the clinical notion of "one weaning attempt episode."

### 4.2 SBT Episode Derivation (`derive/sbt_episodes.py`)

This is the core algorithm for detecting SBT attempts from ventilator mode time-series. The source file implements 241 lines of domain-specific logic.

#### 4.2.1 Ventilator Mode Classification

Two explicit mapping dictionaries translate ventilator mode strings into clinical categories. These cover the two distinct naming conventions found in MIMIC-IV:

**`_VENTILATOR_MODE_MAPPING`** (`sbt_episodes.py:23–67`) — 45 modes mapped for the general `ventilator_mode` column:

| Category | Mapped Modes |
|---|---|
| `"Full Invasive Support"` | Apnea Ventilation, APRV, APRV/Biphasic+ApnPress, APRV/Biphasic+ApnVol, APV(cmv), CMV, CMV/ASSIST, CMV/ASSIST/AutoFlow, CMV/AutoFlow, DuoPaP, MMV, MMV/AutoFlow, P-CMV, PCV+, PCV+Assist, PRES/AC, PRVC/AC, PRVC/SIMV, P-SIMV, (S)CMV, SIMV, SIMV/AutoFlow, SIMV/PRES, SIMV/VOL, SYNCHRON MASTER, SYNCHRON SLAVE, VOL/AC |
| `"SBT"` | CPAP, CPAP/PPS, CPAP/PSV, CPAP/PSV+ApnPres, CPAP/PSV+ApnTCPL, CPAP/PSV+ApnVol, MMV/PSV, MMV/PSV/AutoFlow, PCV+/PSV, PSV/SBT, SIMV/PSV, SIMV/PSV/AutoFlow, SPONT |
| `"Liberated/Non-Invasive"` | Ambient, Standby |

**`_VENTILATOR_MODE_HAMILTON_MAPPING`** (`sbt_episodes.py:69–86`) — 16 modes for the `ventilator_mode_hamilton` column (Hamilton ventilator-specific nomenclature):

| Category | Mapped Modes |
|---|---|
| `"Full Invasive Support"` | APRV, APV(cmv), APV(simv), ASV, DuoPaP, P-CMV, P-SIMV, (S)CMV, SIMV |
| `"SBT"` | SPONT, VS |
| `"Liberated/Non-Invasive"` | Ambient, nCPAP-PS, NIV, NIV-ST |

#### 4.2.2 Weaning State Assignment

Each timepoint in a patient's stay is classified into one of four weaning states via `map_weaning_state()` (`sbt_episodes.py:101`). The function follows a strict **preference hierarchy**:

1. **Hamilton mode check:** If `ventilator_mode_hamilton` is present and non-missing, look it up in the Hamilton mapping first. Map its category to a state: `"SBT"` or `"Liberated/Non-Invasive"` → `"SBT Candidate"`; `"Full Invasive Support"` → `"Full Support"`.
2. **Fallback to general mode:** If the Hamilton check yielded `"Other"` or was missing, fall back to `ventilator_mode` with the general mapping.
3. **Ventilation status fallback:** Only if both mode columns are missing, use `ventilation_status`: `"InvasiveVent"` → `"Full Support"`; `"SupplementalOxygen"`, `"HFNC"`, `"NonInvasiveVent"` → `"SBT Candidate"`; `"None"` → `"Liberated"`.
4. **Complete miss:** Returns `"Other"` for unmapped or ambiguous data.

#### 4.2.3 Weaning Frame Reconstruction (`pipeline.py:80`)

Because the raw event log is in long form (one row per observation), the function `_derive_weaning_frame_from_raw()` pivots the data into a wide weaning frame suitable for SBT detection:

1. Filter to rows where at least one of `{ventilator_mode, ventilator_mode_hamilton}` has a non-missing value.
2. Remove rows where an empty mode value is recorded in the `ventilator_setting` source (these are artifacts that would create spurious transitions).
3. Extract five weaning-relevant columns from the long-form data by matching on `(source_table, itemid)`:
   - `ventilation_status` ← (`ventilation`, `ventilation_status`)
   - `ventilator_mode` ← (`ventilator_setting`, `ventilator_mode`)
   - `ventilator_mode_hamilton` ← (`ventilator_setting`, `ventilator_mode_hamilton`)
   - `plateau_pressure` ← (`ventilator_setting`, `plateau_pressure`)
   - `peep` ← (`ventilator_setting`, `peep_vent`)
4. Group by `(stay_id, event_time)` and aggregate with `_last_valid()` (takes the last non-null value within each timestamp group).
5. Discard rows where all five columns are null (no ventilator data at that timepoint).
6. Rename `event_time` → `charttime` and add `starttime` / `endtime` columns matching the weaning DataFrame schema.

#### 4.2.4 Episode Construction Algorithm (`build_sbt_episodes()`, `sbt_episodes.py:147`)

The algorithm processes the weaning frame as an ordered time-series and builds SBT episodes using a **state machine with look-ahead debouncing**:

**State machine variables:**
- `current_episode`: `None` (idle) or a dict tracking `{stay_id, sbt_start_time, last_time, is_success}`.
- `debounce_minutes`: default **120 minutes**.

**Transitions** (evaluated for each row `i` at time `t_i`):

| Current State | Incoming State | Action |
|---|---|---|
| `None` | `"SBT Candidate"` | **Start episode.** Set `sbt_start_time = t_i`, set `is_success = False` (provisionally). |
| Active | `"Liberated"` | **Close as success.** Set `extubation_time = t_i`, `is_success = True`, compute `sbt_duration_minutes = (t_i - sbt_start_time)`. Append episode. |
| Active | `"Full Support"` | **Trigger debounce look-ahead.** Scan forward from `i+1` up to `debounce_minutes` (120 min). If a return to `"SBT Candidate"` is found within the window, treat this as a **brief fluctuation** — do NOT close the episode, just update `last_time = t_i`. If no return is found within the window, close as **failure**: set `failure_time = t_i`, `is_success = False`, compute duration, append. |
| Active | `"Other"` | **No-op.** Update `last_time = t_i` to extend episode tracking. |
| Active | End of data (`i == len(df) - 1`) | **Right-censored close as success.** Set `extubation_time = t_i`, `is_success = True`, compute duration, append. |

**Key detail — debounce look-ahead** (`sbt_episode.py:206–217`):
When the patient transitions back to Full Support, the algorithm does not immediately declare failure. Instead, it scans subsequent rows within a 120-minute window. If the patient returns to SBT Candidate within that window, the dip is treated as a transient artifact (e.g., a temporary mode change for suctioning or a brief clinical interruption) and the episode continues. Only if the Full Support persists beyond 120 minutes is the SBT declared failed.

#### 4.2.5 Episode-to-Event Conversion (`pipeline.py:28`)

The function `sbt_episodes_to_events()` transforms each episode row into two event rows:
- **SBT Started** event: `source_table = "sbt_derived"`, `itemid = "sbt_status"`, `value_text = "Started"`, timestamped at `sbt_start_time`.
- **SBT Outcome** event: `source_table = "sbt_derived"`, `itemid = "sbt_outcome"`, `value_text = "Success"` or `"Failure"`, timestamped at the outcome time (`extubation_time` for success, `failure_time` for failure, or `last_time` as fallback).

These synthetic rows are concatenated into the raw event stream for downstream activity mapping.

#### 4.2.6 Invasive Ventilation Gating

After episode construction, `_keep_directly_preceded_sbt_episodes()` (`pipeline.py:268`) filters episodes per stay:
1. For each stay, look up the first invasive ventilation start time from `_invasive_vent_start_times_from_raw()` (which calls `_full_support_start_times_from_settings()`).
2. Keep only SBT episodes whose `sbt_start_time ≥ invasive_start_time`.
3. From the eligible episodes per stay, keep only the **first** one (`.head(1)` per stay group).

This ensures that SBT episodes are correctly attributed to specific ventilation periods. Later SBTs in the same stay are not discarded — they are simply handled as separate episodes when a new invasive ventilation cycle is detected, or omitted if no new Full Support transition precedes them. The downstream conformance orchestration in `main_per_sbt.py` further segments by **trigger episodes** (each `InvasiveVentilationStarted` event starts a new independent analysis window).

### 4.3 Activity Mapping (`derive/activity_emitter.py`)

Raw events (defined by `(source_table, itemid, value)` tuples) are mapped to semantic activities using `configs/activity_mapping.yaml`. Examples:

| Raw (source, itemid, value) | Semantic Activity |
|---|---|
| Derived from vent transition | `InvasiveVentilationStarted` / `InvasiveVentilationEnded` |
| Derived from weaning state | `SBTStarted` / `SBTCompleted` |
| `datetimeevents`, `225317` (Extubation) | `Extubation` |
| Derived: re-ventilation after SBT | `SBTFailed` |

### 4.4 Canonical Schema (`conformance/event_log_builder.py`)

All activities are normalized to a uniform schema:

```
case_id | activity | timestamp | source_table | itemid | value_raw | value_num | unit | attrs | patient_id | stay_id
```

### 4.5 Batch Processing (`prepare_event_log.py`)

Uses **DuckDB** for memory-efficient batch processing of large Parquet datasets. Supports:
- Checkpoint/resume via `--resume`, `--state-file`, `--backup-every`.
- Parallel stay processing with `--n-workers`.

---

## 5. Stage 3 — Conformance Checking (`conformance/`)

This is the methodological core of the pipeline. Rather than using ProM or pm4py, it implements a **custom Declare engine** (1,557 lines in `checker.py`).

### 5.1 Declare Templates (30 templates)

| Category | Templates |
|---|---|
| **Unary** | EXISTENCE, ABSENCE, EXACTLY, INIT, END |
| **Positive Binary** | RESPONDED_EXISTENCE, RESPONSE, ALTERNATE_RESPONSE, CHAIN_RESPONSE, PRECEDENCE, ALTERNATE_PRECEDENCE, CHAIN_PRECEDENCE, CO_EXISTENCE, SUCCESSION, ALTERNATE_SUCCESSION, CHAIN_SUCCESSION |
| **Negative Binary** | NOT_RESPONDED_EXISTENCE, NOT_RESPONSE, NOT_CHAIN_RESPONSE, NOT_PRECEDENCE, NOT_CHAIN_PRECEDENCE, NOT_CO_EXISTENCE, NOT_SUCCESSION, NOT_CHAIN_SUCCESSION |

### 5.2 Constraint Structure (`conformance/types.py`)

Each constraint is a YAML-defined object with:

```yaml
- name: RC-DP-01
  description: "PaO2/FiO2 >= 150 before SBT"
  template: RESPONSE
  activation: [InvasiveVentilationStarted]
  target: [SBTStarted]
  conditions:
    correlation:
      FIO2: "items[223835] AS FIO2"
      PaO2: "items[4903] AS PaO2"
      condition: "PaO2 / FIO2 >= 150"
    time:
      min_gap: 0
      max_gap: 86400  # 24 hours
```

### 5.3 Evaluation Algorithm (`conformance/checker.py`)

For each patient stay, grouped events are sorted by timestamp and processed:

1. **Activation Selection:** For each constraint, find all events matching the `activation` activity set (optionally filtered by activation conditions).
2. **Target Selection:** Find all events matching the `target` activity set.
3. **For each activation-target pair**, evaluate:
   - **Temporal conditions:** min/max gap in seconds between activation and target.
   - **Correlation (data) conditions:** Python expressions evaluated against the target event's clinical data.
   - **Directional ordering:** Before, after, or adjacent (depending on template).
4. **Outcome classification:**
   - `SATISFIED` — all criteria met.
   - `VIOLATED` — activation occurred without satisfying target.
   - `VACUOUS` — no activation event occurred (constraint does not apply).
5. Returns `ConstraintResult` with outcome, counts, forensics, and deltas.

### 5.4 Data Condition Engine

Declare correlation conditions are transpiled from YAML to Python via regex:

- `items[itemid]` → `__item(itemid)` function call (looks up the value from the target event's data).
- `AND` / `OR` / `NOT` → Python `and` / `or` / `not`.
- Supports `date(ts)` and `timedelta(days=N)` for date arithmetic.
- Clinical context variables: `hours_since_intubation`, `ventilation_duration_hours`, `previous_SBT_failed`, `is_chronic`, `vent_mode`, `sbt_duration_min`.

### 5.5 Three Clinical Rule Models (`configs/declare/`)

#### Model A: Readiness Assessment (13 constraints, e.g., RC-CF-01, RC-DP-01–07, RC-TM-01)

Evaluates patient readiness before SBT initiation:
- **RC-CF-01 (Control Flow):** At least one set of clinical data (labs, vitals) must be assessed before SBT.
- **RC-DP-01 to RC-DP-07 (Data Perspective):** Specific physiological thresholds must be met:
  - DP-01: PaO₂/FiO₂ ≥ 150 within 24h before SBT.
  - DP-02: pH ≥ 7.25.
  - DP-03: Hemoglobin ≥ 7 g/dL.
  - DP-04: Temperature ≤ 38°C.
  - DP-05: No vasopressors (NED < 0.1 µg/kg/min, or only one vasopressor at low dose).
  - DP-06: Mental status: RASS ≥ -1.
  - DP-07: Inspiratory effort: RSBI ≤ 105.
- **RC-TM-01 (Temporal):** A minimum 24-hour observation window after intubation before SBT.

#### Model B: SBT Execution (10 constraints, e.g., SBT-DP-02–05, SBT-TM-01/02)

Monitors the SBT process itself:
- **SBT-DP-02:** No SBT success when respiratory failure criteria are met.
- **SBT-DP-03:** No SBT success when hemodynamic failure criteria are met.
- **SBT-DP-04:** No SBT success when neurologic failure criteria are met.
- **SBT-DP-05:** No SBT success in chronic care patients.
- **SBT-TM-01 / 01-early / 01-late:** After SBT failure, retry should occur next day.
- **SBT-TM-02:** First SBT should occur within 72 hours of intubation.

#### Model C: Failure Correction / Interventions (10 constraints, e.g., INT-TR-01–05, INT-DX-04/05, INT-SEQ-01/02)

Evaluates whether appropriate interventions followed SBT failure:
- **INT-TR-01 to INT-TR-05 (Therapeutic):** Bronchodilator, diuretic, afterload reduction, electrolyte correction, hormonal replacement — each within a defined temporal window.
- **INT-DX-04/05 (Diagnostic):** Relevant labs and diagnostics must be ordered.
- **INT-SEQ-01/02 (Sequencing):** Interventions should follow a logical clinical sequence.
- **INT-COMPOSITE-01:** At least one appropriate intervention must occur after failure.

### 5.6 Trigger-Episode Segmentation (`main_per_sbt.py`)

The function `_build_trigger_episodes()` (`main_per_sbt.py:46`) segments each patient stay into **trigger episodes** by taking all `InvasiveVentilationStarted` events and pairing each consecutive pair:

```
Episode i: [InvasiveVentilationStarted[i],  InvasiveVentilationStarted[i+1])
Episode n: [InvasiveVentilationStarted[n],  end_of_trace + 1s)
```

This means each conformance window spans from **one invasive ventilation start to the next** — encompassing the full support period, the subsequent SBT trial, and any liberated/recovery time in between. This differs from the individual Full Support blocks emitted by `_full_support_start_times_from_settings()` (which end at the Full Support → SBT transition); the conformance window deliberately extends further to capture the entire clinical outcome of the weaning attempt.

Within each episode:
- **SBT start** is the first `SBTStarted` event in the window.
- **SBT outcome** is determined by checking whether a new `InvasiveVentilationStarted` (re-ventilation) occurs within 48 hours of the SBT start. If yes → `"Failure (Reventilated <48h)"`; otherwise → success or right-censored.
- **SBT end** is set to the re-ventilation timestamp (on failure) or the episode end timestamp (on success).
- Multiple ventilation periods within one stay are evaluated independently.
- Early vs. late SBT attempts can be compared via `attempt_index`.

### 5.7 Weighted Fuzzy Scoring (`conformance/weighted_scoring.py`, 699 lines)

Implements a fuzzy conformance scoring system that goes beyond binary pass/fail:

**Formula (3.1)** — Maximum weight per constraint:
```
w_max(c) = mean(clinical_consequence, unnoticed_frequency, must_not_vs_should)
```
Capped at 2.0 if all three scores are exactly 1.0.

**Formula (3.2)** — Fuzzy severity of violation:
```
mu(v) = trapezoidal(theta, theta_crit, delta)
```
Where `delta = |value - threshold| / threshold`. Control-flow violations always have `mu = 1.0`.

**Formula (3.3)** — Effective violation weight:
```
w(v) = w_max² × mu(v)
```

**Formula (3.4)/(3.5)** — Per-constraint penalty capped at `w_max²`, then aggregated to a trace-level score.

**Sugeno Fuzzy Integral** — Population-level KPI:
```
Sugeno KPI = max(min(score_i, i/n))  over sorted trace scores
```

This produces a single interpretable score between 0 (non-conformant population) and 1 (fully conformant population).

### 5.8 Batch Runner (`conformance/batch_runner.py`)

Uses DuckDB to load event log data in batches, groups by `case_id`, and distributes evaluation across stays. Supports:
- PostgreSQL-style connection to Parquet files.
- Pagination for memory-bounded processing.
- Per-stay conformance evaluation with progress tracking.

---

## 6. Stage 4 — Statistical Analysis (`statistics_R.r`)

**Purpose:** Correlate conformance violations with clinical outcomes.

**Methodology:**

1. Converts episode-level results to a **case-level binary matrix** (each row = patient, each column = rule, value = violated/non-violated). Vacuous constraints are treated as non-violations.
2. For each rule, constructs a **2×2 contingency table**:
   |           | Violated | Not Violated |
   |-----------|----------|--------------|
   | Success   | a        | b            |
   | Failure   | c        | d            |
3. Computes:
   - **Fisher's exact test** (p-value).
   - **Odds ratio** with 95% confidence interval.
   - **Relative risk** with 95% confidence interval.
4. **Multiple testing correction:**
   - **Bonferroni** (conservative).
   - **Benjamini-Hochberg FDR** (less conservative).
5. **Effect size interpretation:** The p-values indicate statistical significance, while odds ratios and relative risks quantify the clinical impact of each violation.

The R script is invoked automatically from `main_per_sbt.py` via `subprocess.run(["Rscript", "statistics_R.r"])`.

---

## 7. Stage 5 — Frontend Visualization (`frontend/`)

**Stack:** React 19 + Vite 8 (JavaScript).

**Components:**

| Component | Purpose |
|---|---|
| `Timeline.jsx` | Per-patient interactive event timeline showing activities, SBT episodes, and violated constraints |
| `SummaryView.jsx` | Aggregate dashboard with population-level statistics, distribution charts |
| `RulesOverview.jsx` | Reference table of all Declare rules with descriptions, definitions, and violation counts |
| `SummaryView/Histogram.jsx` | Distribution of trace-level conformance scores |
| `SummaryView/BarChart.jsx` | Rule violation frequencies |
| `SummaryView/ScatterPlot.jsx` | Correlation plots (e.g., violations vs. outcome) |

The frontend reads JSON files exported by `main_per_sbt.py`: per-case `case_*.json` files, a `manifest.json`, and a `summary.json`.

---

## 8. Key Methodological Decisions

1. **Custom Declare Engine over ProM/pm4py:** The decision to implement a custom engine (rather than using established Process Mining frameworks) was driven by the need to evaluate clinical data conditions (e.g., "PaO₂/FiO₂ ≥ 150") directly on event payloads, support complex temporal windows with clinical context variables, and produce detailed forensics per violation.

2. **DuckDB over pandas for batch processing:** DuckDB provides SQL-based querying on Parquet files with memory-efficient streaming, enabling processing of thousands of ICU stays without loading everything into RAM.

3. **Episode-level over stay-level evaluation:** Each intubation episode is evaluated independently, acknowledging that a single patient stay may involve multiple ventilation periods with different clinical contexts.

4. **Fuzzy weighted scoring over binary conformance:** Standard Declare conformance yields binary (satisfied/violated/vacuous). The fuzzy extension captures partial compliance and clinical severity, producing a graded score that is more useful for clinical quality improvement.

5. **Three separate rule models:** The clinical guidelines are decomposed into three orthogonal dimensions (readiness, execution, intervention), enabling separate analysis of where in the clinical workflow violations occur.

---

## 9. Data Flow Summary

```
PostgreSQL (MIMIC-IV)
    │
    ▼  [materialize_all_icu_events.py]
icu_event_level_sbt.parquet    (20 columns, denormalized)
    │
    ▼  [prepare_event_log.py + derive/pipeline.py]
icu_event_log.parquet          (11 columns, canonical)
    │
    ▼  [main_per_sbt.py + conformance/checker.py]
Trigger-episode results:
  - Per-episode: violated/satisfied/vacuous for each of 33+ rules
  - Forensics: which activation/target pairs matched, data values
  - Fuzzy weights: w_max, mu(v), effective weights
  - Sugeno KPI: population-level score
    │
    ▼  [statistics_R.r]
Fisher's exact test, OR, RR per rule
    │
    ▼  [React Frontend]
Interactive dashboard (Timeline, Summary, Rules)
```

---

## 10. Repository File Reference

| File | Role | Lines |
|---|---|---|
| `main_per_sbt.py` | Primary conformance entry point | 587 |
| `main_per_sbt_checkpoints.py` | Checkpoint-based batch runner | 410 |
| `prepare_event_log.py` | Event log construction | 690 |
| `conformance/checker.py` | Declare constraint evaluator | 1,557 |
| `conformance/types.py` | Declare data types | ~100 |
| `conformance/results.py` | Result types | ~120 |
| `conformance/rules.py` | YAML rule model loader | ~100 |
| `conformance/event_log_builder.py` | Canonical schema builder | ~80 |
| `conformance/batch_runner.py` | DuckDB batch processor | ~200 |
| `conformance/weighted_scoring.py` | Fuzzy weighted scoring | 699 |
| `conformance/outcome_postprocessing.py` | Model-level summary builder | ~100 |
| `derive/pipeline.py` | Raw-to-event-log orchestrator | 492 |
| `derive/sbt_episodes.py` | SBT episode constructor | 241 |
| `derive/activity_emitter.py` | Semantic activity mapper | 355 |
| `derive/value_converter.py` | Value normalization | ~50 |
| `database/materialize_all_icu_events.py` | Raw data extraction | 707 |
| `statistics_R.r` | Statistical analysis | 267 |
| `configs/declare/readiness_assessment.yaml` | Readiness rule model | 193 |
| `configs/declare/sbt_execution.yaml` | SBT execution rule model | 162 |
| `configs/declare/failure_correction.yaml` | Failure correction rule model | 195 |
| `configs/declare/weights.yaml` | Constraint metadata & thresholds | 287 |
| `configs/activity_mapping.yaml` | Raw-to-semantic mapping | ~80 |
