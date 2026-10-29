#!/usr/bin/env python3

from __future__ import annotations

import argparse
import errno
import hashlib
import io
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
import zipfile
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

# The editor shares the pipeline's text helpers and transcript line grammar.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mediscribe_v2.bundle import BundleConflictError, export_bundle, import_bundle  # noqa: E402
from mediscribe_v2.common import (  # noqa: E402
    LLM_API_KEY_DEFAULT,
    LLM_BASE_URL_DEFAULT,
    LLM_MODEL_DEFAULT,
    LLMUnavailableError,
    ROLE_OPTIONS,
    join_text_pieces,
    turn_word_count_from_text,
    validate_llm_config,
    wait_for_llm,
    write_json,
)
from mediscribe_v2.render import (  # noqa: E402
    LOW_CONFIDENCE_THRESHOLD,
    has_obvious_render_boundary,
    render_block_items,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# The pipeline code lives next to this server; --project-root only moves data/.
WORKER_SCRIPT = Path(__file__).resolve().parents[1] / "worker.py"
DATA_ROOT = PROJECT_ROOT / "data"
INPUT_ROOT = DATA_ROOT / "input"
INTERMEDIATE_ROOT = DATA_ROOT / "intermediate"
OUTPUT_ROOT = DATA_ROOT / "output"
STATIC_ROOT = Path(__file__).resolve().parent / "static"
AUDIO_EXTENSIONS = (".wav", ".m4a", ".mp3", ".flac", ".aac", ".ogg", ".webm", ".mp4")
DEFAULT_SPEAKERS = ROLE_OPTIONS
DIARIZATION_SPEAKER_PATTERN = re.compile(r"^speaker[\s_-]*\d+$", re.IGNORECASE)
WORD_PATTERN = re.compile(r"\S+")
LOOPBACK_HOSTS = {"localhost", "127.0.0.1"}
DEFAULT_LLM_BASE_URL = LLM_BASE_URL_DEFAULT
DEFAULT_LLM_MODEL = LLM_MODEL_DEFAULT
UPLOAD_CHUNK_SIZE = 1024 * 1024
# Contiguous runs of turns flagged `unclear_intro` (the pipeline's non-clinical
# flag, surfaced as "unrelated" in the editor) export between explicit span
# markers so a reader sees exactly where the excluded stretch starts and ends.
UNRELATED_START_LINE = (
    "[Unrelated start]: The conversation below may be from a CRC or unrelated "
    "to the doctor-patient conversation."
)
UNRELATED_END_LINE = "[Unrelated end]"

# Conda env that holds the offline pipeline's heavy deps (torch/whisper/pyannote).
# This server only needs the stdlib, but the pipeline subprocess it spawns must run
# under this env. Overridable via --conda-env or the MEDISCRIBE_CONDA_ENV env var.
PIPELINE_CONDA_ENV = os.environ.get("MEDISCRIBE_CONDA_ENV", "scribe")
_RESOLVED_PIPELINE_PYTHON: dict[str, str] = {}


def resolve_pipeline_python(conda_env: str = "") -> str:
    """Pick the interpreter used to run the pipeline subprocess.

    Precedence: explicit PYTHON_BIN > the current interpreter if it already lives in
    the target conda env > that env's python discovered via conda > the current
    interpreter (with a warning). This lets `python3 server.py` launch the pipeline
    correctly even when the target env was never activated.
    """
    override = os.environ.get("PYTHON_BIN")
    if override:
        return override

    env_name = conda_env or PIPELINE_CONDA_ENV
    if not env_name:
        return sys.executable
    if env_name in _RESOLVED_PIPELINE_PYTHON:
        return _RESOLVED_PIPELINE_PYTHON[env_name]

    # Already running inside the target env (e.g. the user activated it first).
    marker = f"{os.sep}envs{os.sep}{env_name}{os.sep}"
    if marker in sys.executable or os.environ.get("CONDA_DEFAULT_ENV") == env_name:
        _RESOLVED_PIPELINE_PYTHON[env_name] = sys.executable
        return sys.executable

    conda_exe = os.environ.get("CONDA_EXE") or shutil.which("conda")
    if conda_exe:
        try:
            base = subprocess.run(
                [conda_exe, "info", "--base"],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            base = ""
        if base:
            candidate = Path(base) / "envs" / env_name / "bin" / "python"
            if candidate.is_file():
                _RESOLVED_PIPELINE_PYTHON[env_name] = str(candidate)
                return str(candidate)

    print(
        f"WARNING: conda env '{env_name}' not found; running the pipeline with "
        f"{sys.executable}. Set PYTHON_BIN or activate the env if imports fail.",
        flush=True,
    )
    _RESOLVED_PIPELINE_PYTHON[env_name] = sys.executable
    return sys.executable


def pipeline_subprocess_env(python_bin: str) -> dict[str, str]:
    """Environment for the pipeline subprocess.

    Running an env's python without activating the env leaves the env's ``bin/`` off
    PATH, so tools the pipeline shells out to (ffmpeg via pydub/whisper, etc.) are not
    found. Prepend the interpreter's directory to PATH and expose CONDA_PREFIX so those
    binaries resolve as if the env were activated.
    """
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    bin_dir = os.path.dirname(os.path.abspath(python_bin)) if python_bin else ""
    if bin_dir:
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        prefix = os.path.dirname(bin_dir)
        if os.path.isdir(os.path.join(prefix, "conda-meta")):
            env["CONDA_PREFIX"] = prefix
    return env


_RESOLVED_FFPROBE: dict[str, str | None] = {}


def resolve_ffprobe() -> str | None:
    """Locate ffprobe, falling back to the pipeline conda env's bin.

    The WebUI process may run without the env's bin on PATH, so a bare which() can
    miss the ffprobe that ships in the scribe env; without it non-wav durations come
    back as 0 and the dashboard shows "Unknown" length.
    """
    if "path" in _RESOLVED_FFPROBE:
        return _RESOLVED_FFPROBE["path"]
    found = shutil.which("ffprobe")
    if not found:
        bin_dir = os.path.dirname(resolve_pipeline_python())
        candidate = os.path.join(bin_dir, "ffprobe")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            found = candidate
    _RESOLVED_FFPROBE["path"] = found
    return found


class ClientDisconnected(Exception):
    """Raised when a browser closes a streaming response before it finishes."""


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def is_diarization_speaker_label(value: Any) -> bool:
    return bool(DIARIZATION_SPEAKER_PATTERN.fullmatch(clean_text(value)))


def speaker_label(value: Any, default: str = "Unknown") -> str:
    text = clean_text(value)
    if text and not is_diarization_speaker_label(text):
        return text
    return default


def speaker_list(values: Any) -> list[str]:
    seen: list[str] = []
    if not isinstance(values, (list, tuple)):
        return seen
    for value in values:
        label = speaker_label(value, "")
        if label and label not in seen:
            seen.append(label)
    return seen


def safe_session_name(name: str) -> str:
    decoded = unquote(name)
    stripped = decoded.strip()
    if not stripped or "/" in decoded or "\\" in decoded or stripped in {".", ".."}:
        raise ValueError("Invalid session name.")
    if any(part == ".." for part in Path(decoded).parts):
        raise ValueError("Invalid session name.")
    return decoded


def safe_input_filename(name: str) -> str:
    decoded = unquote(name).strip()
    if not decoded or "/" in decoded or "\\" in decoded:
        raise ValueError("Invalid input filename.")
    if decoded in {".", ".."} or any(part == ".." for part in Path(decoded).parts):
        raise ValueError("Invalid input filename.")
    if Path(decoded).suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError("Uploaded file is not a supported audio format.")
    return decoded


def is_loopback_address(value: str) -> bool:
    if value in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_or_default(path: Path, default: Any) -> Any:
    """Read JSON, treating a missing or unreadable/corrupt file as `default`.

    Listing and state files are caches the app can regenerate; a torn or
    truncated file must degrade gracefully instead of turning every dashboard
    refresh into a 500 ("Expecting value: line 1 column ..." errors).
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        print(f"WARNING: ignoring unreadable JSON at {path}", flush=True)
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def seconds(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return default


def playback_rate(value: Any) -> float | None:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if 0.5 <= rate <= 2.0:
        return round(rate, 2)
    return None


# Probing duration shells out to ffprobe for non-wav files; both dashboard
# listing endpoints call this for every file on every refresh, so memoize by
# (size, mtime) to keep refreshes fast and avoid a subprocess storm.
_DURATION_CACHE: dict[str, tuple[int, float, float]] = {}
_DURATION_CACHE_LOCK = threading.Lock()


def audio_duration_sec(path: Path | None) -> float:
    if path is None or not path.exists() or not path.is_file():
        return 0.0

    try:
        stat = path.stat()
    except OSError:
        return 0.0
    cache_key = str(path)
    with _DURATION_CACHE_LOCK:
        cached = _DURATION_CACHE.get(cache_key)
        if cached is not None and cached[0] == stat.st_size and cached[1] == stat.st_mtime:
            return cached[2]

    duration = _probe_audio_duration_sec(path)
    with _DURATION_CACHE_LOCK:
        _DURATION_CACHE[cache_key] = (stat.st_size, stat.st_mtime, duration)
    return duration


def _probe_audio_duration_sec(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as handle:
                frame_rate = handle.getframerate()
                if frame_rate > 0:
                    return seconds(handle.getnframes() / frame_rate)
        except (wave.Error, OSError, EOFError):
            pass

    ffprobe = resolve_ffprobe()
    if not ffprobe:
        return 0.0
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0.0
    return seconds(result.stdout.strip(), 0.0)


def preferred_turn_label(turn: dict[str, Any]) -> str:
    for key in ("label", "final_role", "assigned_role", "speaker", "raw_speaker"):
        label = speaker_label(turn.get(key), "")
        if label:
            return label
    return "Unknown"


def synthetic_words(text: str, start_sec: float, end_sec: float, turn_id: str) -> list[dict[str, Any]]:
    matches = list(WORD_PATTERN.finditer(text))
    if not matches:
        return []

    duration = max(0.01, end_sec - start_sec)
    step = duration / len(matches)
    words = []
    for index, match in enumerate(matches):
        word_start = round(start_sec + step * index, 3)
        word_end = round(start_sec + step * (index + 1), 3)
        words.append(
            {
                "id": f"{turn_id}-w{index}",
                "text": match.group(0),
                "start_sec": word_start,
                "end_sec": max(word_end, word_start + 0.01),
                "manual": True,
            }
        )
    return words


def coerce_word(word: dict[str, Any], turn_id: str, index: int, fallback_start: float, fallback_end: float) -> dict[str, Any]:
    text = clean_text(word.get("text") or word.get("raw_text") or word.get("word"))
    start_sec = seconds(word.get("start_sec"), fallback_start)
    end_sec = seconds(word.get("end_sec"), fallback_end)
    if end_sec <= start_sec:
        end_sec = round(start_sec + 0.01, 3)
    clean_word = {
        "id": clean_text(word.get("id")) or f"{turn_id}-w{index}",
        "text": text,
        "start_sec": start_sec,
        "end_sec": end_sec,
        "confidence": word.get("confidence", word.get("speaker_confidence", word.get("probability"))),
        "speaker": clean_text(word.get("speaker") or word.get("candidate_speaker")),
        "manual": bool(word.get("manual", False)),
    }
    for key in ("timing_source", "copied_from_word_id", "inherited_from_word_id"):
        value = clean_text(word.get(key))
        if value:
            clean_word[key] = value
    return clean_word


def canonical_text_boundary(
    word: dict[str, Any],
    *,
    edge: str,
) -> dict[str, Any] | None:
    if edge not in {"start", "end"}:
        raise ValueError(f"Unsupported canonical text edge: {edge}")

    document_start = word.get("document_char_start")
    document_end = word.get("document_char_end")
    if document_start is not None and document_end is not None:
        key: list[Any] = ["document", str(word.get("asr_run_id") or "")]
        offset = document_start if edge == "start" else document_end
    else:
        canonical_start = word.get("canonical_char_start")
        canonical_end = word.get("canonical_char_end")
        if canonical_start is None or canonical_end is None:
            return None
        key = [
            "segment",
            str(word.get("asr_run_id") or ""),
            int(word.get("segment_index", 0)),
        ]
        offset = canonical_start if edge == "start" else canonical_end

    try:
        return {"key": key, "offset": int(offset)}
    except (TypeError, ValueError):
        return None


def sanitize_text_provenance(
    value: Any,
    *,
    text: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or clean_text(value.get("text")) != text:
        return None
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, dict) or not isinstance(end, dict):
        return None
    if not isinstance(start.get("key"), list) or not isinstance(end.get("key"), list):
        return None
    try:
        start_offset = int(start["offset"])
        end_offset = int(end["offset"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "text": text,
        "start": {"key": list(start["key"]), "offset": start_offset},
        "end": {"key": list(end["key"]), "offset": end_offset},
        "leading_space": bool(value.get("leading_space", False)),
    }


def turn_text_provenance(
    turn: dict[str, Any],
    *,
    text: str,
    raw_words: list[dict[str, Any]],
) -> dict[str, Any] | None:
    preserved = sanitize_text_provenance(turn.get("text_provenance"), text=text)
    if preserved is not None:
        return preserved
    if not text or not raw_words:
        return None

    first_word = raw_words[0]
    last_word = raw_words[-1]
    start = canonical_text_boundary(first_word, edge="start")
    end = canonical_text_boundary(last_word, edge="end")
    if start is None or end is None:
        return None

    first_raw_text = str(
        first_word.get("raw_text")
        or first_word.get("text")
        or first_word.get("word")
        or ""
    )
    return {
        "text": text,
        "start": start,
        "end": end,
        "leading_space": bool(first_raw_text[:1].isspace()),
    }


def coerce_turn(turn: dict[str, Any], index: int) -> dict[str, Any]:
    turn_id = clean_text(turn.get("id")) or f"turn-{index}"
    start_sec = seconds(turn.get("start_sec"), float(index))
    end_sec = seconds(turn.get("end_sec"), start_sec + 0.01)
    if end_sec <= start_sec:
        end_sec = round(start_sec + 0.01, 3)
    text = clean_text(turn.get("text"))
    label = preferred_turn_label(turn)
    source = clean_text(turn.get("source")) or "pipeline"

    raw_words = turn.get("words") if isinstance(turn.get("words"), list) else []
    text_provenance = turn_text_provenance(
        turn,
        text=text,
        raw_words=raw_words,
    )
    if raw_words:
        words = [
            coerce_word(word, turn_id, word_index, start_sec, end_sec)
            for word_index, word in enumerate(raw_words)
            if clean_text(word.get("text") or word.get("raw_text") or word.get("word"))
        ]
    else:
        words = synthetic_words(text, start_sec, end_sec, turn_id)

    explicit_timing_reliable = turn.get("timing_reliable", turn.get("timingReliable"))
    if explicit_timing_reliable is None:
        all_words_manual = bool(words) and all(bool(word.get("manual")) for word in words)
        timing_reliable = source != "text" and not (source == "editor" and all_words_manual and end_sec - start_sec <= 0.75)
    else:
        timing_reliable = bool(explicit_timing_reliable)

    return {
        "id": turn_id,
        "label": label,
        "raw_speaker": clean_text(turn.get("raw_speaker") or turn.get("speaker")),
        "start_sec": start_sec,
        "end_sec": end_sec,
        "text": text,
        "bookmarked": bool(turn.get("bookmarked", False)),
        "words": words,
        "timing_reliable": timing_reliable,
        "speaker_confidence": turn.get("speaker_confidence"),
        "final_role": speaker_label(turn.get("final_role"), "") or None,
        "assigned_role": speaker_label(turn.get("assigned_role"), "") or None,
        "final_role_confidence": turn.get("final_role_confidence"),
        "role_confidence": turn.get("role_confidence"),
        "refined_by_llm": bool(turn.get("refined_by_llm", False)),
        "mark_unknown": bool(turn.get("mark_unknown", False)),
        "unclear_intro": bool(turn.get("unclear_intro", False)),
        "playback_rate": playback_rate(turn.get("playback_rate", turn.get("playbackRate"))),
        "source": source,
        "text_provenance": text_provenance,
    }


def parse_transcript_text(path: Path) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    current_minute = 0
    line_index = 0
    in_unrelated = False
    timestamp_pattern = re.compile(r"^\[(\d{2}):00\]$")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        timestamp_match = timestamp_pattern.match(line)
        if timestamp_match:
            current_minute = int(timestamp_match.group(1))
            line_index = 0
            continue
        if line.startswith("[Unrelated start]"):
            in_unrelated = True
            continue
        if line.startswith("[Unrelated end]"):
            in_unrelated = False
            continue
        if line.startswith("[Unclear]:"):
            # Legacy per-minute notifier; the span markers replaced it.
            continue
        if line == "No one spoke during this time." or ":" not in line:
            continue

        label, text = line.split(":", 1)
        start_sec = current_minute * 60 + line_index * 0.5
        turns.append(
            {
                "label": clean_text(label),
                "raw_speaker": clean_text(label),
                "start_sec": start_sec,
                "end_sec": start_sec + 0.5,
                "text": clean_text(text),
                "unclear_intro": in_unrelated,
                "source": "text",
            }
        )
        line_index += 1
    return [coerce_turn(turn, index) for index, turn in enumerate(turns)]


def collect_speakers(turns: list[dict[str, Any]]) -> list[str]:
    seen = speaker_list(list(DEFAULT_SPEAKERS))
    for turn in turns:
        for label in (turn.get("label"), turn.get("raw_speaker")):
            text = speaker_label(label, "")
            if text and text not in seen:
                seen.append(text)
    return seen


def sanitize_saved_turns(turns: Any) -> list[dict[str, Any]]:
    if not isinstance(turns, list):
        raise ValueError("Payload must include a turns list.")

    clean_turns = []
    for index, raw_turn in enumerate(turns):
        if not isinstance(raw_turn, dict):
            continue
        turn = coerce_turn(raw_turn, index)
        turn["source"] = "editor"
        clean_turns.append(turn)
    return clean_turns


def revision_state(name: str, speakers: list[str], finished: bool, turns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "name": name,
        "speakers": speakers,
        "finished": finished,
        "turns": turns,
    }


def revision_state_from_payload(name: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("turns"), list):
        return None
    speakers = payload.get("speakers")
    if not isinstance(speakers, list):
        speakers = []
    return revision_state(
        name,
        speaker_list(speakers),
        bool(payload.get("finished")),
        [coerce_turn(turn, index) for index, turn in enumerate(payload.get("turns", [])) if isinstance(turn, dict)],
    )


def clean_revision_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        text = clean_text(value)
        if text:
            cleaned.append(text)
    return cleaned[:200]


def sanitize_revision_events(events: Any, session_name: str) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []

    clean_events: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = clean_text(event.get("kind") or event.get("action") or event.get("type")) or "edit"
        clean_event = {
            "event_id": clean_text(event.get("event_id")) or uuid.uuid4().hex,
            "created_at": clean_text(event.get("created_at")) or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session": session_name,
            "kind": kind,
            "audio_time_sec": seconds(event.get("audio_time_sec"), 0.0),
            "turn_ids": clean_revision_string_list(event.get("turn_ids")),
            "word_ids": clean_revision_string_list(event.get("word_ids")),
            "before": event.get("before") if isinstance(event.get("before"), dict) else {},
            "after": event.get("after") if isinstance(event.get("after"), dict) else {},
            "meta": event.get("meta") if isinstance(event.get("meta"), dict) else {},
        }
        clean_events.append(clean_event)
    return clean_events


def final_turn_label(turn: dict[str, Any], low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD) -> str:
    label = speaker_label(turn.get("final_role") or turn.get("assigned_role") or turn.get("label"))
    confidence = turn.get("final_role_confidence", turn.get("role_confidence"))
    try:
        role_confidence = float(confidence)
    except (TypeError, ValueError):
        role_confidence = 1.0

    if label == "Unknown":
        return "Unknown"
    if turn.get("refined_by_llm") and turn.get("mark_unknown"):
        return f"[Unknown] {label}"
    if role_confidence < low_confidence_threshold:
        return "Unknown"
    return label


def trusted_text_provenance(item: dict[str, Any]) -> dict[str, Any] | None:
    return sanitize_text_provenance(
        item.get("text_provenance"),
        text=clean_text(item.get("text")),
    )


def render_run_text(run: list[dict[str, Any]]) -> str:
    merged = clean_text(run[0].get("text")) if run else ""
    for previous, current in zip(run, run[1:]):
        current_text = clean_text(current.get("text"))
        previous_provenance = trusted_text_provenance(previous)
        current_provenance = trusted_text_provenance(current)
        contiguous = bool(
            previous_provenance
            and current_provenance
            and previous_provenance["end"]["key"] == current_provenance["start"]["key"]
            and previous_provenance["end"]["offset"] == current_provenance["start"]["offset"]
        )
        if contiguous:
            separator = " " if current_provenance["leading_space"] else ""
            merged = f"{merged}{separator}{current_text.lstrip()}"
        else:
            merged = join_text_pieces([merged, current_text])
    return re.sub(r"\s+", " ", merged).strip()


def final_render_items_for_block(block_turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [
        {
            "label": final_turn_label(turn),
            "text": clean_text(turn.get("text")),
            "text_provenance": turn.get("text_provenance"),
        }
        for turn in block_turns
        if clean_text(turn.get("text"))
    ]
    return render_block_items(items, merge_text=render_run_text)


def unrelated_run_boundaries(ordered_turns: list[dict[str, Any]]) -> tuple[set[int], set[int]]:
    """Object ids of the turns that open and close each contiguous unrelated run."""
    run_starts: set[int] = set()
    run_ends: set[int] = set()
    previous_turn: dict[str, Any] | None = None
    for turn in ordered_turns:
        flagged = bool(turn.get("unclear_intro"))
        previously_flagged = bool(previous_turn and previous_turn.get("unclear_intro"))
        if flagged and not previously_flagged:
            run_starts.add(id(turn))
        if not flagged and previously_flagged and previous_turn is not None:
            run_ends.add(id(previous_turn))
        previous_turn = turn
    if previous_turn is not None and previous_turn.get("unclear_intro"):
        run_ends.add(id(previous_turn))
    return run_starts, run_ends


def rendered_segment_lines(segment_turns: list[dict[str, Any]]) -> list[str]:
    return [f"{item['label']}: {item['text']}" for item in final_render_items_for_block(segment_turns)]


def render_final_transcript_text(turns: list[dict[str, Any]], timeline_minutes: list[int] | None = None) -> str:
    role_turns = [turn for turn in turns if clean_text(turn.get("text"))]
    if not role_turns and not timeline_minutes:
        return ""

    ordered_turns = sorted(role_turns, key=lambda item: seconds(item.get("start_sec")))
    run_starts, run_ends = unrelated_run_boundaries(ordered_turns)

    blocks: dict[int, list[dict[str, Any]]] = {}
    for turn in ordered_turns:
        blocks.setdefault(int(seconds(turn.get("start_sec")) // 60), []).append(turn)

    if timeline_minutes:
        ordered_minutes = sorted(dict.fromkeys(timeline_minutes))
    else:
        start_minute = int(min(seconds(turn.get("start_sec")) for turn in role_turns) // 60)
        end_minute = int(max(seconds(turn.get("end_sec")) for turn in role_turns) // 60)
        ordered_minutes = list(range(start_minute, end_minute + 1))

    lines: list[str] = []
    for minute in ordered_minutes:
        lines.append("")
        lines.append(f"[{minute:02d}:00]")
        block_turns = blocks.get(minute, [])
        if not block_turns:
            lines.append("No one spoke during this time.")
            continue
        # Emit the span markers exactly where the unrelated run starts and ends;
        # same-label condensing runs per segment so text never merges across a marker.
        segment: list[dict[str, Any]] = []
        for turn in block_turns:
            if id(turn) in run_starts:
                lines.extend(rendered_segment_lines(segment))
                segment = []
                lines.append(UNRELATED_START_LINE)
            segment.append(turn)
            if id(turn) in run_ends:
                lines.extend(rendered_segment_lines(segment))
                segment = []
                lines.append(UNRELATED_END_LINE)
        lines.extend(rendered_segment_lines(segment))
    return "\n".join(lines)


@dataclass(frozen=True)
class SessionPaths:
    name: str
    intermediate_dir: Path
    output_dir: Path
    editor_json: Path
    debug_json: Path
    aligned_json: Path
    final_txt: Path
    canonical_json: Path
    revisions_jsonl: Path
    revision_snapshots: Path
    pipeline_state: Path


class EditorStore:
    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = project_root.resolve()
        self.data_root = self.project_root / "data"
        self.intermediate_root = self.data_root / "intermediate"
        self.output_root = self.data_root / "output"
        self.input_root = self.data_root / "input"

    def paths_for(self, name: str) -> SessionPaths:
        session_name = safe_session_name(name)
        intermediate_dir = self.intermediate_root / session_name
        output_dir = self.output_root / session_name
        return SessionPaths(
            name=session_name,
            intermediate_dir=intermediate_dir,
            output_dir=output_dir,
            editor_json=intermediate_dir / f"{session_name}_editor.json",
            debug_json=intermediate_dir / f"{session_name}_debug.json",
            aligned_json=intermediate_dir / f"{session_name}_sen_aligned_segments.json",
            final_txt=output_dir / f"{session_name}_aligned_transcript.txt",
            canonical_json=output_dir / f"{session_name}_canonical.json",
            revisions_jsonl=output_dir / f"{session_name}_revisions.jsonl",
            revision_snapshots=output_dir / f"{session_name}_revision_snapshots.json",
            pipeline_state=intermediate_dir / f"{session_name}_pipeline_state.json",
        )

    def load_editor_payload(self, paths: SessionPaths) -> dict[str, Any]:
        payload = read_json_or_default(paths.editor_json, {})
        return payload if isinstance(payload, dict) else {}

    def session_finished(self, paths: SessionPaths) -> bool:
        return bool(self.load_editor_payload(paths).get("finished"))

    def load_pipeline_state(self, paths: SessionPaths) -> dict[str, Any]:
        payload = read_json_or_default(paths.pipeline_state, {})
        return payload if isinstance(payload, dict) else {}

    def prune_empty_input_parents(self, path: Path) -> None:
        input_root = self.input_root.resolve()
        parent = path.parent.resolve()
        while parent != input_root and parent.is_relative_to(input_root):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent.resolve()

    def selected_artifact_paths(self, root: Path, selected_names: set[str]) -> list[Path]:
        if not root.exists():
            return []
        paths: list[Path] = []
        for name in selected_names:
            exact = root / name
            if exact.exists():
                paths.append(exact)
        for child in root.iterdir():
            child_name = child.name
            child_stem = child.stem
            if child_name in selected_names:
                paths.append(child)
                continue
            if child.is_file() and (child_stem in selected_names or any(child_name.startswith(f"{name}_") for name in selected_names)):
                paths.append(child)
        unique: list[Path] = []
        seen: set[Path] = set()
        for path in paths:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(path)
        return unique

    def find_input_audio_path(self, name: str) -> Path | None:
        session_name = safe_session_name(name)
        candidates = [self.input_root / session_name]
        candidates.extend(self.input_root / f"{session_name}{extension}" for extension in AUDIO_EXTENSIONS)

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        if self.input_root.exists():
            for candidate in self.input_root.rglob("*"):
                if candidate.is_file() and candidate.suffix.lower() in AUDIO_EXTENSIONS and candidate.stem == session_name:
                    return candidate
        return None

    def session_files_exist(self, paths: SessionPaths) -> bool:
        return any(
            path.exists()
            for path in (paths.editor_json, paths.debug_json, paths.aligned_json, paths.canonical_json, paths.final_txt)
        )

    def list_sessions(self) -> list[dict[str, Any]]:
        names: set[str] = set()
        for root in (self.intermediate_root, self.output_root):
            if root.exists():
                names.update(path.name for path in root.iterdir() if path.is_dir())

        sessions = []
        for name in sorted(names):
            paths = self.paths_for(name)
            input_audio_path = self.find_input_audio_path(name)
            audio_path = self.find_audio_path(name)
            has_session = self.session_files_exist(paths)
            known_files = [
                paths.editor_json,
                paths.debug_json,
                paths.aligned_json,
                paths.final_txt,
                paths.canonical_json,
                paths.revisions_jsonl,
                paths.revision_snapshots,
                paths.pipeline_state,
                audio_path,
            ]
            existing_files = [path for path in known_files if path is not None and path.exists()]
            modified = max((path.stat().st_mtime for path in existing_files), default=0.0)
            metadata_audio_path = input_audio_path or audio_path
            audio_size = metadata_audio_path.stat().st_size if metadata_audio_path is not None and metadata_audio_path.exists() else 0
            audio_duration = audio_duration_sec(metadata_audio_path) if metadata_audio_path is not None else 0.0
            pipeline_state = self.load_pipeline_state(paths)
            raw_state = clean_text(pipeline_state.get("state")) or "ready"
            state_reason = clean_text(pipeline_state.get("reason"))
            if has_session:
                if input_audio_path is None:
                    state = "review_only"
                    state_reason = "Input audio is absent. Transcript review remains available."
                else:
                    state = "ready"
                    state_reason = ""
            elif input_audio_path is None and paths.intermediate_dir.exists():
                state = "cannot_resume"
                state_reason = "Input audio is absent. Remove this processing artifact or restore the audio."
            elif raw_state == "awaiting_resume":
                state = "awaiting_resume" if input_audio_path is not None else "cannot_resume"
                if state == "cannot_resume":
                    state_reason = "Input audio is absent. This job cannot resume."
            else:
                state = raw_state
            sessions.append(
                {
                    "name": name,
                    "has_editor": paths.editor_json.exists(),
                    "has_revisions": paths.revisions_jsonl.exists() or paths.revision_snapshots.exists(),
                    "has_debug": paths.debug_json.exists(),
                    "has_aligned_json": paths.aligned_json.exists(),
                    "has_final": paths.final_txt.exists(),
                    "has_input": input_audio_path is not None,
                    "has_audio": audio_path is not None,
                    "finished": self.session_finished(paths),
                    "state": state,
                    "state_reason": state_reason,
                    "modified": modified,
                    "audio_size": audio_size,
                    "audio_duration_sec": audio_duration,
                }
            )
        return sorted(sessions, key=lambda item: (-float(item["modified"]), item["name"]))

    def find_audio_path(self, name: str) -> Path | None:
        session_name = safe_session_name(name)
        paths = self.paths_for(session_name)
        candidates = [
            paths.intermediate_dir / f"{session_name}_converted.wav",
            paths.intermediate_dir / f"{session_name}_cleaned.wav",
            self.input_root / session_name,
        ]
        candidates.extend(self.input_root / f"{session_name}{extension}" for extension in AUDIO_EXTENSIONS)

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        if self.input_root.exists():
            for candidate in self.input_root.rglob("*"):
                if candidate.is_file() and candidate.suffix.lower() in AUDIO_EXTENSIONS and candidate.stem == session_name:
                    return candidate
        return None

    def list_input_audio_files(self) -> list[dict[str, Any]]:
        if not self.input_root.exists():
            return []

        files = []
        for path in sorted(self.input_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            relative_path = path.relative_to(self.input_root).as_posix()
            stat = path.stat()
            duration = audio_duration_sec(path)
            files.append(
                {
                    "path": relative_path,
                    "name": path.name,
                    "stem": path.stem,
                    "size": stat.st_size,
                    "duration_sec": duration,
                    "modified": stat.st_mtime,
                }
            )
        return files

    def unique_input_path(self, filename: str) -> Path:
        safe_name = safe_input_filename(filename)
        self.input_root.mkdir(parents=True, exist_ok=True)
        candidate = self.input_root / safe_name
        if not candidate.exists():
            return candidate

        stem = candidate.stem
        suffix = candidate.suffix
        counter = 2
        while True:
            numbered = self.input_root / f"{stem}_{counter}{suffix}"
            if not numbered.exists():
                return numbered
            counter += 1

    def _input_file_info(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "path": path.relative_to(self.input_root).as_posix(),
            "name": path.name,
            "stem": path.stem,
            "size": stat.st_size,
            "duration_sec": audio_duration_sec(path),
            "modified": stat.st_mtime,
        }

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(UPLOAD_CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _find_duplicate_input(self, *, size: int, sha256: str) -> Path | None:
        """Return an existing input audio file that is byte-identical to the upload."""
        if not self.input_root.exists():
            return None
        for path in sorted(self.input_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            try:
                if path.stat().st_size != size:
                    continue
                if self._hash_file(path) == sha256:
                    return path
            except OSError:
                continue
        return None

    def save_input_audio(
        self, filename: str, stream: Any, content_length: int, *, allow_duplicate: bool = False
    ) -> dict[str, Any]:
        """Store an uploaded recording in the input folder.

        Byte-identical audio already present is reported back as a duplicate (with the
        existing file's name) and not stored again, unless ``allow_duplicate`` is set:
        the WebUI asks the user first and then re-sends the confirmed files with it.
        """
        if content_length <= 0:
            raise ValueError("Uploaded audio file is empty.")

        safe_name = safe_input_filename(filename)
        self.input_root.mkdir(parents=True, exist_ok=True)

        # Stream to a temp file (non-audio suffix so scans ignore it) while hashing,
        # so we can skip the import entirely if the same audio is already present.
        temp_target = self.input_root / f".import-{uuid.uuid4().hex}.part"
        digest = hashlib.sha256()
        remaining = content_length
        try:
            with temp_target.open("xb") as handle:
                while remaining > 0:
                    chunk = stream.read(min(UPLOAD_CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ClientDisconnected()
                    handle.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
        except Exception:
            temp_target.unlink(missing_ok=True)
            raise

        size = temp_target.stat().st_size
        duplicate = None if allow_duplicate else self._find_duplicate_input(size=size, sha256=digest.hexdigest())
        if duplicate is not None:
            temp_target.unlink(missing_ok=True)
            info = self._input_file_info(duplicate)
            info["duplicate"] = True
            return info

        # Not already present. Reuse the name if free, otherwise keep this distinct
        # recording under a numbered name (it has different content from the existing one).
        target = self.unique_input_path(safe_name)
        try:
            temp_target.replace(target)
        except Exception:
            temp_target.unlink(missing_ok=True)
            raise

        info = self._input_file_info(target)
        info["duplicate"] = False
        return info

    def resolve_pipeline_input(self, relative_path: str | None) -> Path:
        if not relative_path:
            return self.input_root

        cleaned = unquote(str(relative_path)).strip()
        if not cleaned or cleaned in {".", "/"}:
            return self.input_root
        if cleaned.startswith("/") or "\\" in cleaned:
            raise ValueError("Input path must be relative to the input folder.")

        candidate = (self.input_root / cleaned).resolve()
        input_root = self.input_root.resolve()
        if not candidate.is_relative_to(input_root):
            raise ValueError("Input path must stay inside the input folder.")
        if not candidate.exists():
            raise FileNotFoundError(f"Input path not found: {cleaned}")
        if candidate.is_file() and candidate.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError("Selected input is not a supported audio file.")
        return candidate

    def load_turns(
        self,
        paths: SessionPaths,
        *,
        editor_payload: dict[str, Any] | None = None,
        debug_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if paths.editor_json.exists():
            payload = editor_payload if editor_payload is not None else self.load_editor_payload(paths)
            turns = payload.get("turns", [])
            if isinstance(turns, list) and turns:
                return [coerce_turn(turn, index) for index, turn in enumerate(turns)]

        if paths.debug_json.exists():
            payload = (
                debug_payload
                if debug_payload is not None
                else read_json_or_default(paths.debug_json, {})
            )
            turns = payload.get("merged_turns") if isinstance(payload, dict) else []
            if isinstance(turns, list) and turns:
                return [coerce_turn(turn, index) for index, turn in enumerate(turns)]

        if paths.aligned_json.exists():
            payload = read_json_or_default(paths.aligned_json, [])
            if isinstance(payload, dict):
                payload = payload.get("turns", [])
            if isinstance(payload, list) and payload:
                return [coerce_turn(turn, index) for index, turn in enumerate(payload)]

        # A run without --keep-intermediate leaves only output/; the canonical
        # evidence still holds the timed, role-labelled turns.
        if paths.canonical_json.exists():
            payload = read_json_or_default(paths.canonical_json, {})
            assignment = payload.get("role_assignment") if isinstance(payload, dict) else None
            turns = assignment.get("turns") if isinstance(assignment, dict) else None
            if isinstance(turns, list) and turns:
                return [coerce_turn(turn, index) for index, turn in enumerate(turns)]

        if paths.final_txt.exists():
            return parse_transcript_text(paths.final_txt)

        return []

    def load_diarization(
        self,
        paths: SessionPaths,
        *,
        debug_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        payload = (
            debug_payload
            if debug_payload is not None
            else read_json_or_default(paths.debug_json, {})
        )
        if not isinstance(payload, dict):
            return []
        diarization = payload.get("diarization", {})
        if not isinstance(diarization, dict):
            return []
        segments = diarization.get("alignment_segments_original") or diarization.get("alignment_segments") or []
        if not isinstance(segments, list):
            return []
        return [
            {
                "start_sec": seconds(segment.get("start_sec")),
                "end_sec": seconds(segment.get("end_sec")),
                "speaker": clean_text(segment.get("speaker")) or "Unknown",
            }
            for segment in segments
            if isinstance(segment, dict)
        ]

    def load_session(self, name: str) -> dict[str, Any]:
        paths = self.paths_for(name)
        editor_payload = self.load_editor_payload(paths) if paths.editor_json.exists() else {}
        raw_debug_payload = read_json_or_default(paths.debug_json, {}) if paths.debug_json.exists() else {}
        debug_payload = raw_debug_payload if isinstance(raw_debug_payload, dict) else {}
        turns = self.load_turns(
            paths,
            editor_payload=editor_payload,
            debug_payload=debug_payload,
        )
        audio_path = self.find_audio_path(paths.name)
        try:
            audio_stat = audio_path.stat() if audio_path is not None else None
        except OSError:
            audio_path = None
            audio_stat = None
        duration = max((seconds(turn.get("end_sec")) for turn in turns), default=0.0)
        return {
            "name": paths.name,
            "speakers": collect_speakers(turns),
            "role_options": list(DEFAULT_SPEAKERS),
            "turns": turns,
            "finished": bool(editor_payload.get("finished")),
            "diarization": self.load_diarization(paths, debug_payload=debug_payload),
            "audio": {
                "available": audio_path is not None,
                "url": f"/api/session/{quote(paths.name, safe='')}/audio" if audio_path is not None else None,
                "size_bytes": audio_stat.st_size if audio_stat is not None else 0,
                "version": (
                    f"{audio_stat.st_mtime_ns:x}-{audio_stat.st_size:x}"
                    if audio_stat is not None
                    else ""
                ),
            },
            "duration_sec": duration,
            "state": self.load_pipeline_state(paths),
            "paths": {
                "editor_json": str(paths.editor_json),
                "final_txt": str(paths.final_txt),
                "revisions_jsonl": str(paths.revisions_jsonl),
                "revision_snapshots": str(paths.revision_snapshots),
            },
        }

    def load_revisions(self, name: str) -> dict[str, Any]:
        paths = self.paths_for(name)
        snapshots = read_json_or_default(paths.revision_snapshots, {})
        if not isinstance(snapshots, dict):
            snapshots = {}
        return {
            "name": paths.name,
            "events": read_jsonl(paths.revisions_jsonl),
            "snapshots": snapshots,
            "paths": {
                "revisions_jsonl": str(paths.revisions_jsonl),
                "revision_snapshots": str(paths.revision_snapshots),
            },
        }

    def append_revision_events(self, paths: SessionPaths, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        paths.revisions_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with paths.revisions_jsonl.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
                handle.write("\n")

    def update_revision_snapshots(
        self,
        paths: SessionPaths,
        baseline: Any,
        previous_state: dict[str, Any] | None,
        latest_state: dict[str, Any],
        checkpoint: bool,
        checkpoint_kind: str,
        events: list[dict[str, Any]],
    ) -> int:
        existing = read_json_or_default(paths.revision_snapshots, {})
        if not isinstance(existing, dict):
            existing = {}

        clean_baseline = baseline if isinstance(baseline, dict) else None
        if not clean_baseline:
            clean_baseline = existing.get("baseline") if isinstance(existing.get("baseline"), dict) else None
        if not clean_baseline:
            clean_baseline = previous_state or latest_state

        checkpoints = existing.get("checkpoints") if isinstance(existing.get("checkpoints"), list) else []
        if checkpoint:
            checkpoint_before = previous_state or clean_baseline
            if checkpoints and isinstance(checkpoints[-1], dict) and isinstance(checkpoints[-1].get("after"), dict):
                checkpoint_before = checkpoints[-1]["after"]
            checkpoints.append(
                {
                    "checkpoint_id": uuid.uuid4().hex,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "kind": checkpoint_kind if checkpoint_kind in {"manual", "autosave"} else "manual",
                    "event_ids": [event["event_id"] for event in events],
                    "before": checkpoint_before,
                    "after": latest_state,
                }
            )
            checkpoints = checkpoints[-100:]

        write_json(
            paths.revision_snapshots,
            {
                "version": 1,
                "name": paths.name,
                "baseline": clean_baseline,
                "latest": latest_state,
                "checkpoints": checkpoints,
            },
        )
        return len(checkpoints)

    def save_session(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        paths = self.paths_for(name)
        previous_state = revision_state_from_payload(paths.name, self.load_editor_payload(paths))
        turns = sanitize_saved_turns(payload.get("turns"))
        speakers = payload.get("speakers")
        if not isinstance(speakers, list):
            speakers = collect_speakers(turns)
        else:
            speakers = speaker_list(speakers)
        finished = bool(payload.get("finished"))

        editor_payload = revision_state(paths.name, speakers, finished, turns)
        write_json(paths.editor_json, editor_payload)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        final_text = render_final_transcript_text(turns)
        paths.final_txt.write_text(final_text, encoding="utf-8")
        revision_events = sanitize_revision_events(payload.get("revision_events"), paths.name)
        self.append_revision_events(paths, revision_events)
        checkpoint_count = self.update_revision_snapshots(
            paths,
            payload.get("baseline"),
            previous_state,
            editor_payload,
            bool(payload.get("checkpoint")),
            clean_text(payload.get("checkpoint_kind")) or "manual",
            revision_events,
        )
        return {
            "ok": True,
            "editor_json": str(paths.editor_json),
            "final_txt": str(paths.final_txt),
            "revision_events": len(revision_events),
            "revision_checkpoints": checkpoint_count,
            "turn_count": len(turns),
        }

    def final_transcript_for_session(self, name: str) -> tuple[str, str]:
        paths = self.paths_for(name)
        turns = self.load_turns(paths)
        if not turns:
            raise FileNotFoundError(f"No transcript session found for {paths.name}.")
        return paths.final_txt.name, render_final_transcript_text(turns)

    def finished_final_transcripts_zip(self, names: list[str] | None = None) -> tuple[str, bytes, int]:
        selected_names = {safe_session_name(name) for name in names or [] if clean_text(name)}
        buffer = io.BytesIO()
        count = 0
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for session in self.list_sessions():
                if selected_names and session["name"] not in selected_names:
                    continue
                if not session.get("finished"):
                    continue
                try:
                    filename, transcript = self.final_transcript_for_session(session["name"])
                except FileNotFoundError:
                    continue
                archive.writestr(filename, transcript)
                count += 1

        if count == 0:
            raise FileNotFoundError("No finished transcript sessions are available to export.")
        filename = "mediscribe_selected_aligned_transcripts.zip" if selected_names else "mediscribe_finished_aligned_transcripts.zip"
        return filename, buffer.getvalue(), count

    def export_bundle_file(self, names: list[str]) -> Path:
        """Write the recordings to a temporary bundle zip; the caller removes it."""
        session_names = [safe_session_name(name) for name in names if clean_text(name)]
        if not session_names:
            raise ValueError("Select at least one recording to export.")
        self.data_root.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=self.data_root, prefix=".bundle-export-", suffix=".zip", delete=False)
        path = Path(handle.name)
        try:
            with handle:
                export_bundle(self.data_root, session_names, handle)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    def import_bundle_upload(
        self, stream: Any, content_length: int, *, replace: bool = False, busy: set[str] | None = None
    ) -> dict[str, Any]:
        """Receive an uploaded bundle zip and unpack it into the data folder."""
        if content_length <= 0:
            raise ValueError("Uploaded bundle is empty.")
        self.data_root.mkdir(parents=True, exist_ok=True)
        temp_target = self.data_root / f".bundle-upload-{uuid.uuid4().hex}.zip"
        try:
            with temp_target.open("xb") as handle:
                remaining = content_length
                while remaining > 0:
                    chunk = stream.read(min(UPLOAD_CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ClientDisconnected()
                    handle.write(chunk)
                    remaining -= len(chunk)
            return import_bundle(self.data_root, temp_target, replace=replace, busy=busy or set())
        finally:
            temp_target.unlink(missing_ok=True)

    def clear_selected(self, names: list[str]) -> dict[str, Any]:
        if not names:
            raise ValueError("Select at least one recording to clear.")
        selected_names = {safe_session_name(name) for name in names if clean_text(name)}
        if not selected_names:
            raise ValueError("Select at least one recording to clear.")

        removed: dict[str, int] = {"input": 0, "intermediate": 0, "output": 0}
        removed_inputs: set[Path] = set()
        for name in selected_names:
            if self.input_root.exists():
                for candidate in self.input_root.rglob("*"):
                    resolved_candidate = candidate.resolve()
                    should_remove = candidate.is_file() and candidate.stem == name
                    if should_remove and resolved_candidate not in removed_inputs:
                        candidate.unlink()
                        removed_inputs.add(resolved_candidate)
                        removed["input"] += 1
        for label, root in (("intermediate", self.intermediate_root), ("output", self.output_root)):
            for target in self.selected_artifact_paths(root, selected_names):
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                removed[label] += 1
        for path in removed_inputs:
            self.prune_empty_input_parents(path)
        return {"ok": True, "removed": removed}

    def prepare_reprocess_input(self, input_path: Path) -> dict[str, int]:
        removed: dict[str, int] = {"intermediate": 0, "output": 0}
        if not input_path.is_file():
            return removed
        paths = self.paths_for(input_path.stem)
        for label, target in (("intermediate", paths.intermediate_dir), ("output", paths.output_dir)):
            if not target.exists():
                continue
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed[label] += 1
        return removed

FILE_STAGE_TOTAL = 6
FILE_STAGE_LABELS = ["Prepare", "Transcribe", "Diarize", "Fuse", "Roles", "Render"]
WORKER_EVENT_PREFIX = "@@EVENT "
RUNNER_LOG_LIMIT = 600
FILE_HISTORY_LIMIT = 200
TERMINAL_FILE_STATUSES = ("succeeded", "failed", "awaiting_resume")


@dataclass
class PipelineFile:
    """One recording moving through the resident worker's two lanes."""

    name: str
    input_path: str
    job_id: int
    reprocess: bool = False
    resume: bool = False
    status: str = "queued"  # queued | running | succeeded | failed | awaiting_resume
    lane: str | None = None
    stage: str = ""
    stage_number: int = 0
    stage_total: int = FILE_STAGE_TOTAL
    stage_label: str = ""
    stage_started: float = 0.0
    queued_at: float = 0.0
    started: float | None = None
    finished: float | None = None
    error: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.name,
            "name": self.name,
            "input_path": self.input_path,
            "job_id": self.job_id,
            "reprocess": self.reprocess,
            "resume": self.resume,
            "status": self.status,
            "lane": self.lane,
            "stage": self.stage,
            "stage_number": self.stage_number,
            "stage_total": self.stage_total,
            "stage_label": self.stage_label,
            "stage_started": self.stage_started,
            "queued_at": self.queued_at,
            "started": self.started,
            "finished": self.finished,
            "error": self.error,
            "stats": self.stats,
            "timings": self.timings,
        }


@dataclass
class PipelineJob:
    """One submission (a file or a folder) tracked as a group of files."""

    id: int
    input_path: str
    command: list[str]
    reprocess: bool = False
    status: str = "running"
    returncode: int | None = None
    started: float = 0.0
    finished: float | None = None
    log: list[str] | None = None
    stage_number: int = 0
    stage_total: int = FILE_STAGE_TOTAL
    stage_name: str = ""
    stage_started: float = 0.0
    batch_inputs: list[str] | None = None
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "input_path": self.input_path,
            "batch_inputs": self.batch_inputs,
            "command": self.command,
            "reprocess": self.reprocess,
            "status": self.status,
            "returncode": self.returncode,
            "started": self.started,
            "finished": self.finished,
            "log": self.log or [],
            "files": list(self.files),
            "progress": {
                "stage_number": self.stage_number,
                "stage_total": self.stage_total,
                "stage_name": self.stage_name,
                "stage_started": self.stage_started,
            },
        }


class PipelineRunner:
    """Start the resident audio worker and track each recording's progress."""

    def __init__(
        self,
        store: EditorStore,
        *,
        llm_base_url: str = DEFAULT_LLM_BASE_URL,
        llm_model: str = DEFAULT_LLM_MODEL,
        worker_idle_sec: float = 0.0,
        llm_concurrency: int = 2,
    ):
        self.store = store
        self.llm_base_url = llm_base_url.rstrip("/")
        self.llm_model = llm_model
        self.worker_idle_sec = float(worker_idle_sec or 0.0)
        self.llm_concurrency = max(1, int(llm_concurrency or 1))
        self.lock = threading.Lock()
        self.next_job_id = 1
        self.jobs: dict[int, PipelineJob] = {}
        self.files: dict[str, PipelineFile] = {}
        self.file_order: list[str] = []
        self.current_job: PipelineJob | None = None
        self.last_finished_job: PipelineJob | None = None
        self.log: list[dict[str, Any]] = []
        self.worker: subprocess.Popen | None = None
        self.worker_info: dict[str, Any] = {}
        self.worker_started: float | None = None
        self.worker_last_exit: dict[str, Any] | None = None
        self._worker_lock = threading.Lock()
        self._stdin_lock = threading.Lock()

    # ------------------------------------------------------------ status
    @property
    def queue(self) -> list[PipelineFile]:
        return [self.files[name] for name in self.file_order if self.files[name].status == "queued"]

    def current_job_dict(self) -> dict[str, Any] | None:
        with self.lock:
            return self.current_job.to_dict() if self.current_job is not None else None

    def queue_dict(self) -> list[dict[str, Any]]:
        with self.lock:
            return self._queue_dicts_locked()

    def _queue_dicts_locked(self) -> list[dict[str, Any]]:
        return [f.to_dict() for f in self.queue]

    def _worker_dict_locked(self) -> dict[str, Any]:
        alive = self.worker is not None and self.worker.poll() is None
        active = [f for f in self.files.values() if f.active]
        return {
            "alive": alive,
            "pid": self.worker.pid if alive and self.worker else None,
            "started": self.worker_started if alive else None,
            "models": list(self.worker_info.get("models") or []) if alive else [],
            "device": self.worker_info.get("device"),
            "llm_concurrency": self.llm_concurrency,
            "idle_sec": self.worker_idle_sec,
            "audio_lane": next((f.name for f in active if f.lane == "audio" and f.status == "running"), None),
            "llm_lane": sorted(f.name for f in active if f.lane == "llm" and f.status == "running"),
            "active_files": len(active),
            "last_exit": self.worker_last_exit,
        }

    def active_names(self) -> set[str]:
        with self.lock:
            return {name for name, entry in self.files.items() if entry.active}

    def status_dict(self) -> dict[str, Any]:
        with self.lock:
            files = [self.files[name].to_dict() for name in self.file_order[-FILE_HISTORY_LIMIT:]]
            return {
                "job": self.current_job.to_dict() if self.current_job is not None else None,
                "jobs": [job.to_dict() for job in self.jobs.values() if job.status == "running"],
                "queue": self._queue_dicts_locked(),
                "files": files,
                "last_finished": self.last_finished_job.to_dict() if self.last_finished_job is not None else None,
                "worker": self._worker_dict_locked(),
                "log": self.log[-300:],
            }

    # ------------------------------------------------------------ submit
    def worker_command(self) -> list[str]:
        return [
            resolve_pipeline_python(),
            "-u",
            str(WORKER_SCRIPT),
            "--intermediate-root",
            str(self.store.intermediate_root),
            "--output-root",
            str(self.store.output_root),
            "--debug-json",
            "--keep-intermediate",
            "--llm-base-url",
            self.llm_base_url,
            "--llm-model",
            self.llm_model,
            "--llm-concurrency",
            str(self.llm_concurrency),
            "--idle-sec",
            str(self.worker_idle_sec),
        ]

    def _awaiting_resume(self, input_path: Path) -> bool:
        state_payload = self.store.load_pipeline_state(self.store.paths_for(input_path.stem))
        return state_payload.get("state") == "awaiting_resume"

    def _expand_input(self, input_path: Path) -> list[Path]:
        if input_path.is_dir():
            return sorted(
                p for p in input_path.iterdir()
                if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith(".")
            )
        return [input_path]

    def _create_job_locked(self, input_path: Path, entries: list[tuple[Path, bool]]) -> PipelineJob:
        removed_total = 0
        for file_path, reprocess in entries:
            if reprocess:
                cleanup_removed = self.store.prepare_reprocess_input(file_path)
                removed_total += sum(int(value or 0) for value in cleanup_removed.values())
        job = PipelineJob(
            id=self.next_job_id,
            input_path=str(input_path),
            command=self.worker_command(),
            reprocess=any(reprocess for _, reprocess in entries),
            started=time.time(),
            log=[],
            batch_inputs=[str(p) for p, _ in entries] if len(entries) > 1 else None,
        )
        self.next_job_id += 1
        if removed_total:
            job.log.append(f"Preparing clean reprocess; removed {removed_total} prior artifact folder(s).")
        now = time.time()
        nothing_active = not any(f.active for f in self.files.values())
        for file_path, reprocess in entries:
            resume = not reprocess and file_path.is_file() and self._awaiting_resume(file_path)
            entry = PipelineFile(
                name=file_path.stem,
                input_path=str(file_path),
                job_id=job.id,
                reprocess=reprocess,
                resume=resume,
                queued_at=now,
            )
            if nothing_active:
                # The worker picks the first file up immediately; showing it as
                # queued for a poll or two only makes the UI flicker.
                entry.status = "running"
                entry.stage_label = "Starting"
                entry.started = now
                nothing_active = False
            if entry.name in self.files:
                self.file_order.remove(entry.name)
            self.files[entry.name] = entry
            self.file_order.append(entry.name)
            job.files.append(entry.name)
        self.jobs[job.id] = job
        if self.current_job is None or self.current_job.status != "running":
            self.current_job = job
        names = ", ".join(job.files)
        job.log.append(
            f"Submitted {len(job.files)} recording(s) to the resident worker ({names}); "
            "models stay loaded between files."
        )
        return job

    def _start_job_thread(self, job: PipelineJob) -> None:
        thread = threading.Thread(target=self._launch_job, args=(job,), daemon=True)
        thread.start()

    def start(self, relative_input_path: str | None, reprocess: bool = False) -> PipelineJob:
        result = self.submit(relative_input_path, reprocess=reprocess)
        job_id = int(result["job"]["id"])
        with self.lock:
            return self.jobs[job_id]

    def submit(self, relative_input_path: str | None, reprocess: bool = False) -> dict[str, Any]:
        input_path = self.store.resolve_pipeline_input(relative_input_path)
        candidates = self._expand_input(input_path)
        if not candidates:
            raise FileNotFoundError(f"No audio files found under {input_path}.")
        with self.lock:
            entries: list[tuple[Path, bool]] = []
            already_running = already_queued = None
            for candidate in candidates:
                existing = self.files.get(candidate.stem)
                if existing is not None and existing.active:
                    if existing.status == "running":
                        already_running = existing
                    else:
                        already_queued = existing
                    continue
                entries.append((candidate, reprocess))
            if not entries:
                blocker = already_running or already_queued
                return {
                    "job": self.current_job.to_dict() if self.current_job else None,
                    "queue": self._queue_dicts_locked(),
                    "queued": blocker.to_dict() if blocker is not None else None,
                    "already_running": already_running is not None,
                    "already_queued": already_running is None and already_queued is not None,
                    "files": [f.to_dict() for f in self.files.values()],
                }
            job = self._create_job_locked(input_path, entries)
            queued_files = [self.files[name] for name in job.files if self.files[name].status == "queued"]
            payload = {
                "job": job.to_dict(),
                "queue": self._queue_dicts_locked(),
                "queued": queued_files[0].to_dict() if queued_files and len(job.files) == 1 else None,
                "files": [f.to_dict() for f in self.files.values()],
            }
        self._start_job_thread(job)
        return payload

    # ----------------------------------------------------------- logging
    def _append_log(self, job: PipelineJob | None, line: str, file_name: str = "") -> None:
        with self.lock:
            clean_line = line.rstrip()
            if job is not None:
                if job.log is None:
                    job.log = []
                job.log.append(clean_line)
                if len(job.log) > 400:
                    job.log = job.log[-400:]
                step_match = re.match(r"^Step\s+(\d+)\/(\d+):\s*(.+)$", clean_line, flags=re.IGNORECASE)
                if step_match:
                    job.stage_number = int(step_match.group(1))
                    job.stage_total = int(step_match.group(2))
                    job.stage_name = clean_text(step_match.group(3)).removesuffix("...")
                    job.stage_started = time.time()
                elif re.search(r"pipeline complete", clean_line, flags=re.IGNORECASE):
                    job.stage_number = max(job.stage_number, job.stage_total)
                    job.stage_name = "Pipeline complete"
            self.log.append({"t": time.time(), "file": file_name, "line": clean_line})
            if len(self.log) > RUNNER_LOG_LIMIT:
                self.log = self.log[-RUNNER_LOG_LIMIT:]

    def _finish_job(self, job: PipelineJob, status: str, returncode: int | None) -> None:
        with self.lock:
            job.status = status
            job.returncode = returncode
            job.finished = time.time()
            self.last_finished_job = job
            if status == "succeeded":
                job.stage_number = job.stage_total
                job.stage_name = "Pipeline complete"
            running = [j for j in self.jobs.values() if j.status == "running"]
            self.current_job = running[0] if running else job

    def _fail_job_files(self, job: PipelineJob, error: str) -> None:
        with self.lock:
            for name in job.files:
                entry = self.files.get(name)
                if entry is not None and entry.active:
                    entry.status = "failed"
                    entry.error = error
                    entry.finished = time.time()
        self._finish_job(job, "failed", None)

    def _ensure_llm_ready(self, job: PipelineJob) -> bool:
        """Check the configured endpoint before starting audio processing."""
        self._append_log(job, "Checking LLM endpoint")
        try:
            validate_llm_config(base_url=self.llm_base_url, model=self.llm_model)
            wait_for_llm(base_url=self.llm_base_url, api_key=LLM_API_KEY_DEFAULT)
        except LLMUnavailableError as exc:
            self._append_log(job, str(exc))
            self._fail_job_files(job, str(exc))
            return False
        return True

    # ------------------------------------------------------------ worker
    def _launch_job(self, job: PipelineJob) -> None:
        try:
            if not self._ensure_llm_ready(job):
                return
            self._ensure_worker(job)
            with self.lock:
                files = [self.files[name] for name in job.files]
                resume = any(f.resume for f in files)
            self._send({"op": "run", "job_id": job.id, "files": [f.input_path for f in files],
                        "resume": resume})
        except Exception as exc:  # noqa: BLE001
            self._append_log(job, f"Failed to start pipeline worker: {exc}")
            self._fail_job_files(job, f"failed to start worker: {exc}")

    def _ensure_worker(self, job: PipelineJob | None = None) -> subprocess.Popen:
        with self._worker_lock:
            if self.worker is not None and self.worker.poll() is None:
                return self.worker
            command = self.worker_command()
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=pipeline_subprocess_env(command[0]),
            )
            with self.lock:
                self.worker = process
                self.worker_started = time.time()
                self.worker_info = {}
            self._append_log(job, f"Started resident pipeline worker (pid {process.pid}); "
                                  "models load once and stay resident.")
            threading.Thread(target=self._read_worker, args=(process,), daemon=True).start()
            return process

    def _send(self, op: dict[str, Any]) -> None:
        process = self.worker
        if process is None or process.stdin is None or process.poll() is not None:
            raise RuntimeError("pipeline worker is not running")
        with self._stdin_lock:
            process.stdin.write(json.dumps(op) + "\n")
            process.stdin.flush()

    def _read_worker(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                if line.startswith(WORKER_EVENT_PREFIX):
                    try:
                        event = json.loads(line[len(WORKER_EVENT_PREFIX):])
                    except json.JSONDecodeError:
                        self._append_log(None, line)
                        continue
                    self.handle_worker_event(event)
                else:
                    self._append_log(self._job_for_line(line), line)
        finally:
            returncode = process.wait()
            self._worker_exited(process, returncode)

    def _job_for_line(self, line: str) -> PipelineJob | None:
        match = re.match(r"^\[([^\]]+)\]", line)
        with self.lock:
            if match and match.group(1) in self.files:
                return self.jobs.get(self.files[match.group(1)].job_id)
            return self.current_job if self.current_job and self.current_job.status == "running" else None

    def handle_worker_event(self, event: dict[str, Any]) -> None:
        kind = event.get("event")
        name = clean_text(event.get("file"))
        with self.lock:
            entry = self.files.get(name) if name else None
            job = self.jobs.get(entry.job_id) if entry else self.jobs.get(int(event.get("job_id") or 0))
        if kind in ("worker_ready", "status"):
            with self.lock:
                self.worker_info.update({k: v for k, v in event.items() if k != "event"})
            if kind == "worker_ready":
                self._append_log(job, f"Worker ready on {event.get('device')} "
                                      f"(LLM lane width {event.get('llm_concurrency')}; torch threads "
                                      f"{event.get('cpu_threads')}/{event.get('cpu_cores')} cores, "
                                      f"nice {event.get('nice')}).")
            return
        if kind == "worker_exit":
            with self.lock:
                self.worker_last_exit = {"reason": event.get("reason"), "at": time.time()}
            return
        if entry is None:
            if kind == "log":
                self._append_log(job, str(event.get("line", "")), name)
            return
        if kind == "stage":
            with self.lock:
                entry.status = "running"
                entry.lane = str(event.get("lane") or entry.lane or "")
                entry.stage = str(event.get("stage") or "")
                entry.stage_number = int(event.get("index") or 0)
                entry.stage_total = int(event.get("total") or FILE_STAGE_TOTAL)
                entry.stage_label = str(event.get("label") or "")
                entry.stage_started = time.time()
                if entry.started is None:
                    entry.started = time.time()
                if job is not None:
                    job.stage_number = entry.stage_number
                    job.stage_total = entry.stage_total
                    job.stage_name = entry.stage_label
                    job.stage_started = entry.stage_started
            self._append_log(job, f"[{name}] Step {entry.stage_number}/{entry.stage_total}: "
                                  f"{entry.stage_label}...", name)
        elif kind == "lane":
            with self.lock:
                if event.get("state") == "start":
                    entry.lane = str(event.get("lane") or "")
        elif kind == "log":
            self._append_log(job, f"[{name}] {event.get('line', '')}", name)
        elif kind == "file_done":
            status = str(event.get("status") or "ok")
            with self.lock:
                entry.status = "succeeded" if status == "ok" else status
                entry.finished = time.time()
                entry.stats = dict(event.get("stats") or {})
                entry.timings = dict(event.get("timings") or {})
                if entry.status == "succeeded":
                    entry.stage_number = entry.stage_total
                    entry.stage_label = "Complete"
            self._append_log(job, f"[{name}] finished ({entry.status}) in "
                                  f"{float(event.get('elapsed_sec') or 0):.0f}s.", name)
            self._after_file_terminal(entry)
        elif kind == "file_failed":
            with self.lock:
                entry.status = "failed"
                entry.finished = time.time()
                entry.error = str(event.get("error") or "pipeline error")
            self._append_log(job, f"[{name}] ERROR: {entry.error}", name)
            if event.get("traceback"):
                for tb_line in str(event["traceback"]).rstrip().splitlines()[-12:]:
                    self._append_log(job, f"[{name}]   {tb_line}", name)
            self._after_file_terminal(entry)

    def _after_file_terminal(self, entry: PipelineFile) -> None:
        with self.lock:
            job = self.jobs.get(entry.job_id)
            statuses = [self.files[n].status for n in job.files] if job else []
            done = job is not None and all(s in TERMINAL_FILE_STATUSES for s in statuses)
        if job is not None and done and job.status == "running":
            status = "succeeded" if all(s == "succeeded" for s in statuses) else "failed"
            self._finish_job(job, status, 0 if status == "succeeded" else 1)

    def _worker_exited(self, process: subprocess.Popen, returncode: int | None) -> None:
        with self.lock:
            if self.worker is process:
                self.worker = None
            self.worker_last_exit = {
                "reason": (self.worker_last_exit or {}).get("reason") or f"exit code {returncode}",
                "at": time.time(),
                "returncode": returncode,
            }
            orphaned = [f for f in self.files.values() if f.active]
            for entry in orphaned:
                entry.status = "failed"
                entry.error = f"pipeline worker exited (code {returncode})"
                entry.finished = time.time()
        if orphaned:
            self._append_log(self.current_job, f"Pipeline worker exited (code {returncode}) with "
                                               f"{len(orphaned)} file(s) unfinished.")
            for entry in orphaned:
                self._after_file_terminal(entry)

    def release_worker(self) -> dict[str, Any]:
        """Stop the resident worker to free GPU memory (refused while files are active)."""
        with self.lock:
            if any(f.active for f in self.files.values()):
                raise ValueError("Cannot release models while recordings are being processed.")
            process = self.worker
        if process is None or process.poll() is not None:
            return {"released": False, "worker": self._worker_dict_locked()}
        try:
            self._send({"op": "shutdown"})
            process.wait(timeout=15)
        except Exception:  # noqa: BLE001
            process.kill()
        self._append_log(None, "Released the resident pipeline worker; models unloaded.")
        return {"released": True, "worker": self.status_dict()["worker"]}


class WebUIRequestHandler(BaseHTTPRequestHandler):
    store = EditorStore()
    runner = PipelineRunner(store)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def is_local_client(self) -> bool:
        return is_loopback_address(str(self.client_address[0]))

    def reject_nonlocal_client(self) -> bool:
        if self.is_local_client():
            return False
        self.send_error_json("Forbidden: this WebUI only accepts localhost connections.", status=403)
        return True

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 400) -> None:
        self.send_json({"error": message}, status=status)

    def handle_client_disconnect(self) -> None:
        return

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        payload = json.loads(raw_body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object.")
        return payload

    def do_GET(self) -> None:
        if self.reject_nonlocal_client():
            return

        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path == "/api/input-files":
                self.send_json(
                    {
                        "input_root": str(self.store.input_root),
                        "files": self.store.list_input_audio_files(),
                    }
                )
                return

            if path == "/api/pipeline/job":
                self.send_json(self.runner.status_dict())
                return

            if path == "/api/sessions":
                self.send_json({"sessions": self.store.list_sessions(), "role_options": list(DEFAULT_SPEAKERS)})
                return

            if path == "/api/sessions/bundle.zip":
                self.send_bundle(parse_qs(parsed.query).get("name", []))
                return

            if path == "/api/sessions/final-transcripts.zip":
                names_param = parse_qs(parsed.query).get("names", [""])[0]
                names = [name for name in names_param.split(",") if clean_text(name)]
                self.send_finished_transcripts_zip(names)
                return

            transcript_match = re.fullmatch(r"/api/session/([^/]+)/final-transcript", path)
            if transcript_match:
                self.send_final_transcript(transcript_match.group(1))
                return

            revisions_match = re.fullmatch(r"/api/session/([^/]+)/revisions", path)
            if revisions_match:
                self.send_json(self.store.load_revisions(revisions_match.group(1)))
                return

            match = re.fullmatch(r"/api/session/([^/]+)", path)
            if match:
                self.send_json(self.store.load_session(match.group(1)))
                return

            audio_match = re.fullmatch(r"/api/session/([^/]+)/audio", path)
            if audio_match:
                self.send_audio(audio_match.group(1))
                return

            self.send_static(path)
        except FileNotFoundError as exc:
            self.send_error_json(str(exc), status=404)
        except ValueError as exc:
            self.send_error_json(str(exc), status=400)
        except ClientDisconnected:
            self.handle_client_disconnect()
        except Exception as exc:
            self.send_error_json(f"Internal server error: {exc}", status=500)

    def do_POST(self) -> None:
        if self.reject_nonlocal_client():
            return

        parsed = urlparse(self.path)
        if parsed.path == "/api/input-files/upload":
            try:
                query = parse_qs(parsed.query)
                filename = clean_text(query.get("filename", [""])[0])
                allow_duplicate = clean_text(query.get("allow_duplicate", [""])[0]).lower() in {"1", "true", "yes"}
                content_length = int(self.headers.get("Content-Length", "0"))
                self.send_json(
                    {
                        "file": self.store.save_input_audio(
                            filename, self.rfile, content_length, allow_duplicate=allow_duplicate
                        )
                    }
                )
            except ValueError as exc:
                self.send_error_json(str(exc), status=400)
            except ClientDisconnected:
                self.handle_client_disconnect()
            except Exception as exc:
                self.send_error_json(f"Internal server error: {exc}", status=500)
            return

        if parsed.path == "/api/bundles/import":
            try:
                query = parse_qs(parsed.query)
                replace = clean_text(query.get("replace", [""])[0]).lower() in {"1", "true", "yes"}
                content_length = int(self.headers.get("Content-Length", "0"))
                result = self.store.import_bundle_upload(
                    self.rfile, content_length, replace=replace, busy=self.runner.active_names()
                )
                self.send_json({"bundle": result})
            except BundleConflictError as exc:
                self.send_json({"error": str(exc), "conflicts": exc.names}, status=409)
            except ValueError as exc:
                self.send_error_json(str(exc), status=400)
            except ClientDisconnected:
                self.handle_client_disconnect()
            except Exception as exc:
                self.send_error_json(f"Internal server error: {exc}", status=500)
            return

        if parsed.path == "/api/cache/clear-selected":
            try:
                payload = self.read_json_body()
                if payload.get("confirm") != "DELETE":
                    raise ValueError("Cache clear requires confirm=DELETE.")
                names = payload.get("names")
                if not isinstance(names, list):
                    raise ValueError("Expected names list.")
                self.send_json(self.store.clear_selected(names))
            except ValueError as exc:
                self.send_error_json(str(exc), status=400)
            except ClientDisconnected:
                self.handle_client_disconnect()
            except Exception as exc:
                self.send_error_json(f"Internal server error: {exc}", status=500)
            return

        if parsed.path == "/api/pipeline/worker/release":
            try:
                self.send_json(self.runner.release_worker())
            except ValueError as exc:
                self.send_error_json(str(exc), status=409)
            except ClientDisconnected:
                self.handle_client_disconnect()
            except Exception as exc:
                self.send_error_json(f"Internal server error: {exc}", status=500)
            return

        if parsed.path == "/api/pipeline/run":
            try:
                payload = self.read_json_body()
                self.send_json(self.runner.submit(payload.get("input_path"), reprocess=bool(payload.get("reprocess"))))
            except FileNotFoundError as exc:
                self.send_error_json(str(exc), status=404)
            except (RuntimeError, ValueError) as exc:
                self.send_error_json(str(exc), status=400)
            except ClientDisconnected:
                self.handle_client_disconnect()
            except Exception as exc:
                self.send_error_json(f"Internal server error: {exc}", status=500)
            return

        match = re.fullmatch(r"/api/session/([^/]+)/save", parsed.path)
        if not match:
            self.send_error_json("Unknown endpoint.", status=404)
            return

        try:
            payload = self.read_json_body()
            self.send_json(self.store.save_session(match.group(1), payload))
        except ValueError as exc:
            self.send_error_json(str(exc), status=400)
        except ClientDisconnected:
            self.handle_client_disconnect()
        except Exception as exc:
            self.send_error_json(f"Internal server error: {exc}", status=500)

    def send_static(self, request_path: str) -> None:
        relative_path = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        target = (STATIC_ROOT / relative_path).resolve()
        if not target.is_relative_to(STATIC_ROOT.resolve()) or not target.exists() or not target.is_file():
            self.send_error_json("Not found.", status=404)
            return
        self.send_file(target, cache_control="no-store")

    def send_audio(self, name: str) -> None:
        audio_path = self.store.find_audio_path(name)
        if audio_path is None:
            raise FileNotFoundError("Audio file was not found for this session.")
        self.send_file(audio_path)

    def send_final_transcript(self, name: str) -> None:
        filename, text = self.store.final_transcript_for_session(name)
        body = text.encode("utf-8")
        safe_filename = filename.replace('"', "_")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{safe_filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ClientDisconnected() from exc

    def send_bundle(self, names: list[str]) -> None:
        busy = sorted({clean_text(name) for name in names} & self.runner.active_names())
        if busy:
            raise ValueError(f"Wait for processing to finish: {', '.join(busy)}.")
        path = self.store.export_bundle_file(names)
        try:
            unique = list(dict.fromkeys(names))
            filename = f"{unique[0]}_bundle.zip" if len(unique) == 1 else "mediscribe_bundle.zip"
            self.send_file(path, download_name=filename)
        finally:
            path.unlink(missing_ok=True)

    def send_finished_transcripts_zip(self, names: list[str] | None = None) -> None:
        filename, body, count = self.store.finished_final_transcripts_zip(names)
        safe_filename = filename.replace('"', "_")
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{safe_filename}"')
        self.send_header("X-Transcript-Count", str(count))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ClientDisconnected() from exc

    def send_file(self, path: Path, *, cache_control: str | None = None, download_name: str | None = None) -> None:
        file_size = path.stat().st_size
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        range_header = self.headers.get("Range")

        start = 0
        end = file_size - 1
        status = 200
        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if match:
                if match.group(1):
                    start = int(match.group(1))
                if match.group(2):
                    end = int(match.group(2))
                end = min(end, file_size - 1)
                status = 206

        if start > end or start >= file_size:
            try:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise ClientDisconnected() from exc
            return

        length = end - start + 1
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if cache_control:
                self.send_header("Cache-Control", cache_control)
            if download_name:
                fallback = download_name.encode("ascii", "replace").decode("ascii").replace('"', "_").replace("?", "_")
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(download_name, safe='')}",
                )
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ClientDisconnected() from exc

        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError) as exc:
                    raise ClientDisconnected() from exc
                remaining -= len(chunk)


