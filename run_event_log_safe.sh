#!/usr/bin/env bash
set -euo pipefail

# Safe launcher for long prepare_event_log runs.
# - Uses tmux when available (recommended)
# - Falls back to nohup when tmux is unavailable
# - Writes timestamped logs and optional resume mode

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN_DEFAULT="$ROOT_DIR/.venv/bin/python"

INPUT="data/final/mimic_raw_data.parquet"
OUTPUT="data/final/icu_event_log_full.parquet"
BACKUP_EVERY=200
SESSION_NAME="eventlog"
STATE_FILE=""
BACKUP_DIR=""
MEMORY_LIMIT=""
SOURCE_TABLE_FILTER=""
RESUME=0
DRY_RUN=0
FORCE_NOHUP=0
SEED_CHECKPOINT=""
SEED_SKIP_COUNT=""

usage() {
  cat <<'EOF'
Usage:
  ./run_event_log_safe.sh [options]

Options:
  --input PATH            Input raw events file (default: data/final/mimic_raw_data.parquet)
  --output PATH           Output event log file (default: data/final/icu_event_log_full.parquet)
  --backup-every N        Backup checkpoint interval (default: 200)
  --resume                Resume from existing state/temp DB
  --state-file PATH       Custom state file path
  --source-table-filter X  Restrict to a raw source_table; default is no filter (full dataset)
  --backup-dir PATH       Custom backup directory path
  --memory-limit VALUE    Pass through to --memory-limit (e.g., 4GB)
  --seed-checkpoint PATH  Seed the run from an existing parquet checkpoint
  --seed-skip-count N     Skip the first N candidate stays when seeding
  --session NAME          tmux session name (default: eventlog)
  --nohup                 Force nohup mode instead of tmux
  --dry-run               Print command and exit
  -h, --help              Show this help

Examples:
  ./run_event_log_safe.sh
  ./run_event_log_safe.sh --resume
  ./run_event_log_safe.sh --output data/final/icu_event_log_full.parquet --backup-every 100
  ./run_event_log_safe.sh --seed-checkpoint data/final/icu_event_log_checkpoints/icu_event_log.checkpoint_0010000.parquet
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
    --backup-every)
      BACKUP_EVERY="$2"
      shift 2
      ;;
    --resume)
      RESUME=1
      shift
      ;;
    --state-file)
      STATE_FILE="$2"
      shift 2
      ;;
    --backup-dir)
      BACKUP_DIR="$2"
      shift 2
      ;;
    --memory-limit)
      MEMORY_LIMIT="$2"
      shift 2
      ;;
    --source-table-filter)
      SOURCE_TABLE_FILTER="$2"
      shift 2
      ;;
    --seed-checkpoint)
      SEED_CHECKPOINT="$2"
      shift 2
      ;;
    --seed-skip-count)
      SEED_SKIP_COUNT="$2"
      shift 2
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

if [[ ! -f "$ROOT_DIR/prepare_event_log.py" ]]; then
  echo "prepare_event_log.py not found in $ROOT_DIR" >&2
  exit 1
fi

if [[ "$BACKUP_EVERY" =~ ^[0-9]+$ ]]; then
  :
else
  echo "--backup-every must be a non-negative integer" >&2
  exit 1
fi

if [[ "$BACKUP_EVERY" -lt 0 ]]; then
  echo "--backup-every must be >= 0" >&2
  exit 1
fi

LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/prepare_event_log_${TIMESTAMP}.log"

CMD=("$PYTHON_BIN" "$ROOT_DIR/prepare_event_log.py" "--input" "$INPUT" "--output" "$OUTPUT" "--backup-every" "$BACKUP_EVERY" "--use-all-data")

if [[ -n "$SOURCE_TABLE_FILTER" ]]; then
  CMD+=("--source-table-filter" "$SOURCE_TABLE_FILTER")
fi

if [[ "$RESUME" -eq 1 ]]; then
  CMD+=("--resume")
fi

if [[ -n "$STATE_FILE" ]]; then
  CMD+=("--state-file" "$STATE_FILE")
fi

if [[ -n "$BACKUP_DIR" ]]; then
  CMD+=("--backup-dir" "$BACKUP_DIR")
fi

if [[ -n "$MEMORY_LIMIT" ]]; then
  CMD+=("--memory-limit" "$MEMORY_LIMIT")
fi

if [[ -n "$SEED_CHECKPOINT" ]]; then
  CMD+=("--seed-checkpoint" "$SEED_CHECKPOINT")
fi

if [[ -n "$SEED_SKIP_COUNT" ]]; then
  CMD+=("--seed-skip-count" "$SEED_SKIP_COUNT")
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
  echo "Log tail:   tail -f '$LOG_FILE'"
else
  (cd "$ROOT_DIR" && nohup "${CMD[@]}" > "$LOG_FILE" 2>&1 &)
  echo "Started with nohup in background."
  echo "PID: $(pgrep -n -f 'prepare_event_log.py' || true)"
  echo "Log tail: tail -f '$LOG_FILE'"
fi
