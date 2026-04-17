# Conformance Checking and Scoring Summary

This document summarizes how the current conformance checking pipeline works and how scores are computed in this codebase.

## 1) End-to-end flow

The main execution path is:

1. Load input data (canonical event log or raw ICU events).
2. Build a Declare model from YAML.
3. Run per-trace conformance checking against all constraints.
4. Aggregate outcomes and compute a conformance score.
5. Export case-level results.

In the default CLI path (`main.py`), the readiness model is used.

## 2) Model loading and normalization

Rule definitions are read from YAML files in `configs/declare/`.

Highlights of the loader behavior:

- Template aliases are normalized (for example `MP_EXISTENCE -> EXISTENCE`, `TIMED_RESPONSE -> RESPONSE`).
- Condition macros under `model.data_conditions` are expanded inside activation/correlation conditions.
- Time windows can be provided in seconds or hours and are converted to seconds internally.
- If a binary template has no explicit target, a fallback target may be assigned for compatibility.

The output is a `DeclareModel` containing typed `DeclareConstraint` objects.

## 3) Conformance checker logic

For each `case_id` trace:

1. Events are sorted by timestamp.
2. Each constraint in the model is evaluated.
3. A `ConstraintResult` is produced per constraint.
4. A `TraceResult` is produced per case.

### 3.1 Constraint outcomes

Each constraint result is one of:

- `SATISFIED`
- `VIOLATED`
- `VACUOUS` (for example, no activations)
- `NOT_EVALUATED` (template unsupported)

Trace conformance is then:

- `is_conformant = True` if no constraint is `VIOLATED`.

### 3.2 Supported Declare templates

The checker supports a broad set of templates, including:

- Unary: `EXISTENCE`, `ABSENCE`, `EXACTLY`, `INIT`
- Response family: `RESPONSE`, `ALTERNATE_RESPONSE`, `CHAIN_RESPONSE`, and negative variants
- Precedence family: `PRECEDENCE`, `ALTERNATE_PRECEDENCE`, `CHAIN_PRECEDENCE`, and negative variants
- Co-existence family: `CO_EXISTENCE`, `NOT_CO_EXISTENCE`
- Succession family: `SUCCESSION`, `ALTERNATE_SUCCESSION`, `CHAIN_SUCCESSION`
- Responded existence variants

### 3.3 Data and time conditions

During evaluation, the checker can use:

- Item snapshots (latest values up to evaluation timestamp)
- Derived context variables such as:
  - `hours_since_intubation`
  - `ventilation_duration_hours`
  - `previous_SBT_failed`
  - `is_chronic`
  - `sbt_duration_min`
- Time-window checks via min/max seconds bounds

Activation and correlation conditions are parsed from Declare-like syntax into Python expressions and evaluated against this context.

## 4) Weighted scoring method (thesis formulas)

The weighted scoring module implements formulas (3.1) to (3.5).

### 4.1 Constraint weight

For each constraint $c$, a maximum weight $w_{max}(c)$ is computed from metadata scores:

$$
w_{max}(c)=
\begin{cases}
2 & \text{if all metadata scores are }1 \\
\text{mean(metadata scores)} & \text{otherwise}
\end{cases}
$$

### 4.2 Violation severity

For one violation instance $v$:

- Control-flow violations use $\mu(v)=1$.
- Threshold violations use piecewise severity from observed value $x$ and $(\theta,\theta_{crit})$:

$$
\mu(v)=
\begin{cases}
0 & x\le\theta \\
1 & x>\theta_{crit} \\
\frac{x-\theta}{\theta_{crit}-\theta} & \text{otherwise}
\end{cases}
$$

### 4.3 Effective violation penalty

Each violation contributes:

$$
w(v)=w_{max}(c)^2 \cdot \mu(v)
$$

Per trace and constraint, penalties are summed then capped:

$$
W_t(c)=\min\left(w_{max}(c)^2,\sum_{v\in V_{t,c}}w(v)\right)
$$

This prevents repeated violations of the same constraint from exceeding that constraint's maximum squared weight.

### 4.4 Weighted Trace Score

The reworked implementation uses a weighted average of per-constraint satisfaction degrees:

$$
score(t_j)=\frac{\sum_i w_i\mu_{ij}}{\sum_i w_i}
$$

where $w_i$ is the static importance weight from the YAML metadata and $\mu_{ij}$ is the fuzzy satisfaction degree for constraint $c_i$ on trace $t_j$.

## 5) How scoring is currently used in this repo

There are two scoring paths:

1. Legacy helper (`conformance/weighted_scoring.py`)
   - The older `compute_trace_scores()` helper is still available for compatibility with the sample notebooks and tests.
   - It still returns the older capped-penalty summary used in the previous implementation.

2. Current CLI scoring (`main.py`)
   - Uses `score_trace_collection()` to compute the per-trace weighted average score.
   - Converts the trace score to a percentage for export:
     - `conformance_score = trace_score * 100`
   - Also computes a population KPI with `sugeno_kpi()` using the sort-then-max-min Sugeno form.

## 6) Outputs produced by the default CLI

For each stay/case, the exported CSV currently includes:

- `stay_id`
- `is_conformant`
- `conformance_score`
- `num_sbts`
- `num_fails`
- `num_successes`
- `violated` (JSON list of constraint IDs)
- `satisfied` (JSON list of constraint IDs)

## 7) Practical interpretation

- Conformance checking is strict on rule semantics but supports vacuous satisfaction when a template has no activation.
- Weighted scoring lets you encode clinical importance and severity rather than treating all violations equally.
- The current `main.py` score is useful for dashboards, while `weighted_scoring.py` is the mathematically complete scoring implementation.