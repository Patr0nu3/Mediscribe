#!/usr/bin/env bash
# Run the Mediscribe pipeline from the command line.
#
#   ./scripts/run.sh                       # everything in data/input/
#   ./scripts/run.sh path/to/visit.m4a     # one file
#   ./scripts/run.sh data/input --keep-intermediate --debug-json
#
# Extra flags are passed to src/offline.py (see `python src/offline.py -h`).
# Configure the LLM endpoint and model in .env before processing.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

PIPELINE_SCRIPT="$MEDISCRIBE_ROOT/src/offline.py"
DATA_ROOT="$MEDISCRIBE_ROOT/data"
DEFAULT_INPUT_PATH="$DATA_ROOT/input"
INTERMEDIATE_ROOT="$DATA_ROOT/intermediate"
OUTPUT_ROOT="$DATA_ROOT/output"

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  PYTHON_CMD=$(mediscribe_python)
  exec "$PYTHON_CMD" "$PIPELINE_SCRIPT" --help
fi

INPUT_PATH="$DEFAULT_INPUT_PATH"
if [[ $# -gt 0 && ${1:0:1} != "-" ]]; then
  INPUT_PATH=$1
  shift
fi

if [[ ! -f "$PIPELINE_SCRIPT" ]]; then
  echo "Pipeline script not found: $PIPELINE_SCRIPT" >&2
  exit 1
fi

mkdir -p "$DEFAULT_INPUT_PATH" "$INTERMEDIATE_ROOT" "$OUTPUT_ROOT"

if [[ ! -e "$INPUT_PATH" ]]; then
  echo "Input path does not exist: $INPUT_PATH" >&2
  exit 1
fi

PYTHON_CMD=$(mediscribe_python)
mediscribe_use_python_path "$PYTHON_CMD"

cd "$MEDISCRIBE_ROOT"
exec "$PYTHON_CMD" "$PIPELINE_SCRIPT" "$INPUT_PATH" \
  --intermediate-root "$INTERMEDIATE_ROOT" \
  --output-root "$OUTPUT_ROOT" \
  "$@"
