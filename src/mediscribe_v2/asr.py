"""Transcribe audio with Whisper and Parakeet, align word timings,
merge their results, and filter non-speech tokens.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np

from .common import normalize_token

ANALYSIS_SR = 16000
MERGE_TIME_TOLERANCE_SEC = 1.5
RESYNC_WINDOW = 8
# Require consecutive Parakeet-only words to filter isolated stray tokens.
SOLO_B_MIN_RUN = 2
# Suppress a repeated word when the other engine placed it nearby.
SOLO_B_ECHO_SEC = 0.35
NO_SPEECH_DROP_THRESHOLD = 0.6
# Silero false-positives on typing/paper let hallucinated words in with zero
# scrutiny; inside speech regions an uncorroborated word is still dropped when
# whisper's own no-speech detector fired AND the word confidence is poor.
IN_SPEECH_LOW_PROB = 0.3
MARKER_MIN_GAP_SEC = 2.5

_CACHE: dict[str, Any] = {}


# ------------------------------------------------------------------ whisper
def run_whisper(waveform: np.ndarray, *, model_name: str, device: str, language: str | None) -> dict:
    """Full-file whisper decode with anti-drop settings.

    The temperature fallback ladder re-decodes hard segments instead of
    dropping them, ``condition_on_previous_text=False`` stops one
    hallucination from seeding the next segment, and the permissive log-prob
    threshold keeps quiet speech that the default settings discard.
    """
    import whisper

    key = f"whisper:{model_name}:{device}"
    model = _CACHE.get(key)
    if model is None:
        model = _CACHE[key] = whisper.load_model(model_name, device=device)
    result = model.transcribe(
        waveform,
        language=language,
        word_timestamps=True,
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        condition_on_previous_text=False,
        logprob_threshold=-1.0,
        no_speech_threshold=0.6,
        beam_size=1,
        verbose=None,
    )
    words: list[dict] = []
    for seg_index, seg in enumerate(result.get("segments") or []):
        no_speech = float(seg.get("no_speech_prob") or 0.0)
        for w in seg.get("words") or []:
            text = str(w.get("word", "")).strip()
            if not text:
                continue
            words.append({
                "text": text,
                "norm": normalize_token(text),
                "start_sec": round(float(w.get("start", 0.0)), 3),
                "end_sec": round(float(w.get("end", 0.0)), 3),
                "engine": "whisper",
                "asr_prob": round(float(w.get("probability") or 0.0), 3),
                "no_speech_prob": round(no_speech, 3),
                "segment_index": seg_index,
            })
    return {"text": result.get("text", ""), "language": result.get("language"),
            "segments": result.get("segments") or [], "words": words,
            "asr_backend": "whisper", "model_name": model_name}


# ---------------------------------------------------- MMS forced re-timing
def refine_timings_mms(waveform: np.ndarray, whisper_payload: dict, *, device: str) -> str:
    """Re-time whisper words per segment with torchaudio's MMS forced aligner.

    Mutates word start/end in place. Returns a status string for the debug
    payload; any failure leaves whisper-native timings untouched.
    """
    try:
        import torch
        import torchaudio
        from torchaudio.pipelines import MMS_FA as bundle

        key = "mms_fa"
        pack = _CACHE.get(key)
        if pack is None:
            model = bundle.get_model(with_star=False).to(device).eval()
            pack = _CACHE[key] = {
                "model": model,
                "tokenizer": bundle.get_tokenizer(),
                "aligner": bundle.get_aligner(),
            }
        model, tokenizer, aligner = pack["model"], pack["tokenizer"], pack["aligner"]

        by_segment: dict[int, list[dict]] = {}
        for w in whisper_payload["words"]:
            by_segment.setdefault(w["segment_index"], []).append(w)

        refined = 0
        skipped_segments = 0
        with torch.inference_mode():
            for seg_index, seg_words in by_segment.items():
                seg = whisper_payload["segments"][seg_index]
                s0 = max(0.0, float(seg.get("start", 0.0)) - 0.2)
                s1 = float(seg.get("end", 0.0)) + 0.2
                clip = waveform[int(s0 * ANALYSIS_SR): int(s1 * ANALYSIS_SR)]
                if len(clip) < ANALYSIS_SR // 4 or (s1 - s0) > 35.0:
                    continue
                # MMS_FA vocabulary is lowercase latin; words that normalize to
                # nothing (digits stay, punctuation goes) keep whisper timing.
                alignable = [w for w in seg_words if w["norm"]]
                transcript = ["".join(ch for ch in w["norm"] if ch.isalpha() or ch == "'") or "a"
                              for w in alignable]
                if not transcript:
                    continue
                # Degenerate segments (hallucination-shaped: lots of text in a
                # sliver of audio) cannot satisfy CTC; skip them, they keep
                # whisper timings and usually die in the guard anyway.
                target_chars = sum(len(t) for t in transcript)
                if target_chars * 0.02 > (s1 - s0):
                    skipped_segments += 1
                    continue
                try:
                    emission, _ = model(torch.from_numpy(clip).unsqueeze(0).to(device))
                    if emission.shape[1] <= target_chars:
                        skipped_segments += 1
                        continue
                    spans = aligner(emission[0], tokenizer(transcript))
                except Exception:  # noqa: BLE001 — one bad segment must not kill the rest
                    skipped_segments += 1
                    continue
                ratio = len(clip) / emission.shape[1]
                for w, word_spans in zip(alignable, spans):
                    if not word_spans:
                        continue
                    w["start_sec"] = round(s0 + word_spans[0].start * ratio / ANALYSIS_SR, 3)
                    w["end_sec"] = round(s0 + word_spans[-1].end * ratio / ANALYSIS_SR, 3)
                    refined += 1
        return (f"mms_fa refined {refined}/{len(whisper_payload['words'])} words"
                + (f" ({skipped_segments} degenerate segments skipped)" if skipped_segments else ""))
    except Exception as exc:  # noqa: BLE001 — alignment is an enhancement, never fatal
        warnings.warn(f"MMS forced alignment unavailable ({type(exc).__name__}: {exc}); "
                      "keeping whisper-native word timings")
        return f"mms_fa unavailable: {type(exc).__name__}"


# ----------------------------------------------------------------- parakeet
def _parakeet_words(result: Any, offset_sec: float) -> list[dict]:
    """Group subword tokens into timed words.

    Depending on the onnx_asr/model version a word start is marked by a
    SentencePiece '▁' or by a leading space; punctuation-only tokens always
    attach to the previous word.
    """
    words: list[dict] = []
    tokens = result.tokens or []
    stamps = [float(s) for s in (result.timestamps or [])]
    for idx, (token, stamp) in enumerate(zip(tokens, stamps)):
        starts_word = token.startswith(("▁", " "))
        text = token.lstrip("▁ ")
        if not text:
            continue
        is_punct = not any(ch.isalnum() for ch in text)
        at = offset_sec + stamp
        nxt = offset_sec + stamps[idx + 1] if idx + 1 < len(stamps) else at + 0.35
        if words and (is_punct or not starts_word):
            words[-1]["text"] += text
            words[-1]["end_sec"] = round(min(nxt, at + 1.0), 3)
        else:
            words.append({"text": text, "start_sec": round(at, 3),
                          "end_sec": round(min(nxt, at + 1.0), 3)})
    for w in words:
        w["norm"] = normalize_token(w["text"])
        w["engine"] = "parakeet"
    return words


def _preload_pip_cuda_libs() -> None:
    """Make the pip-bundled CUDA 12 libs (shipped with the torch stack) visible
    to onnxruntime's CUDA provider, which dlopens them by soname."""
    import ctypes
    import glob
    import os
    import site

    patterns = ("nvidia/cublas/lib/libcublasLt.so*", "nvidia/cublas/lib/libcublas.so*",
                "nvidia/cudnn/lib/libcudnn.so*", "nvidia/cuda_runtime/lib/libcudart.so*",
                "nvidia/cufft/lib/libcufft.so*", "nvidia/curand/lib/libcurand.so*",
                "nvidia/nvjitlink/lib/libnvJitLink.so*")
    for sp in set(site.getsitepackages() + [site.getusersitepackages()]):
        for pattern in patterns:
            for lib in sorted(glob.glob(os.path.join(sp, pattern))):
                try:
                    ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


