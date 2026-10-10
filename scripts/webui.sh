#!/usr/bin/env bash
# Start the Mediscribe transcript editor.
#
#   ./scripts/webui.sh                 # http://127.0.0.1:7860
#   WEBUI_PORT=7861 ./scripts/webui.sh
#
# Extra flags are passed to src/WebUI/server.py (see `python3 src/WebUI/server.py -h`).
# The server itself needs only the Python standard library. The pipeline it
# runs for imported recordings uses the conda env from scripts/env.sh.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

WEBUI_SCRIPT="$MEDISCRIBE_ROOT/src/WebUI/server.py"
HOST=127.0.0.1
PORT=${WEBUI_PORT:-7860}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  SERVER_PYTHON=$(command -v python3 || command -v python)
  exec "$SERVER_PYTHON" "$WEBUI_SCRIPT" --help
fi

if [[ ! -f "$WEBUI_SCRIPT" ]]; then
  echo "WebUI script not found: $WEBUI_SCRIPT" >&2
  exit 1
fi

mkdir -p "$MEDISCRIBE_ROOT/data/input" "$MEDISCRIBE_ROOT/data/intermediate" "$MEDISCRIBE_ROOT/data/output"

# The server runs on any Python 3; the pipeline interpreter is resolved by the
# server itself (MEDISCRIBE_CONDA_ENV / PYTHON_BIN), so only export the hint.
SERVER_PYTHON=$(command -v python3 || command -v python)

echo "Starting Mediscribe WebUI on http://localhost:${PORT}"
cd "$MEDISCRIBE_ROOT"
exec "$SERVER_PYTHON" "$WEBUI_SCRIPT" \
  --host "$HOST" \
  --port "$PORT" \
  --project-root "$MEDISCRIBE_ROOT" \
  --conda-env "$MEDISCRIBE_CONDA_ENV" \
  --llm-base-url "$MEDISCRIBE_LLM_BASE_URL" \
  --llm-model "$MEDISCRIBE_LLM_MODEL" \
  "$@"
