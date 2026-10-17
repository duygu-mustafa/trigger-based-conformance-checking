#!/usr/bin/env bash
# Regenerate every case-study result artifact (CSVs, JSON, figures, digest).
#
#   bash case_study/run_all.sh            # step 01 skipped if already computed
#   bash case_study/run_all.sh --force    # recompute the event-log scan too
#
# Run from the repository root.
set -euo pipefail

cd "$(dirname "$0")/.."

PY=${PYTHON:-python}
FORCE=""
WITH_ABLATION=""
for arg in "$@"; do
  case "$arg" in
    --force) FORCE="--force" ;;
    --with-ablation) WITH_ABLATION="1" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

run_step() {
  local label="$1"; shift
  echo
  echo "=== ${label} ==="
  local start
  start=$(date +%s)
  "$@"
  echo "--- ${label} took $(( $(date +%s) - start ))s"
}

run_step "01 event log stats"      "$PY" case_study/01_event_log_stats.py ${FORCE}
run_step "02 episode stats"        "$PY" case_study/02_episode_stats.py
run_step "03 violation frequency"  "$PY" case_study/03_violation_frequency.py
run_step "04 outcome association"  "$PY" case_study/04_outcome_association.py
run_step "09 deviation patterns"   "$PY" case_study/09_deviation_patterns.py
# 08 reads the conformance run that records per-activation failure causes. Skip it
# rather than fail when that run has not been produced.
if [ -f data/results/full_results_diag/trigger_results_full.csv ]; then
  run_step "08 readiness diagnostics" "$PY" case_study/08_readiness_diagnostics.py
else
  echo
  echo "=== 08 readiness diagnostics: skipped, no data/results/full_results_diag run ==="
fi
run_step "05 digest"               "$PY" case_study/05_digest.py
# 10 only reshapes the tables the earlier steps wrote; it needs 08's causes table.
if [ -f case_study/out/readiness_violation_causes.csv ]; then
  run_step "10 frontend insights" "$PY" case_study/10_frontend_insights.py
else
  echo
  echo "=== 10 frontend insights: skipped, step 08 did not run ==="
fi

if [ -n "$WITH_ABLATION" ]; then
  run_step "06+07 segmentation ablation (2,000-stay sample)" bash case_study/run_ablation.sh --yes
fi

echo
echo "All done. Read case_study/RESULTS_DIGEST.md"
