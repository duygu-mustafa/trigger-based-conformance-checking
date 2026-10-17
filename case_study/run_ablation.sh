#!/usr/bin/env bash
# One command: mixed-outcome numbers -> no-segmentation conformance run -> comparison -> digest.
#
#   bash case_study/run_ablation.sh                 # 2,000-stay sample (default), ~30-60 min
#   bash case_study/run_ablation.sh --full          # all 11,790 multi-episode stays, ~2-6 h
#   bash case_study/run_ablation.sh --sample 500     # any other sample size
#   bash case_study/run_ablation.sh --smoke          # 20 stays, seconds; runs the verification
#                                                     # checks described in case_study/README.md
#   bash case_study/run_ablation.sh --yes            # skip the confirmation prompt on --full
#
# Safe to interrupt and re-run: the conformance step passes --resume, so a second
# invocation with the same size continues instead of restarting.
set -euo pipefail

cd "$(dirname "$0")/.."

PY=${PYTHON:-python}
SAMPLE=2000
MODE="sample"
AUTO_YES=""

for arg in "$@"; do
  case "$arg" in
    --full) MODE="full" ;;
    --smoke) MODE="smoke"; SAMPLE=20 ;;
    --sample) MODE="sample" ;;
    --sample=*) MODE="sample"; SAMPLE="${arg#--sample=}" ;;
    --yes) AUTO_YES="1" ;;
    [0-9]*) SAMPLE="$arg" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

case_study_out="case_study/out"
mkdir -p "$case_study_out"

run_step() {
  local label="$1"; shift
  echo
  echo "=== ${label} ==="
  local start; start=$(date +%s)
  "$@"
  echo "--- ${label} took $(( $(date +%s) - start ))s"
}

echo "Mode: ${MODE}"

# --- Stage 1: Tier-0 mixed-outcome numbers + stay-id lists -------------------
if [ "$MODE" = "full" ]; then
  run_step "1/4 mixed outcomes + stay-id lists" "$PY" case_study/06_mixed_outcomes.py --sample-size "$SAMPLE"
  STAY_IDS="${case_study_out}/multi_episode_stay_ids.txt"
  TAG="full"
else
  run_step "1/4 mixed outcomes + stay-id lists" "$PY" case_study/06_mixed_outcomes.py --sample-size "$SAMPLE"
  STAY_IDS="${case_study_out}/ablation_sample_${SAMPLE}_stay_ids.txt"
  TAG="sample${SAMPLE}"
fi

N_STAYS=$(wc -l < "$STAY_IDS" | tr -d ' ')
ABLATION_CSV="${case_study_out}/ablation_no_segmentation_${TAG}.csv"

# ~1.5-2s/stay observed on this machine (data/runtime/runtime_log.jsonl); multi-episode
# stays run longer than the cohort average, so this is a lower bound.
EST_SECONDS=$(( N_STAYS * 2 ))
EST_MIN=$(( EST_SECONDS / 60 ))
echo
echo "Stage 2 will evaluate ${N_STAYS} stays with segmentation disabled."
echo "Rough estimate: ~${EST_MIN} min (single machine, 4 workers)."

if [ "$MODE" = "full" ] && [ -z "$AUTO_YES" ]; then
  read -r -p "Proceed with the full ${N_STAYS}-stay run? [y/N] " reply
  case "$reply" in
    [yY]*) ;;
    *) echo "Aborted before stage 2. Re-run with --yes to skip this prompt."; exit 1 ;;
  esac
fi

# --- Stage 2: the no-segmentation conformance run ----------------------------
run_step "2/4 no-segmentation conformance run" "$PY" main.py \
  --input data/final/icu_event_log_full.parquet \
  --output "$ABLATION_CSV" \
  --stay-ids "$STAY_IDS" \
  --no-segmentation --skip-postprocess --resume --workers 4

# --- Stage 3: the comparison --------------------------------------------------
run_step "3/4 segmentation-ablation comparison" "$PY" case_study/07_segmentation_ablation.py \
  --ablation "$ABLATION_CSV"

# --- Stage 4: digest ----------------------------------------------------------
run_step "4/4 digest" "$PY" case_study/05_digest.py

if [ "$MODE" = "smoke" ]; then
  echo
  echo "=== smoke-test verification ==="
  "$PY" - "$ABLATION_CSV" "$STAY_IDS" <<'PYEOF'
import sys
import pandas as pd

ablation_path, stay_ids_path = sys.argv[1], sys.argv[2]
df = pd.read_csv(ablation_path, low_memory=False)
ids = [l.strip() for l in open(stay_ids_path) if l.strip()]

ok = True
if sorted(df["stay_id"].astype(str).unique()) != sorted(set(ids)):
    print("FAIL: ablation output does not cover exactly the requested stay ids")
    ok = False
if (df["episode_index"] != 1).any():
    print("FAIL: episode_index != 1 found under --no-segmentation")
    ok = False
if len(df) != df["stay_id"].nunique():
    print("FAIL: more than one row for some stay under --no-segmentation")
    ok = False
if ok:
    print(f"PASS: {len(df)} rows, one per stay, episode_index == 1 throughout")
PYEOF
fi

echo
echo "All done. Read case_study/RESULTS_DIGEST.md"
echo "Ablation CSV: ${ABLATION_CSV}"
