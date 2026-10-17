# evaluation/

Second-dataset evaluation of the conformance method on a public, non-clinical log: the
**Road Traffic Fine Management Process** (150,370 cases / 561,470 events). Same checker, same
statistical analysis as the MIMIC-IV SBT pipeline — nothing in `conformance/` or `derive/` is
modified.

| File | What it is |
|---|---|
| `rtfm_conformance.ipynb` | The run: load → outcome preprocessing → episodes → conformance → statistics |
| `rtfm.yaml` | Declare model for the fine process (RTF-01 … RTF-10 and RTF-03b, 11 constraints) |
| `rtfm_utils.py` | Episode segmentation, good/bad outcome derivation, results adapter |
| `complexity.py` | Rule complexity measure C(r) = w_template + n_clauses + n_attributes + t_time |
| `benchmark_scalability.py` | Scalability benchmark (E1 log size, E2 trace length, E3 model size, E4 rule complexity, E5 memory) |
| `rtfm_synthetic_rules.yaml` | Synthetic rule variants for the E4 complexity sweeps (SYN-T/C/A) |
| `synthetic_log.py` | Generator for logs with planted ground truth: SE1 verdict catalogue, SE2/SE3 multi-episode log |
| `benchmark_synthetic.py` | Ground-truth experiments (SE1 correctness, SE2 scoping, SE3 association recovery) |
| `synthetic_analysis.py` | Reads `data/synthetic/`, produces thesis figures and LaTeX table fragments |
| `scalability_analysis.ipynb` | Reads `data/benchmarks/`, produces thesis figures (`figures/`) and tables |
| `trigger_sensitivity.ipynb` | Trigger-selection sensitivity (EQ4): coverage, granularity, prefix loss and label validity per candidate trigger |
| `data/` | Parquet cache of the log and all result CSVs (generated) |

## Running it