def run_parakeet(waveform: np.ndarray, *, chunk_sec: float = 30.0, overlap_sec: float = 5.0) -> list[dict]:
    import onnx_asr

    model = _CACHE.get("parakeet")
    if model is None:
        import os

        import onnxruntime

        # CPU is the deliberate default: engine B runs concurrently with
        # whisper's GPU decode, so on CPU it costs ~zero wall time, while on
        # CUDA it would compete with Whisper for GPU resources.
        # MEDISCRIBE_PARAKEET_CUDA=1 opts into the GPU for standalone use.
        available = onnxruntime.get_available_providers()
        if os.environ.get("MEDISCRIBE_PARAKEET_CUDA") == "1" and "CUDAExecutionProvider" in available:
            _preload_pip_cuda_libs()
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]
        print(f"  parakeet providers: {providers[0]}", flush=True)
        model = _CACHE["parakeet"] = onnx_asr.load_model(
            "nemo-parakeet-tdt-0.6b-v3", providers=providers
        ).with_timestamps()
    words: list[dict] = []
    for offset, keep_from, keep_until in chunk_keep_windows(
            len(waveform), chunk_sec=chunk_sec, overlap_sec=overlap_sec):
        piece = waveform[offset: offset + int(chunk_sec * ANALYSIS_SR)]
        if len(piece) < ANALYSIS_SR // 10:
            continue
        words.extend(w for w in _parakeet_words(model.recognize(piece.astype(np.float32)),
                                                offset / ANALYSIS_SR)
                     if keep_from <= w["start_sec"] < keep_until)
    return words


