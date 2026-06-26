#!/usr/bin/env bash
set -euo pipefail

# Safe launcher for long main_per_sbt.py conformance runs.
# - Uses tmux when available (recommended)
# - Falls back to nohup when tmux is unavailable
# - Writes timestamped logs and supports --resume

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN_DEFAULT="$ROOT_DIR/.venv/bin/python"

INPUT="icu_event_log_full.parquet"
OUTPUT="data/results/full_results/trigger_results_full.csv"
SESSION_NAME="conformance"
RESUME=0
DRY_RUN=0
FORCE_NOHUP=0

usage() {
  cat <<'EOF'
Usage:
  ./run_conformance_safe.sh [options]

Options:
  --input PATH      Input event log parquet (default: icu_event_log_full.parquet)
  --output PATH     Output results CSV (default: data/results/full_results/trigger_results_full.csv)
  --resume          Skip stays already present in output CSV
  --session NAME    tmux session name (default: conformance)
  --nohup           Force nohup mode instead of tmux
  --dry-run         Print command and exit
  -h, --help        Show this help

Examples:
  ./run_conformance_safe.sh
  ./run_conformance_safe.sh --resume
  ./run_conformance_safe.sh --output data/results/full_results/trigger_results_full.csv --resume
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      INPUT="$2"
      shift 2
      ;;
    --output)
      OUTPUT="$2"
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

if [[ ! -f "$ROOT_DIR/main_per_sbt.py" ]]; then
  echo "main_per_sbt.py not found in $ROOT_DIR" >&2
  exit 1
fi

LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/main_per_sbt_${TIMESTAMP}.log"

CMD=("$PYTHON_BIN" "$ROOT_DIR/main_per_sbt.py" "--input" "$INPUT" "--output" "$OUTPUT")

if [[ "$RESUME" -eq 1 ]]; then
  CMD+=("--resume")
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
  echo "PID: $(pgrep -n -f 'main_per_sbt.py' || true)"
  echo "Log tail: tail -f '$LOG_FILE'"
fi
