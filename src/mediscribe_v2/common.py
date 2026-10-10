"""Shared constants, LLM client, text helpers, and artifact writers.

The role vocabulary, final-transcript line format, and canonical/state file
semantics are shared with the WebUI editor and the launch scripts; change them
together.
"""
from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

# ---------------------------------------------------------------- LLM client
LLM_BASE_URL_DEFAULT = os.environ.get("MEDISCRIBE_LLM_BASE_URL", "")
LLM_MODEL_DEFAULT = os.environ.get("MEDISCRIBE_LLM_MODEL", "")
LLM_API_KEY_DEFAULT = os.environ.get("MEDISCRIBE_LLM_API_KEY", "")
LLM_MAX_OUTPUT_TOKENS = 2048
LLM_RETRY_ATTEMPTS = 10
LLM_RETRY_WINDOW_SEC = 60.0
LLM_HEALTHCHECK_TIMEOUT_SEC = 2.0
# Retry transient connection failures and server errors with exponential backoff.
LLM_GENERATION_ATTEMPTS = 4
LLM_GENERATION_BACKOFF_SEC = 3.0

# ------------------------------------------------------------------- roles
@dataclass(frozen=True)
class RoleConfig:
    roles: dict[str, str]
    instructions: str
    required_roles: tuple[str, ...]
    ordered_roles: tuple[str, ...]
    aliases: dict[str, str]

    @property
    def options(self) -> tuple[str, ...]:
        return (*self.roles, "Unknown")


