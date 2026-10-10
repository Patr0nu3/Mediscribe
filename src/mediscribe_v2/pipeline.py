"""Run audio preparation, transcription, diarization, fusion, role assignment,
and transcript export. Audio stages run serially while role requests for
other recordings can run concurrently.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import asr, audio_prep, diarize, fuse, roles
from .common import (
    LLM_BASE_URL_DEFAULT,
    LLM_MODEL_DEFAULT,
    LLMUnavailableError,
    configure_cpu,
    validate_llm_config,
    write_canonical_transcript,
    write_json,
    write_pipeline_state,
)
from .render import LOW_CONFIDENCE_THRESHOLD, render_final_transcript

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".mp4", ".webm"}
CANONICAL_TRANSCRIPT_SCHEMA_VERSION = 2
DEFAULT_LLM_CONCURRENCY = 2

# (key, lane, human label) — the order is the stage number shown everywhere.
STAGES: list[tuple[str, str, str]] = [
    ("prepare", "audio", "Prepare"),
    ("asr", "audio", "Transcribe"),
    ("diarize", "audio", "Diarize"),
    ("fuse", "audio", "Fuse"),
    ("roles", "llm", "Roles"),
    ("render", "llm", "Render"),
]
STAGE_TOTAL = len(STAGES)
STAGE_INDEX = {key: i + 1 for i, (key, _lane, _label) in enumerate(STAGES)}
Emitter = Callable[[dict[str, Any]], None]


def build_parser(*, require_input: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transcribe consultation audio and assign clinical speaker roles.")
    if require_input:
        parser.add_argument("input_path", nargs="*", type=Path, default=[DATA_ROOT / "input"],
                            help="Audio files or directories (default: data/input, created if missing).")
    parser.add_argument("--output-root", type=Path, default=DATA_ROOT / "output",
                        help="Where <name>/<name>_aligned_transcript.txt and _canonical.json go.")
    parser.add_argument("--intermediate-root", type=Path, default=DATA_ROOT / "intermediate",
                        help="Where per-file working artifacts go (removed on success unless kept).")
    parser.add_argument("--whisper-model", default="turbo",
                        help="openai-whisper model name for ASR engine A (default: turbo).")
    parser.add_argument("--language", default="en",
                        help="Spoken language passed to Whisper (default: en).")
    parser.add_argument("--device", default=None,
                        help="torch device for the audio models (default: cuda when available).")
    parser.add_argument("--num-speakers", type=int, default=None,
                        help="Exact speaker count for diarization.")
    parser.add_argument("--min-speakers", type=int, default=None,
                        help="Lower bound of the diarization speaker search (default: 2).")
    parser.add_argument("--max-speakers", type=int, default=None,
                        help="Upper bound of the diarization speaker search (default: 5).")
    parser.add_argument("--keep-intermediate", action="store_true",
                        help="Keep working files for review in the editor.")
    parser.add_argument("--debug-json", action="store_true",
                        help="Also write <name>_debug.json (turns, structure, ASR stats).")
    parser.add_argument("--resume", action="store_true",
                        help="Reuse prepared audio, ASR merge, and diarization when the input is unchanged.")
    parser.add_argument("--no-forced-align", dest="forced_align", action="store_false",
                        help="Keep Whisper's own word timings instead of MMS forced alignment.")
    parser.add_argument("--no-rescore", dest="rescore", action="store_false",
                        help="Skip the voice-embedding re-scoring passes in fusion.")
    parser.set_defaults(forced_align=True, rescore=True)
    parser.add_argument("--low-confidence-threshold", type=float, default=LOW_CONFIDENCE_THRESHOLD,
                        help="Role confidence below which a rendered line is labelled Unknown.")
    parser.add_argument("--llm-base-url", default=LLM_BASE_URL_DEFAULT,
                        help="API base URL (default: $MEDISCRIBE_LLM_BASE_URL).")
    parser.add_argument("--llm-model", default=LLM_MODEL_DEFAULT,
                        help="Endpoint model name (default: $MEDISCRIBE_LLM_MODEL).")
    parser.add_argument("--llm-timeout-sec", type=float, default=1800.0,
                        help="Per-request LLM timeout in seconds.")
    parser.add_argument("--llm-concurrency", type=int, default=DEFAULT_LLM_CONCURRENCY,
                        help="Concurrent recordings in the LLM stage.")
    parser.add_argument("--serial", action="store_true",
                        help="Process files sequentially.")
    return parser


def finalize_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.num_speakers is None and args.min_speakers is None and args.max_speakers is None:
        args.min_speakers, args.max_speakers = 2, 5
    args.llm_concurrency = max(1, int(args.llm_concurrency))
    return args


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return finalize_args(build_parser().parse_args(argv))


def collect_audio_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.iterdir()
                                if p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith(".")))
        elif path.is_file():
            files.append(path)
        else:
            print(f"Skipping missing input: {path}", flush=True)
    return files


def resolve_device(args: argparse.Namespace) -> str:
    try:
        import torch

        return args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    except ImportError:
        return args.device or "cpu"


# ------------------------------------------------------------------ events
def default_emit(event: dict[str, Any]) -> None:
    """Human-readable event printer for the CLI."""
    kind = event.get("event")
    name = event.get("file", "")
    prefix = f"[{name}] " if name else ""
    if kind == "stage":
        print(f"{prefix}Step {event['index']}/{event['total']}: {event['label']}...", flush=True)
    elif kind == "log":
        print(f"{prefix}{event['line']}", flush=True)
    elif kind == "file_done":
        print(f"{prefix}done ({event['status']}) in {event['elapsed_sec']:.0f}s", flush=True)
    elif kind == "file_failed":
        print(f"{prefix}FAILED: {event['error']}", flush=True)


@dataclass
class FileContext:
    input_audio: Path
    base_name: str
    output_dir: Path
    intermediate_dir: Path
    state_path: Path
    job_id: Any = None
    started: float = field(default_factory=time.monotonic)
    resumed: bool = False
    manifest: dict | None = None
    duration_sec: float = 0.0
    waveform: Any = None
    kept_words: list | None = None
    markers: list | None = None
    asr_meta: dict | None = None
    diarization: dict | None = None
    fusion: dict | None = None
    turns: list | None = None
    timings: dict[str, float] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    def emit_stage(self, emit: Emitter, key: str) -> None:
        index = STAGE_INDEX[key]
        lane = STAGES[index - 1][1]
        self.timings[f"{key}_started"] = time.monotonic()
        emit({"event": "stage", "file": self.base_name, "job_id": self.job_id, "stage": key,
              "index": index, "total": STAGE_TOTAL, "lane": lane, "label": STAGES[index - 1][2]})

    def log(self, emit: Emitter, line: str) -> None:
        emit({"event": "log", "file": self.base_name, "job_id": self.job_id, "line": line})


def new_context(args: argparse.Namespace, input_audio: Path, job_id: Any = None) -> FileContext:
    base_name = input_audio.stem
    output_dir = args.output_root / base_name
    intermediate_dir = args.intermediate_root / base_name
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    return FileContext(input_audio=input_audio, base_name=base_name, output_dir=output_dir,
                       intermediate_dir=intermediate_dir,
                       state_path=intermediate_dir / f"{base_name}_pipeline_state.json",
                       job_id=job_id)


# ------------------------------------------------------------- audio lane
def run_audio_stages(args: argparse.Namespace, input_audio: Path, device: str,
                     emit: Emitter = default_emit, *, job_id: Any = None,
                     resume: bool | None = None) -> FileContext:
    """Stages 1-4. Owns the GPU models; the result feeds the LLM lane."""
    ctx = new_context(args, input_audio, job_id)
    base_name = ctx.base_name
    intermediate_dir = ctx.intermediate_dir
    ctx.log(emit, f"Processing: {input_audio}")
    ctx.log(emit, f"Output directory: {ctx.output_dir}")
    merged_words_path = intermediate_dir / f"{base_name}_merged_words.json"
    diarization_path = intermediate_dir / f"{base_name}_diarization.json"
    write_pipeline_state(ctx.state_path, state="running", reason="started", message=str(input_audio))

    resume = args.resume if resume is None else resume
    if resume and merged_words_path.exists() and diarization_path.exists():
        fingerprint = audio_prep.audio_fingerprint(intermediate_dir, base_name)
        if fingerprint:
            import hashlib

            current = hashlib.sha256(input_audio.read_bytes()).hexdigest()
            if fingerprint == current:
                ctx.resumed = True
                ctx.log(emit, "Resume: reusing prepared audio, ASR merge, and diarization.")

    ctx.emit_stage(emit, "prepare")
    if not ctx.resumed:
        audio_prep.prepare_audio(input_audio, intermediate_dir, base_name)
    ctx.manifest = json.loads((intermediate_dir / f"{base_name}_audio_clock.json").read_text())
    ctx.waveform = audio_prep.load_analysis_waveform(intermediate_dir, base_name)
    ctx.duration_sec = float(ctx.manifest["duration_sec"])

    if ctx.resumed:
        stored = json.loads(merged_words_path.read_text())
        ctx.kept_words, ctx.markers = stored["words"], stored["markers"]
        ctx.asr_meta = stored["meta"]
        ctx.diarization = json.loads(diarization_path.read_text())
        ctx.emit_stage(emit, "asr")
        ctx.emit_stage(emit, "diarize")
        if args.rescore:
            # Fusion re-scores disputed spans with the diarizer's embedding
            # model. A resumed file skips the diarization call that loads it,
            # so load it here or the resumed result differs from a fresh run.
            diarize.load_diarization_pipeline(device)
    else:
        ctx.emit_stage(emit, "asr")
        # Engine B and the VAD are CPU/GPU-disjoint from whisper's decode, so
        # they run concurrently; results are identical to the serial order.
        from concurrent.futures import ThreadPoolExecutor

        waveform = ctx.waveform
        with ThreadPoolExecutor(max_workers=2) as pool:
            parakeet_future = pool.submit(asr.run_parakeet, waveform)
            silero_future = pool.submit(asr.silero_speech_regions, waveform)
            whisper_payload = asr.run_whisper(waveform, model_name=args.whisper_model,
                                              device=device, language=args.language)
            align_status = (asr.refine_timings_mms(waveform, whisper_payload, device=device)
                            if args.forced_align else "disabled")
            parakeet_words = parakeet_future.result()
            speech_regions = silero_future.result()
        merged, merge_stats = asr.merge_streams(whisper_payload["words"], parakeet_words, speech_regions)
        kept_words, dropped_words, markers, guard_stats = asr.apply_guard(
            merged, speech_regions, ctx.duration_sec)
        ctx.kept_words, ctx.markers = kept_words, markers
        ctx.asr_meta = {
            "engines": {"a": f"whisper:{args.whisper_model}", "b": "nemo-parakeet-tdt-0.6b-v3"},
            "forced_alignment": align_status,
            "merge_stats": merge_stats,
            "guard_stats": guard_stats,
        }
        write_json(intermediate_dir / f"{base_name}_segments.json", {
            "schema_version": 2, "asr_backend": "whisper+parakeet",
            "model_name": args.whisper_model, "language": whisper_payload.get("language"),
            "text": whisper_payload.get("text", ""),
            "segments": whisper_payload["segments"],
            "words": whisper_payload["words"],
            "merge_stats": merge_stats,
        })
        ctx.log(emit, f"  merge: {merge_stats} | guard: {guard_stats} | {align_status}")

        ctx.emit_stage(emit, "diarize")
        ctx.diarization = diarize.run_diarization(
            waveform, device=device, num_speakers=args.num_speakers,
            min_speakers=args.min_speakers, max_speakers=args.max_speakers)
        clusters = {s["speaker"] for s in ctx.diarization["raw_segments"]}
        ctx.log(emit, f"  clusters: {sorted(clusters)} ({ctx.diarization['exclusive_source']})")
        write_json(diarization_path, ctx.diarization)
        write_json(merged_words_path, {"words": kept_words, "markers": markers,
                                       "dropped": dropped_words, "meta": ctx.asr_meta})

    ctx.emit_stage(emit, "fuse")
    fusion = fuse.fuse(ctx.kept_words, ctx.diarization, ctx.waveform, rescore=args.rescore)
    ctx.fusion = fusion
    ctx.turns = fusion["turns"]
    ctx.log(emit, f"  {len(ctx.turns)} turns | echo collapsed: {fusion['echo_collapsed']} | "
                  f"rescored: {fusion['rescored_turns']} | boundary snapped: "
                  f"{fusion['boundary_snapped_words']} | words rescored: {fusion['rescored_words']} | "
                  f"overlap disputes: {fusion['overlap_dispute_words']} | sentences repaired: "
                  f"{fusion['sentences_repaired']} | sandwiches absorbed: {fusion['sandwich_absorbed']}")
    ctx.stats["turns"] = len(ctx.turns)

    # Sideline a stale WebUI editor overlay (manual edits made before this re-run).
    editor_json_path = intermediate_dir / f"{base_name}_editor.json"
    if editor_json_path.exists():
        superseded = editor_json_path.with_name(f"{base_name}_editor.superseded.json")
        editor_json_path.replace(superseded)
        ctx.log(emit, f"Sidelined stale WebUI editor overlay: {superseded}")
    write_json(intermediate_dir / f"{base_name}_sen_aligned_segments.json", ctx.turns)
    write_pipeline_state(ctx.state_path, state="running", reason="audio_done",
                         message="waiting for the LLM lane", resumable_step="roles")
    # The LLM lane never touches audio; release the waveform now so several
    # files can sit in that lane without holding hundreds of MB each.
    ctx.waveform = None
    ctx.timings["audio_sec"] = time.monotonic() - ctx.started
    return ctx


# --------------------------------------------------------------- LLM lane
def run_llm_stages(args: argparse.Namespace, ctx: FileContext, emit: Emitter = default_emit) -> str:
    """Stages 5-6. Returns "ok" or "awaiting_resume"."""
    base_name, intermediate_dir, output_dir = ctx.base_name, ctx.intermediate_dir, ctx.output_dir
    turns = ctx.turns
    assert turns is not None and ctx.fusion is not None and ctx.manifest is not None
    llm_started = time.monotonic()

    ctx.emit_stage(emit, "roles")
    block = roles.transcript_block(turns)
    try:
        structure = roles.infer_structure(turns, base_url=args.llm_base_url,
                                          model=args.llm_model, timeout_sec=args.llm_timeout_sec,
                                          cluster_similarity=ctx.fusion["cluster_similarity"],
                                          block=block)
    except LLMUnavailableError as exc:
        write_pipeline_state(ctx.state_path, state="awaiting_resume", reason="llm_unavailable",
                             message=str(exc), resumable_step="roles")
        ctx.log(emit, f"LLM unavailable; wrote awaiting_resume state: {exc}")
        return "awaiting_resume"
    roles.apply_structure(turns, structure)
    ctx.log(emit, f"  people inferred: {structure.get('people_inferred')} | department: "
                  f"{structure.get('department')} | role map: {structure.get('role_map')} | "
                  f"minor-cluster turns repaired: {structure.get('minor_cluster_turns_repaired', 0)} | "
                  f"suspected non-speech turns: {structure.get('suspected_non_speech_turns', 0)}")

    ctx.stats.update({"turns": len(turns), "people": structure.get("people_inferred"),
                      "department": structure.get("department")})

    ctx.emit_stage(emit, "render")
    # rewrite the editor overlay source with roles + flags now attached
    write_json(intermediate_dir / f"{base_name}_sen_aligned_segments.json", turns)

    final_txt_path = output_dir / f"{base_name}_aligned_transcript.txt"
    render_final_transcript(turns, final_txt_path,
                            low_confidence_threshold=args.low_confidence_threshold,
                            role_options=structure["role_options"])
    fusion, diarization = ctx.fusion, ctx.diarization
    assert diarization is not None
    canonical_payload = {
        "schema_version": CANONICAL_TRANSCRIPT_SCHEMA_VERSION,
        "authoritative": True,
        "pipeline": "mediscribe_v2",
        "audio_clock": ctx.manifest,
        "asr": ctx.asr_meta,
        "non_speech_markers": ctx.markers,
        "diarization": {k: diarization[k] for k in
                        ("backend", "constraints", "raw_segments", "alignment_segments", "exclusive_source")},
        "structure": structure,
        "fusion": {"echo_collapsed": fusion["echo_collapsed"], "rescored_turns": fusion["rescored_turns"],
                   "boundary_snapped_words": fusion["boundary_snapped_words"],
                   "rescored_words": fusion["rescored_words"],
                   "overlap_dispute_words": fusion["overlap_dispute_words"],
                   "sentences_repaired": fusion["sentences_repaired"],
                   "sandwich_absorbed": fusion["sandwich_absorbed"],
                   "cluster_similarity": fusion["cluster_similarity"]},
        "role_assignment": {"turns": turns},
        "projections": {"final_text": final_txt_path.name},
        "timings": {**ctx.timings, "llm_sec": time.monotonic() - llm_started,
                    "total_sec": time.monotonic() - ctx.started},
    }
    write_canonical_transcript(output_dir / f"{base_name}_canonical.json", canonical_payload)
    if args.debug_json:
        write_json(intermediate_dir / f"{base_name}_debug.json", {
            "merged_turns": turns, "structure": structure,
            "asr": ctx.asr_meta, "markers": ctx.markers,
        })
        ctx.log(emit, f"Debug JSON: {intermediate_dir / f'{base_name}_debug.json'}")
    ctx.log(emit, f"Canonical transcript evidence: {output_dir / f'{base_name}_canonical.json'}")

    write_pipeline_state(ctx.state_path, state="running", reason="finalizing", message="cleanup")
    finalize_artifacts(args, output_dir, intermediate_dir, base_name)
    if ctx.state_path.parent.exists():
        write_pipeline_state(ctx.state_path, state="ready", reason="complete",
                             message=str(final_txt_path))
    return "ok"


def finalize_artifacts(args: argparse.Namespace, output_dir: Path,
                       intermediate_dir: Path, base_name: str) -> None:
    keep = {f"{base_name}_aligned_transcript.txt", f"{base_name}_canonical.json",
            f"{base_name}_revisions.jsonl", f"{base_name}_revision_snapshots.json"}
    for child in output_dir.iterdir():
        if child.name not in keep and child.is_file():
            child.unlink()
    if not (args.keep_intermediate or args.debug_json):
        shutil.rmtree(intermediate_dir, ignore_errors=True)


def process_audio_file(args: argparse.Namespace, input_audio: Path, device: str,
                       emit: Emitter = default_emit) -> str:
    """Single-file, sequential path (both lanes in this thread)."""
    ctx = run_audio_stages(args, input_audio, device, emit)
    return run_llm_stages(args, ctx, emit)


def mark_failed(args: argparse.Namespace, input_audio: Path) -> None:
    state_path = (args.intermediate_root / input_audio.stem
                  / f"{input_audio.stem}_pipeline_state.json")
    write_pipeline_state(state_path, state="failed", reason="exception",
                         message=f"processing {input_audio}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.input_path == [DATA_ROOT / "input"]:
        args.input_path[0].mkdir(parents=True, exist_ok=True)
    files = collect_audio_files(args.input_path)
    if not files:
        sys.exit("No input audio files found. Add recordings to data/input or supply an input path.")
    try:
        validate_llm_config(base_url=args.llm_base_url, model=args.llm_model)
    except LLMUnavailableError as exc:
        sys.exit(str(exc))
    device = resolve_device(args)
    cpu = configure_cpu()
    print(f"Found {len(files)} audio file(s) to process.", flush=True)
    print(f"Using device: {device} | torch threads {cpu['cpu_threads']}/{cpu['cpu_cores']} cores"
          f"{'' if cpu['nice'] is None else ' | nice ' + str(cpu['nice'])}", flush=True)
    if args.num_speakers:
        print(f"Diarization speaker constraint: num_speakers={args.num_speakers}", flush=True)
    else:
        print(f"Diarization speaker constraint: min_speakers={args.min_speakers}, "
              f"max_speakers={args.max_speakers}", flush=True)
    started = time.monotonic()
    outcomes: list[str] = []
    if args.serial or len(files) == 1:
        for index, input_audio in enumerate(files, 1):
            print(f"[{index}/{len(files)}]", flush=True)
            try:
                outcomes.append(process_audio_file(args, input_audio, device))
            except Exception:
                mark_failed(args, input_audio)
                raise
    else:
        from .scheduler import run_batch

        print(f"Lanes: audio x1, llm x{args.llm_concurrency} (models load once, files overlap).",
              flush=True)
        results = run_batch(args, files, device, emit=default_emit)
        outcomes = [results[f.stem] for f in files]
    elapsed = time.monotonic() - started
    print(f"Done: {outcomes.count('ok')}/{len(files)} completed "
          f"({outcomes.count('awaiting_resume')} awaiting resume, {outcomes.count('failed')} failed) "
          f"in {elapsed:.0f}s.", flush=True)
    if "awaiting_resume" in outcomes or "failed" in outcomes:
        sys.exit(1)


if __name__ == "__main__":
    main()
