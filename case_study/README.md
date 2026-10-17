# Case-study result assets

Everything the results section of the MIMIC-IV SBT case study needs, regenerated from
the committed data by five scripts. Read `RESULTS_DIGEST.md` first — it holds every
headline number in prose-ready form and indexes the CSVs and figures.

## Run

```bash
bash case_study/run_all.sh                  # ~1 min; step 01 skipped if already computed
bash case_study/run_all.sh --force          # rescan the 348 M-event log and rebuild caches
bash case_study/run_all.sh --with-ablation  # also runs the segmentation ablation below (~30-60 min)
```

Run from the repository root, with the project virtualenv active
(`duckdb`, `pandas`, `matplotlib`, `statsmodels`, `pyyaml`). Set `PYTHON=...` to pick
a different interpreter. Individual steps can be rerun on their own,
e.g. `python case_study/03_violation_frequency.py`.

### Segmentation ablation (mixed outcomes + trace-global comparison)

One command, no manual step sequencing:

```bash
bash case_study/run_ablation.sh          # 2,000-stay sample (default), ~30-60 min
bash case_study/run_ablation.sh --full   # all 11,790 multi-episode stays, ~2-6 h
bash case_study/run_ablation.sh --smoke  # 20 stays, seconds — sanity-checks the plumbing
```

It runs, in order: (1) the mixed-outcome numbers and the stay-id lists, (2) a
no-segmentation conformance run on those stays (`main.py --no-segmentation`,
resumable), (3) the episode-vs-trace comparison, (4) the digest. `--full` prints a
runtime estimate and asks for confirmation once (`--yes` skips the prompt). Re-running
the same invocation after an interruption resumes rather than restarting, because stage
2 passes `--resume`.

## Inputs (read-only)

| Path | Used for |
| --- | --- |
| `data/final/icu_event_log_full.parquet` | event-log statistics |
| `data/results/full_results/trigger_results_full.csv` | episodes, conformance, associations |
| `configs/declare/*.yaml` | constraint ids, labels, templates, outcome scope |
| `configs/activity_mapping.yaml` | which activity labels the Declare models reason over |
| `data/results/full_results/statistical_results_summary_both.csv` | cross-check reference |

Nothing under `data/` is written to; all output goes to `case_study/out` and
`case_study/figures`.

## Scripts

| Script | Produces |
| --- | --- |
| `01_event_log_stats.py` | `log_overview.json`, `activity_frequency*.csv`, `source_table_distribution.csv`, `events_per_stay*.csv`, activity/trace-length figures |
| `02_episode_stats.py` | `episode_overview.json`, `episodes_per_stay.csv`, `episode_durations.csv`, `outcome_distribution.csv`, `outcome_by_episode_position.csv`, `violations_per_episode*.csv`, segmentation/outcome figures |
| `03_violation_frequency.py` | `violation_frequency.csv` (per constraint), `violation_frequency_by_group.csv`, `violation_frequency_check.json`, violation-rate and coverage figures |
| `04_outcome_association.py` | `association_activations_only.csv`, `association_pooled.csv`, `association_headline.csv`, `association_comparison.csv`, `association_overview.json`, forest plot and vacuity-sensitivity plot |
| `05_digest.py` | `RESULTS_DIGEST.md` |
| `06_mixed_outcomes.py` | `mixed_outcomes.json`, `mixed_outcomes_by_episode_count.csv`, stay-id lists for the ablation, mixed-outcome figure |
| `07_segmentation_ablation.py` | `ablation_by_constraint.csv`, `ablation_overview.json`, masking/activation-loss figures — needs the no-segmentation CSV from `run_ablation.sh` |
| `08_readiness_diagnostics.py` | `readiness_violation_causes.csv`, `readiness_margin_association.csv`, `readiness_records.parquet`, cause and margin figures — needs the diagnostics conformance run below |
| `09_deviation_patterns.py` | `deviation_profiles*.csv`, `readiness_coviolation_matrix.csv`, `violation_by_attempt.csv`, profile, co-violation and attempt-position figures |
| `10_frontend_insights.py` | `frontend/public/data/insights.json` — reshapes the tables of steps 04–09 for the Insights page of the Clinician Studio; needs step 08 |

`06` and `07` are invoked together by `run_ablation.sh` (see above); they are not part
of the default `run_all.sh` unless `--with-ablation` is passed, since `07` needs the
extra conformance run from step 2 of the ablation script.

### Diagnostics conformance run (step 08)