def load_role_config(path: Path) -> RoleConfig:
    """Load a shared role vocabulary and its assignment rules."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Role configuration must be a JSON object.")
    entries = payload.get("roles")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Role configuration needs a nonempty roles list.")
    if "aliases" in payload:
        raise ValueError("Put aliases inside each role entry.")
    roles = {}
    labels = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each role needs a name, aliases, and description.")
        label, description = entry.get("name"), entry.get("description")
        if (not isinstance(label, str) or not label
                or label != re.sub(r"\s+", " ", label).strip() or ":" in label
                or any(ord(char) < 32 for char in label)
                or label.casefold() == "unknown" or label.casefold() in labels
                or re.fullmatch(r"speaker[\s_-]*\d+", label, re.IGNORECASE)):
            raise ValueError(f"Invalid or duplicate role label: {label!r}")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Role {label!r} needs a description.")
        roles[label] = description
        labels.add(label.casefold())
    groups = {}
    for name in ("required_roles", "ordered_roles"):
        group = payload.get(name, [])
        if (not isinstance(group, list) or any(not isinstance(role, str) or role not in roles for role in group)
                or len(group) != len(set(group))):
            raise ValueError(f"{name} must list distinct labels from roles.")
        groups[name] = tuple(group)
    instructions = payload.get("instructions", "")
    if not isinstance(instructions, str):
        raise ValueError("Role instructions must be text.")
    aliases = {label.casefold(): label for label in (*roles, "Unknown")}
    for entry in entries:
        label = entry["name"]
        configured_aliases = entry.get("aliases", [])
        if not isinstance(configured_aliases, list):
            raise ValueError(f"Aliases for {label!r} must be a list.")
        for alias in configured_aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError(f"Invalid alias for {label!r}: {alias!r}")
            key = re.sub(r"\s+", " ", alias.strip().casefold())
            if key in aliases and aliases[key] != label:
                raise ValueError(f"Alias {alias!r} belongs to more than one role.")
            aliases[key] = label
    return RoleConfig(roles, instructions, groups["required_roles"], groups["ordered_roles"], aliases)


ROLE_CONFIG_PATH = Path(os.environ.get("MEDISCRIBE_ROLES_CONFIG")
                        or Path(__file__).resolve().parents[2] / "config" / "roles" / "clinical.json").expanduser()
ROLE_CONFIG = load_role_config(ROLE_CONFIG_PATH)
ROLE_OPTIONS = ROLE_CONFIG.options


class LLMUnavailableError(RuntimeError):
    """Raised when an LLM request fails after bounded retries."""


class LLMContextLengthError(LLMUnavailableError):
    """Raised when the serving model rejects a prompt for exceeding its context window."""


class LLMBadReplyError(LLMUnavailableError):
    """Raised when the model answered every attempt but never with a usable reply."""


def _urlopen(request: urllib.request.Request, *, timeout: float):
    """Respect proxy settings for remote endpoints; connect directly to loopback."""
    host = urlparse(request.full_url).hostname
    handlers = [urllib.request.ProxyHandler({})] if host in {"localhost", "127.0.0.1", "::1"} else []
    opener = urllib.request.build_opener(*handlers)
    return opener.open(request, timeout=timeout)


def validate_llm_config(*, base_url: str, model: str) -> None:
    try:
        url = urlparse(base_url)
        valid = (url.scheme in {"http", "https"} and url.hostname and not url.query
                 and not url.fragment and url.username is None and url.password is None)
        url.port  # Reject malformed or out-of-range ports.
    except ValueError:
        valid = False
    if not valid:
        raise LLMUnavailableError("Set MEDISCRIBE_LLM_BASE_URL to an HTTP or HTTPS API base URL.")
    if not model.strip():
        raise LLMUnavailableError("Set MEDISCRIBE_LLM_MODEL to a model name accepted by the endpoint.")


def wait_for_llm(*, base_url: str, api_key: str = LLM_API_KEY_DEFAULT) -> None:
    last_error: Exception | None = None
    deadline = time.monotonic() + LLM_RETRY_WINDOW_SEC
    for attempt in range(1, LLM_RETRY_ATTEMPTS + 1):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        request = urllib.request.Request(f"{base_url.rstrip('/')}/models", headers=headers, method="GET")
        try:
            health_timeout = min(LLM_HEALTHCHECK_TIMEOUT_SEC, max(0.25, deadline - time.monotonic()))
            with _urlopen(request, timeout=health_timeout):
                return
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise LLMUnavailableError(f"LLM endpoint check failed: HTTP {exc.code}.") from exc
            last_error = exc
        except (urllib.error.URLError, OSError, socket.timeout) as exc:
            last_error = exc
        print(f"LLM endpoint check failed ({attempt}/{LLM_RETRY_ATTEMPTS}): {last_error}", flush=True)
        if attempt >= LLM_RETRY_ATTEMPTS or time.monotonic() >= deadline:
            break
        sleep_for = max(0.0, (deadline - time.monotonic()) / (LLM_RETRY_ATTEMPTS - attempt))
        if sleep_for:
            time.sleep(min(2.0, sleep_for))
    raise LLMUnavailableError(
        f"LLM endpoint check did not respond after {LLM_RETRY_ATTEMPTS} attempts in "
        f"{LLM_RETRY_WINDOW_SEC:.0f} seconds: {last_error}"
    )


def call_llm(
    prompt: str,
    *,
    base_url: str,
    model: str,
    timeout_sec: float,
    system: str | None = None,
    temperature: float = 0.2,
    top_p: float | None = None,
    max_tokens: int = LLM_MAX_OUTPUT_TOKENS,
    api_key: str = LLM_API_KEY_DEFAULT,
) -> str:
    """Call an OpenAI-compatible chat endpoint and return its answer text.

    Retry transient failures up to ``LLM_GENERATION_ATTEMPTS`` times.
    Authentication, request, and context-length errors propagate immediately.
    """
    validate_llm_config(base_url=base_url, model=model)
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if top_p is not None:
        payload["top_p"] = top_p
    last_error: LLMUnavailableError | None = None
    delay = LLM_GENERATION_BACKOFF_SEC
    for attempt in range(1, LLM_GENERATION_ATTEMPTS + 1):
        wait_for_llm(base_url=base_url, api_key=api_key)
        try:
            return _generate_once(payload, base_url=base_url, api_key=api_key, timeout_sec=timeout_sec)
        except LLMContextLengthError:
            raise
        except LLMUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code < 500 and cause.code != 429:
                raise
            last_error = exc
            if attempt >= LLM_GENERATION_ATTEMPTS:
                break
            print(f"LLM request failed ({attempt}/{LLM_GENERATION_ATTEMPTS}); "
                  f"retrying in {delay:.0f}s: {exc}", flush=True)
            time.sleep(delay)
            delay *= 2
    assert last_error is not None
    raise last_error


def _generate_once(payload: dict[str, object], *, base_url: str, api_key: str,
                   timeout_sec: float) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with _urlopen(request, timeout=float(timeout_sec)) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
        except (OSError, ValueError):
            detail = ""
        if exc.code == 400 and "maximum context length" in detail:
            raise LLMContextLengthError(
                f"Prompt exceeds the serving model's context window: {detail}"
            ) from exc
        raise LLMUnavailableError(f"LLM request failed: {exc}: {detail}") from exc
    except (urllib.error.URLError, json.JSONDecodeError, OSError, socket.timeout) as exc:
        raise LLMUnavailableError(f"LLM request failed: {exc}") from exc
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    return str(content).strip()


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Pull the first parseable JSON object out of an LLM reply.

    The outermost brace span is tried first (the usual "JSON only" answer).
    When prose with stray braces surrounds the answer, every opening brace is
    tried as a start position instead of giving up.
    """
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None