def chunk_keep_windows(n_samples: int, *, chunk_sec: float,
                       overlap_sec: float) -> list[tuple[int, float, float]]:
    """(sample offset, keep_from_sec, keep_until_sec) per decode chunk.

    Chunks overlap by overlap_sec so no word is cut in half, and each chunk
    keeps only its own half of that overlap — so the kept windows tile the file
    exactly. Trimming the head without trimming the tail (the original bug)
    re-emits overlap_sec/2 of speech every hop, which the merge then splices
    back in as a parakeet-only run: "be be going going to to".
    """
    chunk = int(chunk_sec * ANALYSIS_SR)
    hop = chunk - int(overlap_sec * ANALYSIS_SR)
    half_overlap = overlap_sec / 2
    windows: list[tuple[int, float, float]] = []
    for offset in range(0, max(1, n_samples), hop):
        offset_sec = offset / ANALYSIS_SR
        last = offset + chunk >= n_samples
        windows.append((offset,
                        offset_sec + (half_overlap if offset else 0.0),
                        float("inf") if last else offset_sec + chunk_sec - half_overlap))
        if last:
            break
    return windows


# ------------------------------------------------------------------- silero
def silero_speech_regions(waveform: np.ndarray) -> list[tuple[float, float]]:
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad

    model = _CACHE.get("silero")
    if model is None:
        model = _CACHE["silero"] = load_silero_vad()
    stamps = get_speech_timestamps(
        torch.from_numpy(waveform), model, sampling_rate=ANALYSIS_SR,
        return_seconds=True, speech_pad_ms=150,
    )
    return [(float(s["start"]), float(s["end"])) for s in stamps]


def _in_regions(t: float, regions: list[tuple[float, float]]) -> bool:
    return any(s <= t <= e for s, e in regions)


# -------------------------------------------------------------------- merge
def merge_streams(words_a: list[dict], words_b: list[dict],
                  speech_regions: list[tuple[float, float]]) -> tuple[list[dict], dict]:
    """Two-pointer time-bucketed merge of the whisper and parakeet streams."""

    def mid(w: dict) -> float:
        return (w["start_sec"] + w["end_sec"]) / 2

    def close(a: dict, b: dict) -> bool:
        return abs(mid(a) - mid(b)) <= MERGE_TIME_TOLERANCE_SEC

    def emit_a(w: dict, agreement: str) -> dict:
        out = dict(w)
        out["agreement"] = agreement
        return out

    merged: list[dict] = []
    stats = {"agree": 0, "disagree": 0, "solo_whisper": 0,
             "solo_parakeet_kept": 0, "solo_parakeet_dropped": 0}
    i = j = 0
    pending_b: list[dict] = []

    def flush_pending_b() -> None:
        """Parakeet-only tokens: keep runs (recovered speech), drop strays."""
        nonlocal pending_b
        if not pending_b:
            return
        keep = len(pending_b) >= SOLO_B_MIN_RUN
        for w in pending_b:
            if keep:
                out = dict(w)
                out["agreement"] = "solo_parakeet"
                out["asr_prob"] = None
                out["no_speech_prob"] = None
                merged.append(out)
                stats["solo_parakeet_kept"] += 1
            else:
                stats["solo_parakeet_dropped"] += 1
        pending_b = []

    while i < len(words_a) or j < len(words_b):
        if j >= len(words_b):
            flush_pending_b()
            merged.append(emit_a(words_a[i], "solo_whisper"))
            stats["solo_whisper"] += 1
            i += 1
            continue
        if i >= len(words_a):
            pending_b.append(words_b[j])
            j += 1
            continue
        a, b = words_a[i], words_b[j]
        if a["norm"] and a["norm"] == b["norm"] and close(a, b):
            flush_pending_b()
            merged.append(emit_a(a, "agree"))
            stats["agree"] += 1
            i += 1
            j += 1
            continue
        # resync: nearest equal-norm pair within the lookahead window
        best: tuple[int, int] | None = None
        for di in range(RESYNC_WINDOW):
            if i + di >= len(words_a):
                break
            for dj in range(RESYNC_WINDOW):
                if j + dj >= len(words_b):
                    break
                aa, bb = words_a[i + di], words_b[j + dj]
                if aa["norm"] and aa["norm"] == bb["norm"] and close(aa, bb):
                    if best is None or di + dj < best[0] + best[1]:
                        best = (di, dj)
            if best and best[0] + best[1] <= di:
                break
        if best is not None:
            di, dj = best
            for k in range(di):
                w = words_a[i + k]
                overlapped = any(abs(mid(w) - mid(words_b[j + m])) <= MERGE_TIME_TOLERANCE_SEC
                                 for m in range(dj))
                merged.append(emit_a(w, "disagree" if overlapped else "solo_whisper"))
                stats["disagree" if overlapped else "solo_whisper"] += 1
            for m in range(dj):
                w = words_b[j + m]
                shadowed = any(abs(mid(w) - mid(words_a[i + k])) <= 0.6 for k in range(max(1, di)))
                if not shadowed:
                    pending_b.append(w)
            i += di
            j += dj
            continue
        # no resync found: advance whichever stream is earlier in time
        if mid(a) <= mid(b):
            merged.append(emit_a(a, "solo_whisper"))
            stats["solo_whisper"] += 1
            i += 1
        else:
            pending_b.append(b)
            j += 1
    flush_pending_b()
    merged.sort(key=lambda w: (w["start_sec"], w["end_sec"]))
    merged, echoed = _drop_echoed_solo_b(merged)
    stats["solo_parakeet_kept"] -= echoed
    stats["solo_parakeet_echo_dropped"] = echoed
    return merged, stats


