"""Prepare native PCM and mono 16 kHz audio, with hashes for resume."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from .common import write_json

ANALYSIS_SR = 16000


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode(errors='replace')[:500]}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_audio(input_audio: Path, intermediate_dir: Path, base_name: str) -> dict:
    """Write <base>_source_pcm.wav + <base>_converted.wav; return manifest."""
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    source_pcm = intermediate_dir / f"{base_name}_source_pcm.wav"
    converted = intermediate_dir / f"{base_name}_converted.wav"

    _run_ffmpeg(["-i", str(input_audio), "-map_metadata", "-1", "-acodec", "pcm_s16le", str(source_pcm)])
    _run_ffmpeg(["-i", str(source_pcm), "-ac", "1", "-ar", str(ANALYSIS_SR),
                 "-acodec", "pcm_s16le", str(converted)])

    info = sf.info(str(converted))
    duration_sec = info.frames / info.samplerate
    manifest = {
        "schema_version": 2,
        "input_path": str(input_audio),
        "input_sha256": _sha256(input_audio),
        "source_pcm_sha256": _sha256(source_pcm),
        "converted_sha256": _sha256(converted),
        "analysis_sample_rate": ANALYSIS_SR,
        "duration_sec": round(duration_sec, 3),
    }
    write_json(intermediate_dir / f"{base_name}_audio_clock.json", manifest)
    return manifest


def load_analysis_waveform(intermediate_dir: Path, base_name: str) -> np.ndarray:
    """The mono 16 kHz float32 waveform shared by ASR, VAD, and diarization."""
    data, rate = sf.read(str(intermediate_dir / f"{base_name}_converted.wav"), always_2d=True)
    assert rate == ANALYSIS_SR, f"expected {ANALYSIS_SR} Hz, got {rate}"
    return data.mean(axis=1).astype(np.float32)


def audio_fingerprint(intermediate_dir: Path, base_name: str) -> str | None:
    clock = intermediate_dir / f"{base_name}_audio_clock.json"
    if not clock.exists():
        return None
    try:
        return json.loads(clock.read_text()).get("input_sha256")
    except (json.JSONDecodeError, OSError):
        return None