def build_handler(
    project_root: Path,
    *,
    llm_base_url: str = DEFAULT_LLM_BASE_URL,
    llm_model: str = DEFAULT_LLM_MODEL,
    worker_idle_sec: float = 0.0,
    llm_concurrency: int = 2,
) -> type[WebUIRequestHandler]:
    store = EditorStore(project_root)

    class ConfiguredHandler(WebUIRequestHandler):
        pass

    ConfiguredHandler.store = store
    ConfiguredHandler.runner = PipelineRunner(
        store,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        worker_idle_sec=worker_idle_sec,
        llm_concurrency=llm_concurrency,
    )

    return ConfiguredHandler


def create_http_server(
    host: str,
    port: int,
    handler_cls: type[BaseHTTPRequestHandler],
    *,
    allow_port_fallback: bool,
) -> ThreadingHTTPServer:
    try:
        return ThreadingHTTPServer((host, port), handler_cls)
    except OSError as exc:
        if not allow_port_fallback or port == 0 or exc.errno != errno.EADDRINUSE:
            raise

    server = ThreadingHTTPServer((host, 0), handler_cls)
    selected_port = int(server.server_address[1])
    print(f"Port {port} is already in use; selected available port {selected_port}.")
    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Mediscribe transcript editor.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=7860, help="Preferred port to bind.")
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail when --port is unavailable instead of selecting a free port.",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT, help="Mediscribe project root.")
    parser.add_argument(
        "--conda-env",
        default=PIPELINE_CONDA_ENV,
        help="Conda env whose python runs the offline pipeline (default: scribe). "
        "PYTHON_BIN overrides this entirely.",
    )
    parser.add_argument(
        "--llm-base-url",
        default=os.environ.get("MEDISCRIBE_LLM_BASE_URL", ""),
        help="API base URL (default: $MEDISCRIBE_LLM_BASE_URL).",
    )
    parser.add_argument(
        "--llm-model",
        default=os.environ.get("MEDISCRIBE_LLM_MODEL", ""),
        help="Endpoint model name (default: $MEDISCRIBE_LLM_MODEL).",
    )
    parser.add_argument(
        "--worker-idle-sec",
        type=float,
        default=float(os.environ.get("MEDISCRIBE_WORKER_IDLE_SEC", "0")),
        help="Stop the resident pipeline worker (unloading Whisper/pyannote/Parakeet) after this "
        "many idle seconds. 0 keeps the models resident for the life of the WebUI.",
    )
    parser.add_argument(
        "--llm-concurrency",
        type=int,
        default=int(os.environ.get("MEDISCRIBE_LLM_CONCURRENCY", "2")),
        help="Concurrent recordings in the LLM stage.",
    )
    return parser.parse_args()


def main() -> None:
    global PIPELINE_CONDA_ENV
    args = parse_args()
    PIPELINE_CONDA_ENV = args.conda_env
    if not is_loopback_address(args.host):
        raise SystemExit("Refusing to bind WebUI outside localhost. Use 127.0.0.1 or localhost.")

    handler_cls = build_handler(
        args.project_root,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        worker_idle_sec=args.worker_idle_sec,
        llm_concurrency=args.llm_concurrency,
    )

    server = create_http_server(
        args.host,
        args.port,
        handler_cls,
        allow_port_fallback=not args.strict_port,
    )
    selected_port = int(server.server_address[1])
    print(f"Mediscribe WebUI running at http://{args.host}:{selected_port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMediscribe WebUI stopped.")
    finally:
        server.server_close()
        worker = handler_cls.runner.worker
        if worker is not None and worker.poll() is None:
            worker.terminate()


if __name__ == "__main__":
    main()