Step 08 decomposes each readiness violation into *why* the activation failed, which
the checker records per activation but the committed results predate:

```bash
python main.py --output data/results/full_results_diag/trigger_results_full.csv \
    --workers 6 --resume --skip-postprocess          # ~3 h over the full cohort
```

The verdicts it produces are identical to `data/results/full_results`; the run adds
`causes` and `values` entries inside `violation_forensics`. `run_all.sh` skips step 08
when that file is absent.

## Design notes

- **Cohort consistency.** Step 01 restricts the event log to the stays that appear in
  the episode results, so log statistics and conformance statistics describe the same
  population (35,692 stays).
- **No duplicated statistics code.** Step 04 imports `build_case_level_table`,
  `generate_contingency_table`, `calculate_stats`, `_classify` and the inter-episode
  rule loader from `derive/statistical_analysis.py`, and asserts at the end that its
  a/b/c/d cells, odds ratios and p-values match the committed
  `statistical_results_summary_both.csv` exactly (`CROSS-CHECK ... PASS`).
- **Orientation.** Every association is reported as exposure = *constraint violated*,
  outcome = *success*. OR < 1 means violation tracks failure.
- **Inter-episode rules.** Constraints flagged `outcome_scope: next_episode` activate
  on `SBTFailed`, which is definitionally the same-episode outcome. They are scored
  against the next episode's outcome, both in the violation-rate split (step 03,
  column `outcome_used`) and in the contingency tables (step 04).
- **Degenerate estimates.** Constraints that activate in only one outcome arm are
  flagged (`outcome_entangled` in step 03, `degenerate_estimate` in step 04) and kept
  out of the headline table — their odds ratios are separation artifacts, not effects.
- **Multiple testing.** Bonferroni and Benjamini–Hochberg FDR are applied within each
  vacuity mode, family size = number of constraints tested.
- **Vacuity sensitivity.** Both encodings are computed: activations-only (primary,
  vacuous episodes dropped) and pooled (vacuous counted as satisfied). The comparison
  CSV/figure flag constraints whose direction or relevance class changes.
- **Segmentation ablation.** `main.py --no-segmentation` reuses the exact
  per-constraint evaluation code path (context windows, verdict bucketing, outcome
  reading) with a single whole-stay window in place of trigger-based episodes, so the
  comparison isolates the effect of segmentation rather than any other pipeline
  difference. Verified byte-identical to the production path when the flag is absent
  (see `run_ablation.sh --smoke` and its check 3). `INT-COMPOSITE-01` and the
  `SBT-TM-01` family are excluded from the ablation as not comparable — the former
  never activates under a single evaluation trace (`attempt_index > 1` never occurs),
  the latter are already saturated at episode level.
- **Violation causes.** Step 08 splits a readiness violation four ways: the criterion
  was never charted in the lookback window (`absent`), charted only outside it
  (`stale`), charted as an event carrying no value (`no_payload`), or assessed and not
  met (`unmet`). Only `unmet` is a statement about care, and only `unmet` violations
  carry a reading, so only they can be ordered by distance from the threshold.
- **Margin strata.** The near/moderate/gross strata of step 08 are tertiles of that
  distance among the `unmet` violations of a constraint, each compared against the
  episodes where the same constraint was satisfied. RC-DP-06 has no graded reading and
  RC-DP-07 has no gradation below its zero threshold, so neither is stratified.
- **Saturated constraints in profiles.** Step 09 leaves RC-DP-06 out of the violation
  profiles and the co-violation matrix. It is violated in 99.9% of its activations, so
  it would enter almost every profile and hide the structure among the criteria that
  discriminate — the same reason it is kept out of interpretation elsewhere.
- **Ablation scope.** The ablation covers the 11,790 multi-episode stays (or a sample
  of them) only, since single-episode stays are identical under both evaluation modes
  by construction. It shows where segmentation *can* matter, not an average over the
  whole cohort.

## Caveats worth repeating in the text

- MIMIC-IV date-shifts every patient, so the log's calendar span (~105 years) is not a
  study period and must not be reported as one.
- `sbt_start` → `sbt_end` is the post-SBT outcome-observation window (capped at 48 h,
  ending with the episode on failure), not the duration of the breathing trial.
- `SBT-TM-01`, `SBT-TM-01-early`, `SBT-TM-01-late` activate only in failing episodes;
  their same-episode outcome split is degenerate by construction, which is why they are
  tested against the next episode's outcome.
