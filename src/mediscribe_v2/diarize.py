"""Stage 3 — diarization with pyannote community-1.

The pipeline is fed a preloaded waveform dict (sidesteps torchcodec), asked
for both the raw and the *exclusive* (non-overlapping) annotation — the
timeline purpose-built for zipping with a transcript — and its embedding
model is kept reachable for disputed-span re-scoring in fusion.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np

ANALYSIS_SR = 16000
_CACHE: dict[str, Any] = {}

COMMUNITY1_REPOS = (
    "pyannote-community/speaker-diarization-community-1",
    "pyannote/speaker-diarization-community-1",
)


def load_diarization_pipeline(device: str):
    # pyannote warns at import when torchcodec cannot load; the pipeline never
    # uses torchcodec (it hands pyannote a preloaded waveform), so hide it.
    warnings.filterwarnings("ignore", message=r"(?s).*torchcodec is not installed correctly.*")
    from pyannote.audio import Pipeline
    import torch

    pipeline = _CACHE.get("diar")
    if pipeline is None:
        last: Exception | None = None
        for repo in COMMUNITY1_REPOS:
            try:
                pipeline = Pipeline.from_pretrained(repo)
                break
            except Exception as exc:  # noqa: BLE001 — try the mirror, then fail loudly
                last = exc
                pipeline = None
        if pipeline is None:
            raise RuntimeError(f"community-1 diarization pipeline unavailable: {last}")
        pipeline.to(torch.device(device))
        _CACHE["diar"] = pipeline
    return pipeline


def _annotation_segments(annotation) -> list[dict]:
    segments = []
    for segment, _track, label in annotation.itertracks(yield_label=True):
        segments.append({
            "start_sec": round(float(segment.start), 3),
            "end_sec": round(float(segment.end), 3),
            "speaker": str(label),
        })
    segments.sort(key=lambda s: (s["start_sec"], s["end_sec"]))
    return segments


def run_diarization(
    waveform: np.ndarray,
    *,
    device: str,
    num_speakers: int | None,
    min_speakers: int | None,
    max_speakers: int | None,
) -> dict:
    import torch

    pipeline = load_diarization_pipeline(device)
    kwargs: dict[str, int] = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = num_speakers
    else:
        if min_speakers is not None:
            kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            kwargs["max_speakers"] = max_speakers
    audio = {"waveform": torch.from_numpy(waveform).unsqueeze(0), "sample_rate": ANALYSIS_SR}
    result = pipeline(audio, **kwargs)

    raw = getattr(result, "speaker_diarization", result)
    exclusive = getattr(result, "exclusive_speaker_diarization", None)
    payload = {
        "backend": "pyannote-community-1",
        "constraints": kwargs,
        "raw_segments": _annotation_segments(raw),
        "alignment_segments": _annotation_segments(exclusive) if exclusive is not None else [],
    }
    if not payload["alignment_segments"]:
        payload["alignment_segments"] = make_exclusive(payload["raw_segments"])
        payload["exclusive_source"] = "derived_midpoint_split"
    else:
        payload["exclusive_source"] = "pipeline_exclusive"
    return payload


def make_exclusive(segments: list[dict]) -> list[dict]:
    """Fallback non-overlapping timeline: split overlaps at their midpoint."""
    out: list[dict] = []
    for seg in sorted(segments, key=lambda s: (s["start_sec"], s["end_sec"])):
        seg = dict(seg)
        while out and seg["start_sec"] < out[-1]["end_sec"]:
            prev = out[-1]
            if seg["end_sec"] <= prev["end_sec"] and prev["speaker"] == seg["speaker"]:
                seg = None
                break
            midpoint = (seg["start_sec"] + min(prev["end_sec"], seg["end_sec"])) / 2
            prev["end_sec"] = round(midpoint, 3)
            seg["start_sec"] = round(midpoint, 3)
            if prev["end_sec"] <= prev["start_sec"]:
                out.pop()
                continue
            break
        if seg is not None and seg["end_sec"] > seg["start_sec"]:
            out.append(seg)
    return out


# ------------------------------------------------- disputed-span re-scoring
def build_cluster_centroids(waveform: np.ndarray, raw_segments: list[dict]) -> dict[str, np.ndarray] | None:
    """Pooled embedding per cluster from its longest segments (reuses the
    community-1 embedding model; returns None when internals are unreachable)."""
    embedder = _get_embedder()
    if embedder is None:
        return None
    by_cluster: dict[str, list[dict]] = {}
    for seg in raw_segments:
        by_cluster.setdefault(seg["speaker"], []).append(seg)
    centroids: dict[str, np.ndarray] = {}
    for cluster, segs in by_cluster.items():
        segs = sorted(segs, key=lambda s: s["end_sec"] - s["start_sec"], reverse=True)[:6]
        vecs = [v for v in (_embed_span(waveform, s["start_sec"], s["end_sec"]) for s in segs) if v is not None]
        if vecs:
            centroid = np.mean(vecs, axis=0)
            centroids[cluster] = centroid / (np.linalg.norm(centroid) + 1e-9)
    return centroids or None


def centroid_similarity(centroids: dict[str, Any] | None) -> dict[str, float]:
    """Pairwise cosine similarity between cluster centroids (unit-norm, so a
    plain dot product). Keyed "A~B" with names sorted, for prompt/provenance."""
    if not centroids or len(centroids) < 2:
        return {}
    names = sorted(centroids)
    return {f"{a}~{b}": round(float(np.dot(centroids[a], centroids[b])), 3)
            for i, a in enumerate(names) for b in names[i + 1:]}


def rescore_span(waveform: np.ndarray, start_sec: float, end_sec: float,
                 centroids: dict[str, np.ndarray]) -> dict[str, float] | None:
    """Cosine similarity of the pooled span embedding against each centroid."""
    vec = _embed_span(waveform, start_sec, end_sec)
    if vec is None:
        return None
    return {cluster: round(float(np.dot(vec, centroid)), 3) for cluster, centroid in centroids.items()}


def _get_embedder():
    if "embedder" in _CACHE:
        return _CACHE["embedder"]
    embedder = None
    try:
        pipeline = _CACHE.get("diar")
        candidate = getattr(pipeline, "_embedding", None)
        if candidate is not None and callable(candidate):
            embedder = candidate
    except Exception:  # noqa: BLE001
        embedder = None
    if embedder is None:
        warnings.warn("community-1 embedding model not reachable; disputed spans keep flags only")
    _CACHE["embedder"] = embedder
    return embedder


def _embed_span(waveform: np.ndarray, start_sec: float, end_sec: float) -> np.ndarray | None:
    import torch

    embedder = _get_embedder()
    if embedder is None:
        return None
    start_sec = max(0.0, start_sec - 0.1)
    end_sec = min(len(waveform) / ANALYSIS_SR, end_sec + 0.1)
    if end_sec - start_sec < 0.4:
        pad = (0.4 - (end_sec - start_sec)) / 2
        start_sec, end_sec = max(0.0, start_sec - pad), end_sec + pad
    clip = waveform[int(start_sec * ANALYSIS_SR): int(end_sec * ANALYSIS_SR)]
    if len(clip) < ANALYSIS_SR // 5:
        return None
    try:
        with torch.inference_mode():
            vec = embedder(torch.from_numpy(clip).unsqueeze(0).unsqueeze(0))
        vec = np.asarray(vec).reshape(-1)
        return vec / (np.linalg.norm(vec) + 1e-9)
    except Exception:  # noqa: BLE001 — rescoring is optional by design
        return None