def _drop_echoed_solo_b(merged: list[dict]) -> tuple[list[dict], int]:
    """Drop engine-B-only tokens that merely repeat a whisper-backed word.

    A genuine recovery says something whisper never said. A token repeating the
    same word whisper already placed a moment earlier is an artefact of B's
    chunking or of a decoder loop, and the merge's local shadow test misses it
    whenever the resync lands a few words away.
    """
    anchors: dict[str, list[float]] = {}
    for w in merged:
        if w["agreement"] != "solo_parakeet" and w["norm"]:
            anchors.setdefault(w["norm"], []).append(w["start_sec"])
    kept: list[dict] = []
    dropped = 0
    for w in merged:
        if (w["agreement"] == "solo_parakeet"
                and any(abs(t - w["start_sec"]) <= SOLO_B_ECHO_SEC
                        for t in anchors.get(w["norm"], ()))):
            dropped += 1
            continue
        kept.append(w)
    return kept, dropped


# -------------------------------------------------------------------- guard
def apply_guard(merged: list[dict], speech_regions: list[tuple[float, float]],
                duration_sec: float) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Drop tokens that fail the speech vote; emit non-speech timeline markers."""
    kept: list[dict] = []
    dropped: list[dict] = []
    for w in merged:
        t = (w["start_sec"] + w["end_sec"]) / 2
        in_speech = _in_regions(t, speech_regions)
        w["in_speech"] = in_speech
        if w["agreement"] == "agree":
            kept.append(w)
            continue
        if in_speech:
            hallucination_shaped = (
                w["agreement"] == "solo_whisper"
                and (w.get("no_speech_prob") or 0.0) >= NO_SPEECH_DROP_THRESHOLD
                and (w.get("asr_prob") or 0.0) <= IN_SPEECH_LOW_PROB)
            (dropped if hallucination_shaped else kept).append(w)
            continue
        suspicious = (w["agreement"] == "solo_parakeet"
                      or (w.get("no_speech_prob") or 0.0) >= NO_SPEECH_DROP_THRESHOLD)
        (dropped if suspicious else kept).append(w)

    markers: list[dict] = []
    edges = sorted([(s, e) for s, e in speech_regions])
    cursor = 0.0
    for s, e in edges + [(duration_sec, duration_sec)]:
        if s - cursor >= MARKER_MIN_GAP_SEC:
            n_dropped = sum(1 for w in dropped if cursor <= w["start_sec"] <= s)
            markers.append({"start_sec": round(cursor, 1), "end_sec": round(s, 1),
                            "kind": "non_speech", "dropped_tokens": n_dropped})
        cursor = max(cursor, e)
    stats = {"kept": len(kept), "dropped_non_speech": len(dropped), "markers": len(markers)}
    return kept, dropped, markers, stats