Needs the Road Traffic Fine Management Process log (de Leoni & Mannhardt, 4TU.Centre for Research
Data, 2015, [doi:10.4121/uuid:270fd440-1057-4fb9-89a9-b699b47990f5](https://doi.org/10.4121/uuid:270fd440-1057-4fb9-89a9-b699b47990f5))
saved as `evaluation/Road_Traffic_Fine_Management_Process.xes` (not committed), and `pm4py`.
Open `rtfm_conformance.ipynb` and run top to bottom. The first run parses the 185 MB XES and caches
it to `data/rtfm_event_log.parquet`; later runs read the parquet.

`SAMPLE_N` in the second cell controls scope — 5,000 cases by default, `None` for the full log.

## Outcome definition

An episode is good (`"Success"`) when the full amount owed was paid before the process escalated:

```
paid >= amount(Create Fine) + expense
  AND (no 'Add penalty', or the last payment preceded it)
  AND no 'Send for Credit Collection'
```

Bad (`"Failure"`) otherwise. See `derive_episode_outcome` in `rtfm_utils.py` for the attribute
quirks behind the arithmetic.

## Ground-truth experiments

The fine log records no correct verdict and no reason an episode ended as it did, so it cannot
say whether the checker is *right* — only that it runs. `synthetic_log.py` generates logs where
both are known by construction, and `benchmark_synthetic.py` runs three experiments on them:

* **SE1 (verdict correctness)** — 95 hand-written micro-traces, one per template and variant,
  each paired with the verdict the activation semantics prescribe. Covers all 24 implemented
  templates plus activation/correlation conditions, forward and backward time windows, and the
  target-selection modes. Found and fixed a role-reversal defect in the succession decomposition.
* **SE2 (episode vs case scoping)** — a multi-episode log with per-episode verdicts planted,
  checked once per episode and once per whole case. Reports violations the case-scoped reading
  masks and violations it invents.
* **SE3 (association recovery)** — the episode outcome is planted at known risk ratios; the
  statistical stage is asked to recover them, under both scopes and both vacuity treatments.

```
python evaluation/benchmark_synthetic.py --experiments SE1            # seconds
python evaluation/benchmark_synthetic.py --experiments SE2 SE3 --reps 20 --cases 1000
python evaluation/synthetic_analysis.py                               # figures + LaTeX tables
```

SE2/SE3 replications are keyed by seed and appended as they finish, so `--resume` continues an
interrupted run. Results go to `evaluation/data/synthetic/`, figures and table fragments to
`evaluation/figures/`.

The outcome model multiplies a baseline success probability by the planted risk ratio of every
violated rule. That makes each rule's marginal risk ratio equal its planted value **only while no
episode's probability exceeds one** — clipping withholds part of the effect from exactly the
episodes violating the most rules and biases every estimate toward the null. `generate_log`
rejects a configuration that would need clipping rather than doing it silently, and
`tests/test_synthetic_generator.py` asserts the model stays unbiased.

## Scalability benchmark

`benchmark_scalability.py` measures how the checker scales; protocol: single-threaded, fixed
sampling seed (the same case sample across repetitions, so repetition spread is timing noise
only), warm-up pass, `perf_counter`, median over `--reps` repetitions.

Long runs go through the launcher, same contract as `scripts/run_conformance_safe.sh` — tmux (or
nohup), timestamped log in `logs/`, `--resume`:

```
scripts/run_benchmark_safe.sh --reps 3 -- --e2-cases 5000 --e3-cases 5000 --e4-cases 5000
scripts/run_benchmark_safe.sh --resume      # after an interruption
tmux attach -t benchmark                     # watch it
```

That invocation takes roughly 5 h on the reference machine. Results are appended per
measurement, so an interrupted run loses at most the unit in flight; `--resume` reads the
completed keys back and runs only what is missing. Without `--resume` existing CSVs are
truncated, so a fresh run never mixes measurements from different machines or code revisions.

Writes tidy CSVs + `machine_info.json` + `sample_representativeness.csv` to `evaluation/data/benchmarks/`;
`scalability_analysis.ipynb` turns them into figures (log-log scaling fits, complexity-score
regression) under `figures/`. The complexity measure and its rationale live in `complexity.py`.

### Sampling protocol

Not every experiment runs on all 150,370 cases, for different reasons per experiment:

* **E1 (log size)** runs the full ladder **including the complete log**. One full-log pass is
  ~80 min and is what backs the headline claim; extrapolating from a fitted exponent would be
  weaker for no real saving.
* **E1/E5 repetitions are tiered**: `--reps` at small sizes, `--large-reps` (default 1) at or
  above `--large-threshold` (default 25,000). Justified because repetition spread at the small
  sizes is well under a few percent, so timing noise is already characterised and does not need
  re-measuring at the expensive sizes.
* **E2/E3/E4 subsample** (default 10,000 cases, 5,000 in the invocation above). These measure
  *per-unit* quantities — per-trace, per-model-size and per-rule runtime — which do not depend
  on how many other cases are in the log; more cases only narrow the error bars, and they are
  already narrow at 5,000.
* **E5 (memory)** stops at `--large-threshold` by default: peak memory is flat in the number of
  cases (the checker holds no cross-case state), so the expensive sizes add nothing.

`sample_representativeness.csv` backs the subsampling: it compares each sample's trace-length
distribution against the full log (mean/median/p95/max events per case, two-sample KS test).
Random case sampling preserves that distribution in expectation, but the long-trace tail is
thin, so this is the check that a sample is not systematically short.


## Outputs (`evaluation/data/`)

- `rtfm_conformance_results.csv` — one row per episode, per-rule satisfied/violated/vacuous
- `rtfm_case_table_{activations_only,pooled}.csv` — case-level analysis table
- `rtfm_stats_{activations_only,pooled}.csv` — per-rule 2×2 counts, Fisher p, OR, RR with CIs
