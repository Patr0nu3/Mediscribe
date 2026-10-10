"""Queue recordings through serial audio stages and concurrent LLM stages.
Audio models remain loaded across jobs. Submit recordings with ``submit``,
wait for a batch with ``wait_all``, and drain the queue with ``stop``.
"""
from __future__ import annotations

import argparse
import queue
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import pipeline
from .common import write_pipeline_state


@dataclass
class FileJob:
    input_audio: Path
    job_id: Any = None
    resume: bool | None = None
    submitted: float = field(default_factory=time.monotonic)

    @property
    def name(self) -> str:
        return self.input_audio.stem


class PipelineService:
    def __init__(self, args: argparse.Namespace, device: str,
                 emit: pipeline.Emitter = pipeline.default_emit, *,
                 llm_concurrency: int | None = None) -> None:
        self.args = args
        self.device = device
        self.emit = emit
        self.llm_concurrency = max(1, int(llm_concurrency or getattr(args, "llm_concurrency", 1) or 1))
        self._queue: "queue.Queue[FileJob | None]" = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=self.llm_concurrency, thread_name_prefix="llm-lane")
        self._lock = threading.Lock()
        self._futures: dict[str, Future] = {}
        self._results: dict[str, str] = {}
        self._active: set[str] = set()
        self._queued: list[str] = []
        self._audio_current: str | None = None
        self._llm_current: set[str] = set()
        self._all_done = threading.Condition(self._lock)
        self.last_activity = time.monotonic()
        self._stopped = False
        self._audio_thread = threading.Thread(target=self._audio_loop, name="audio-lane", daemon=True)
        self._audio_thread.start()

    # ------------------------------------------------------------ control
    def submit(self, input_audio: Path, *, job_id: Any = None, resume: bool | None = None) -> str:
        job = FileJob(Path(input_audio), job_id=job_id, resume=resume)
        with self._lock:
            if self._stopped:
                raise RuntimeError("pipeline service is stopped")
            self._active.add(job.name)
            self._queued.append(job.name)
            self.last_activity = time.monotonic()
        self._queue.put(job)
        self.emit({"event": "file_queued", "file": job.name, "job_id": job_id})
        return job.name

    def wait_all(self, timeout: float | None = None) -> dict[str, str]:
        with self._all_done:
            self._all_done.wait_for(lambda: not self._active, timeout=timeout)
            return dict(self._results)

    def stop(self, wait: bool = True) -> None:
        with self._lock:
            self._stopped = True
        self._queue.put(None)
        if wait:
            self._audio_thread.join()
        self._pool.shutdown(wait=wait)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"active": sorted(self._active), "queued": list(self._queued),
                    "audio": self._audio_current, "llm": sorted(self._llm_current),
                    "results": dict(self._results), "idle_sec": time.monotonic() - self.last_activity}

    @property
    def idle(self) -> bool:
        with self._lock:
            return not self._active

    # -------------------------------------------------------------- lanes
    def _audio_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            with self._lock:
                if job.name in self._queued:
                    self._queued.remove(job.name)
                self._audio_current = job.name
                self.last_activity = time.monotonic()
            self.emit({"event": "lane", "lane": "audio", "file": job.name, "job_id": job.job_id,
                       "state": "start"})
            try:
                ctx = pipeline.run_audio_stages(self.args, job.input_audio, self.device, self.emit,
                                                job_id=job.job_id, resume=job.resume)
            except Exception as exc:  # noqa: BLE001 — one bad file must not stop the batch
                self._fail(job, exc)
                continue
            finally:
                with self._lock:
                    self._audio_current = None
                self.emit({"event": "lane", "lane": "audio", "file": job.name, "job_id": job.job_id,
                           "state": "end"})
            with self._lock:
                self._futures[job.name] = self._pool.submit(self._llm_stage, job, ctx)

    def _llm_stage(self, job: FileJob, ctx: pipeline.FileContext) -> None:
        with self._lock:
            self._llm_current.add(job.name)
            self.last_activity = time.monotonic()
        self.emit({"event": "lane", "lane": "llm", "file": job.name, "job_id": job.job_id,
                   "state": "start"})
        try:
            status = pipeline.run_llm_stages(self.args, ctx, self.emit)
        except Exception as exc:  # noqa: BLE001
            self._fail(job, exc)
            return
        finally:
            with self._lock:
                self._llm_current.discard(job.name)
            self.emit({"event": "lane", "lane": "llm", "file": job.name, "job_id": job.job_id,
                       "state": "end"})
        self._finish(job, status, ctx)

    def _finish(self, job: FileJob, status: str, ctx: pipeline.FileContext) -> None:
        with self._all_done:
            self._results[job.name] = status
            self._active.discard(job.name)
            self.last_activity = time.monotonic()
            self._all_done.notify_all()
        self.emit({"event": "file_done", "file": job.name, "job_id": job.job_id, "status": status,
                   "elapsed_sec": time.monotonic() - job.submitted,
                   "timings": ctx.timings, "stats": ctx.stats})

    def _fail(self, job: FileJob, exc: BaseException) -> None:
        state_path = (self.args.intermediate_root / job.name / f"{job.name}_pipeline_state.json")
        try:
            write_pipeline_state(state_path, state="failed", reason="exception",
                                 message=f"{type(exc).__name__}: {exc}")
        except OSError:
            pass
        with self._all_done:
            self._results[job.name] = "failed"
            self._active.discard(job.name)
            self.last_activity = time.monotonic()
            self._all_done.notify_all()
        self.emit({"event": "file_failed", "file": job.name, "job_id": job.job_id,
                   "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()[-4000:],
                   "elapsed_sec": time.monotonic() - job.submitted})


def run_batch(args: argparse.Namespace, files: list[Path], device: str,
              emit: pipeline.Emitter = pipeline.default_emit) -> dict[str, str]:
    """CLI helper: pipeline a fixed list of files and return {name: status}."""
    service = PipelineService(args, device, emit)
    try:
        for input_audio in files:
            service.submit(input_audio)
        return service.wait_all()
    finally:
        service.stop()
