#!/usr/bin/env bash
# Shared launcher settings. Set overrides in .env or MEDISCRIBE_ENV_FILE.
# LLM connection: MEDISCRIBE_LLM_BASE_URL, MEDISCRIBE_LLM_MODEL,
# MEDISCRIBE_LLM_API_KEY. Audio models: HF_TOKEN, MEDISCRIBE_MODEL_CACHE.
# MEDISCRIBE_ROLES_CONFIG selects a role configuration file.

MEDISCRIBE_SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export MEDISCRIBE_ROOT=$(cd "$MEDISCRIBE_SCRIPT_DIR/.." && pwd)

MEDISCRIBE_ENV_FILE=${MEDISCRIBE_ENV_FILE:-$MEDISCRIBE_ROOT/.env}
if [[ -f "$MEDISCRIBE_ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$MEDISCRIBE_ENV_FILE"
  set +a
fi

# Audio-model cache directory.
if [[ -n ${MEDISCRIBE_MODEL_CACHE:-} ]]; then
  export HF_HOME=${HF_HOME:-$MEDISCRIBE_MODEL_CACHE/huggingface}
  export TORCH_HOME=${TORCH_HOME:-$MEDISCRIBE_MODEL_CACHE/torch}
  export XDG_CACHE_HOME=${XDG_CACHE_HOME:-$MEDISCRIBE_MODEL_CACHE/xdg}   # openai-whisper
fi

# LLM connection
export MEDISCRIBE_LLM_BASE_URL=${MEDISCRIBE_LLM_BASE_URL:-}
export MEDISCRIBE_LLM_MODEL=${MEDISCRIBE_LLM_MODEL:-}
export MEDISCRIBE_LLM_API_KEY=${MEDISCRIBE_LLM_API_KEY:-}
export MEDISCRIBE_ROLES_CONFIG=${MEDISCRIBE_ROLES_CONFIG:-$MEDISCRIBE_ROOT/config/roles/clinical.json}

# --- interpreter for the pipeline -------------------------------------------
# PYTHON_BIN wins. Otherwise the conda env named by MEDISCRIBE_CONDA_ENV is
# located through conda, so the launchers work without activating it first.
export MEDISCRIBE_CONDA_ENV=${MEDISCRIBE_CONDA_ENV:-scribe}

mediscribe_python() {
  if [[ -n ${PYTHON_BIN:-} ]]; then
    echo "$PYTHON_BIN"
    return
  fi
  if [[ ${CONDA_DEFAULT_ENV:-} == "$MEDISCRIBE_CONDA_ENV" ]] && command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi
  local conda_exe=${CONDA_EXE:-$(command -v conda 2>/dev/null || true)}
  if [[ -n $conda_exe ]]; then
    local base
    base=$("$conda_exe" info --base 2>/dev/null || true)
    if [[ -n $base && -x "$base/envs/$MEDISCRIBE_CONDA_ENV/bin/python" ]]; then
      echo "$base/envs/$MEDISCRIBE_CONDA_ENV/bin/python"
      return
    fi
  fi
  command -v python3 || command -v python
}

# Put the interpreter's bin/ first on PATH so ffmpeg and ffprobe from the same
# environment are found even when the env is not activated.
mediscribe_use_python_path() {
  local bin_dir
  bin_dir=$(dirname "$1")
  export PATH="$bin_dir${PATH:+:$PATH}"
}
