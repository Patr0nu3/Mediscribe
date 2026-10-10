"""Resident pipeline worker: JSON lines in on stdin, events out on stdout.

The WebUI starts one worker in the scribe environment and keeps it alive
across jobs, so Whisper, the MMS aligner, pyannote, and Parakeet load once
and stay on the GPU/CPU. Files are handed to ``scheduler.PipelineService``
which overlaps the audio and LLM lanes.

Protocol (one JSON object per line):
  in : {"op": "run", "job_id": 7, "files": ["/abs/a.wav", ...], "resume": true|false|null}
       {"op": "shutdown"}
  out: lines starting with ``@@EVENT `` carry a JSON event (worker_ready,
       accepted, file_queued, stage, log, lane, file_done, file_failed,
       status, worker_exit); any other stdout line is plain pipeline chatter.
       A ``status`` event (resident models, queue snapshot) follows every lane
       end, which is when a model may just have been loaded.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import asr, diarize, pipeline
from .common import configure_cpu
from .scheduler import PipelineService

EVENT_PREFIX = "@@EVENT "
_OUT_LOCK = threading.Lock()


def emit_jsonl(event: dict[str, Any]) -> None:
    line = EVENT_PREFIX + json.dumps(event, default=str)
    with _OUT_LOCK:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def models_resident() -> list[str]:
    names = []
    for key in asr._CACHE:
        names.append({"parakeet": "parakeet", "silero": "silero-vad", "mms_fa": "mms-aligner"}.get(
            key, key.split(":")[0] if ":" in key else key))
    if "diar" in diarize._CACHE:
        names.append("pyannote")
    return names


def main(argv: list[str] | None = None) -> None:
    parser = pipeline.build_parser(require_input=False)
    parser.add_argument("--idle-sec", type=float, default=0.0,
                        help="Exit (releasing the models) after this many idle seconds; 0 = stay.")
    args = pipeline.finalize_args(parser.parse_args(argv))
    cpu = configure_cpu()
    device = pipeline.resolve_device(args)

    def status_event() -> dict[str, Any]:
        return {"event": "status", "pid": os.getpid(), "models": models_resident(), **service.snapshot()}

    def emit(event: dict[str, Any]) -> None:
        emit_jsonl(event)
        if event.get("event") == "lane" and event.get("state") == "end":
            emit_jsonl(status_event())

    service = PipelineService(args, device, emit)
    emit_jsonl({"event": "worker_ready", "pid": os.getpid(), "device": device,
                "llm_concurrency": service.llm_concurrency, "idle_sec": args.idle_sec, **cpu})
    stop = threading.Event()

    def watchdog() -> None:
        while not stop.wait(5.0):
            if args.idle_sec > 0 and service.idle and \
                    time.monotonic() - service.last_activity >= args.idle_sec:
                emit_jsonl({"event": "worker_exit", "reason": "idle_timeout",
                            "idle_sec": args.idle_sec})
                sys.stdout.flush()
                os._exit(0)

    threading.Thread(target=watchdog, name="idle-watchdog", daemon=True).start()
    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                op = json.loads(raw)
            except json.JSONDecodeError:
                emit_jsonl({"event": "error", "error": f"bad request line: {raw[:200]}"})
                continue
            kind = op.get("op")
            if kind == "run":
                job_id = op.get("job_id")
                for entry in op.get("files") or []:
                    try:
                        service.submit(Path(entry), job_id=job_id, resume=op.get("resume"))
                    except Exception as exc:  # noqa: BLE001
                        emit_jsonl({"event": "file_failed", "file": Path(entry).stem, "job_id": job_id,
                                    "error": f"{type(exc).__name__}: {exc}"})
                emit_jsonl({"event": "accepted", "job_id": job_id, "files": [Path(e).stem for e in op.get("files") or []]})
            elif kind == "shutdown":
                break
            else:
                emit_jsonl({"event": "error", "error": f"unknown op: {kind}"})
    finally:
        stop.set()
        emit_jsonl({"event": "worker_exit", "reason": "shutdown", **service.snapshot()})
        service.stop(wait=False)


if __name__ == "__main__":
    main()