def normalize_role(value: object, role_config: RoleConfig = ROLE_CONFIG) -> str | None:
    if not isinstance(value, str):
        return None
    key = re.sub(r"\s+", " ", value.strip().casefold())
    return role_config.aliases.get(key)


# ------------------------------------------------------------- text helpers
def join_text_pieces(pieces: Iterable[str]) -> str:
    merged = ""
    for piece in pieces:
        raw_piece = str(piece)
        if not raw_piece:
            continue
        if not merged:
            merged = raw_piece.lstrip()
            continue
        if raw_piece.startswith((" ", "\n")) or raw_piece[0] in ".,!?;:%)]}":
            merged += raw_piece
        else:
            merged += " " + raw_piece.lstrip()
    return re.sub(r"\s+", " ", merged).strip()


def turn_word_count_from_text(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def normalize_token(text: str) -> str:
    """Lowercased, punctuation-stripped form used for cross-engine matching."""
    return re.sub(r"[^a-z0-9']", "", text.lower())


def load_token_lexicon(path: Path) -> frozenset[str]:
    """Read a JSON word list using the same normalization as transcript tokens."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or any(not isinstance(term, str) or not normalize_token(term) for term in entries):
        raise ValueError(f"Lexicon must be a JSON list of words: {path.name}")
    return frozenset(normalize_token(term) for term in entries)


def format_minsec_label(ms: int) -> str:
    minutes, seconds = divmod(ms // 1000, 60)
    return f"{minutes}min {seconds}s"


# --------------------------------------------------------------- artifacts
def write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically: a reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_canonical_transcript(path: Path, payload: dict[str, Any]) -> Path:
    write_json(path, payload)
    return path


def write_pipeline_state(
    path: Path, *, state: str, reason: str, message: str, resumable_step: str | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "reason": reason,
        "message": message,
        "resumable_step": resumable_step,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ------------------------------------------------------------ CPU budget
def configure_cpu(*, reserve_cores: int | None = None, nice_increment: int | None = None) -> dict:
    """Set audio-worker CPU threads and scheduling priority.

    MEDISCRIBE_CPU_THREADS sets an explicit thread count. Otherwise
    MEDISCRIBE_CPU_RESERVE leaves cores available for other processes.
    MEDISCRIBE_CPU_NICE controls the scheduling priority increment.
    """
    cores = os.cpu_count() or 4
    if reserve_cores is None:
        reserve_cores = int(os.environ.get("MEDISCRIBE_CPU_RESERVE", "4"))
    threads = int(os.environ.get("MEDISCRIBE_CPU_THREADS", str(max(2, cores - reserve_cores))))
    if nice_increment is None:
        nice_increment = int(os.environ.get("MEDISCRIBE_CPU_NICE", "10"))
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, str(threads))
    applied: dict = {"cpu_cores": cores, "cpu_threads": threads, "nice": None}
    try:
        import torch

        torch.set_num_threads(threads)
    except Exception:  # noqa: BLE001 — torch is optional at import time
        pass
    if nice_increment > 0:
        try:
            applied["nice"] = os.nice(nice_increment)
        except OSError:
            pass
    return applied
