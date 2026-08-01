#!/usr/bin/env bash
set -euo pipefail

# Safe launcher for long evaluation/benchmark_scalability.py runs.
# - Uses tmux when available (recommended)
# - Falls back to nohup when tmux is unavailable
# - Writes timestamped logs and supports --resume
# Mirrors run_conformance_safe.sh.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN_DEFAULT="$ROOT_DIR/.venv/bin/python"

EXPERIMENTS="all"
REPS=5
LARGE_REPS=1
LARGE_THRESHOLD=25000
E1_SIZES="1000 2000 5000 10000 25000 50000 100000 full"
SESSION_NAME="benchmark"
RESUME=0
DRY_RUN=0
FORCE_NOHUP=0
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
Usage:
  ./run_benchmark_safe.sh [options] [-- extra args passed to benchmark_scalability.py]

Options:
  --experiments "E1 E3"  Experiments to run (default: all)
  --reps N               Repetitions at small sample sizes (default: 5)
  --large-reps N         Repetitions at/above --large-threshold (default: 1)
  --large-threshold N    Size above which --large-reps applies (default: 25000)
  --e1-sizes "1000 full" E1/E5 size ladder (default: 1000 ... 100000 full)
  --resume               Keep measurements already in data/benchmarks/ and run only what's missing
  --session NAME         tmux session name (default: benchmark)
  --nohup                Force nohup mode instead of tmux
  --dry-run              Print command and exit
  -h, --help             Show this help

Examples:
  # Full thesis protocol, ~5-6 h; safe to interrupt and re-run with --resume
  ./run_benchmark_safe.sh
  ./run_benchmark_safe.sh --resume

  # Quick re-run of one experiment
  ./run_benchmark_safe.sh --experiments E4 --reps 3 --session bench_e4
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --experiments)
      EXPERIMENTS="$2"
      shift 2
      ;;
    --reps)
      REPS="$2"
      shift 2
      ;;
    --large-reps)
      LARGE_REPS="$2"
      shift 2
      ;;
    --large-threshold)
      LARGE_THRESHOLD="$2"
      shift 2
      ;;
    --e1-sizes)
      E1_SIZES="$2"
      shift 2
      ;;
    --resume)
      RESUME=1
      shift
      ;;
    --session)
      SESSION_NAME="$2"
      shift 2
      ;;
    --nohup)
      FORCE_NOHUP=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      EXTRA_ARGS=("$@")
      break
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -x "$PYTHON_BIN_DEFAULT" ]]; then
  PYTHON_BIN="$PYTHON_BIN_DEFAULT"
else
  PYTHON_BIN="python3"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

SCRIPT="$ROOT_DIR/evaluation/benchmark_scalability.py"
if [[ ! -f "$SCRIPT" ]]; then
  echo "benchmark_scalability.py not found in $ROOT_DIR/evaluation" >&2
  exit 1
fi

PARQUET="$ROOT_DIR/evaluation/data/rtfm_event_log.parquet"
if [[ ! -f "$PARQUET" ]]; then
  echo "Missing $PARQUET" >&2
  echo "Run evaluation/rtfm_conformance.ipynb once to build the parquet cache." >&2
  exit 1
fi

LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/benchmark_scalability_${TIMESTAMP}.log"

# shellcheck disable=SC2206  # word splitting is intended for the space-separated lists
CMD=("$PYTHON_BIN" "$SCRIPT"
     --experiments ${EXPERIMENTS}
     --reps "$REPS"
     --large-reps "$LARGE_REPS"
     --large-threshold "$LARGE_THRESHOLD"
     --e1-sizes ${E1_SIZES})

if [[ "$RESUME" -eq 1 ]]; then
  CMD+=("--resume")
fi

if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  CMD+=("${EXTRA_ARGS[@]}")
fi

echo "Root: $ROOT_DIR"
echo "Log:  $LOG_FILE"
echo "Cmd:  ${CMD[*]}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  exit 0
fi

if [[ "$FORCE_NOHUP" -eq 0 ]] && command -v tmux >/dev/null 2>&1; then
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "tmux session '$SESSION_NAME' already exists."
    echo "Attach with: tmux attach -t $SESSION_NAME"
    echo "Or rerun with --session <new_name>."
    exit 1
  fi

  TMUX_CMD="cd '$ROOT_DIR' && ${CMD[*]} 2>&1 | tee '$LOG_FILE'"
  tmux new-session -d -s "$SESSION_NAME" "$TMUX_CMD"
  echo "Started in tmux session: $SESSION_NAME"
  echo "Attach with: tmux attach -t $SESSION_NAME"
  echo "Log tail:    tail -f '$LOG_FILE'"
else
  (cd "$ROOT_DIR" && nohup "${CMD[@]}" > "$LOG_FILE" 2>&1 &)
  echo "Started with nohup in background."
  echo "PID: $(pgrep -n -f 'benchmark_scalability.py' || true)"
  echo "Log tail: tail -f '$LOG_FILE'"
fi
