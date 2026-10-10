"""Stage 4 — word-speaker fusion.

A deterministic zip of the merged word lattice onto the exclusive speaker
timeline. Every word keeps a best-guess speaker plus one continuous
confidence; low confidence sets an `uncertain` flag instead of destroying the
label, so no word is ever relabelled "Unknown" by arithmetic. Disputed spans
are re-scored against cluster centroids when the
embedding model is reachable, and echo turns (identical short repeats) are
collapsed with a count.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .common import join_text_pieces, load_token_lexicon, normalize_token

UNCERTAIN_THRESHOLD = 0.45
TURN_GAP_SEC = 1.5
NEAREST_TOLERANCE_SEC = 2.0
ECHO_MAX_WORDS = 4
ECHO_WINDOW_SEC = 6.0
RESCORE_MARGIN = 0.08

# Boundary snap: word timestamps and the exclusive split are both imprecise
# near a speaker change, but a real turn change almost always sits on a pause.
SNAP_WINDOW_SEC = 0.25       # words this close to a boundary are re-decided
SNAP_MIN_GAP_SEC = 0.10      # smallest split score trusted as the turn change
SNAP_MAX_SEG_GAP_SEC = 0.5   # beyond this the segments don't share a boundary
SNAP_AMBIGUOUS_SEC = 0.15    # no-pause boundaries flag only words this close
SNAP_PUNCT_BONUS = 0.20      # splits right after sentence-final punctuation
SNAP_NONFINAL_PENALTY = 0.10  # splits after words that rarely end a turn
SENTENCE_FINAL_RE = re.compile(r"[.?!…][\"')\]]*$")
LEXICON_ROOT = Path(__file__).resolve().parents[2] / "config" / "lexicons"
NONFINAL_TOKENS = load_token_lexicon(LEXICON_ROOT / "nonfinal_words.json")

# Sandwich absorption: a short turn from cluster X between two turns of
# cluster Y is usually another fragment of Y from over-clustering
# — absorb it unless its own cluster's embedding clearly defends it.
SANDWICH_MAX_WORDS = 6
SANDWICH_MAX_SEC = 2.5
SANDWICH_PRIOR = 0.05

# Sentence repair: one sentence has one speaker. Whisper's punctuation
# delimits sentences; a sentence scattered across clusters is reunited under
# its dominant cluster. Dominance guards keep real hand-offs that merely lack
# punctuation from being swallowed.
CONTINUATION_MAX_GAP_SEC = 1.0
SENTENCE_REPAIR_MIN_WORDS = 3
SENTENCE_REPAIR_MAX_WORDS = 30
SENTENCE_REPAIR_MIN_SHARE = 0.6
SHORT_TURN_RESCORE_WORDS = 3
MIN_RESCORE_SEC = 0.15

OVERLAP_DISPUTE_PENALTY = 0.15
WORD_RESCORE_MARGIN = 0.10
BACKCHANNEL_MAX_SEC = 0.6
BACKCHANNEL_ISOLATION_SEC = 0.15
BACKCHANNEL_TOKENS = load_token_lexicon(LEXICON_ROOT / "backchannels.json")


def assign_words(words: list[dict], timeline: list[dict]) -> None:
    """Attach speaker/confidence to each word from the exclusive timeline."""
    if not timeline:
        for w in words:
            w.update({"speaker": "SPEAKER_00", "speaker_confidence": 0.0,
                      "speaker_assignment_reason": "no_diarization", "uncertain": True})
        return
    starts = [seg["start_sec"] for seg in timeline]
    import bisect

    for w in words:
        mid = (w["start_sec"] + w["end_sec"]) / 2
        idx = bisect.bisect_right(starts, mid) - 1
        best, reason, confidence = None, "nearest", 0.0
        for probe in (idx, idx + 1, idx - 1):
            if 0 <= probe < len(timeline):
                seg = timeline[probe]
                if seg["start_sec"] <= mid <= seg["end_sec"]:
                    best = seg
                    overlap = (min(w["end_sec"], seg["end_sec"]) - max(w["start_sec"], seg["start_sec"]))
                    duration = max(0.02, w["end_sec"] - w["start_sec"])
                    edge = min(mid - seg["start_sec"], seg["end_sec"] - mid)
                    confidence = min(1.0, 0.55 + 0.35 * max(0.0, overlap / duration)
                                     + 0.10 * min(1.0, edge / 0.5))
                    reason = "timeline"
                    break
        if best is None:
            candidates = []
            for probe in (idx, idx + 1):
                if 0 <= probe < len(timeline):
                    seg = timeline[probe]
                    distance = max(seg["start_sec"] - mid, mid - seg["end_sec"], 0.0)
                    candidates.append((distance, seg))
            if candidates:
                distance, best = min(candidates, key=lambda c: c[0])
                confidence = max(0.05, 0.5 - 0.2 * min(distance, NEAREST_TOLERANCE_SEC))
                reason = "nearest"
        if best is None:
            best = timeline[0]
            reason = "fallback_first"
        agreement_bonus = {"agree": 0.05, "disagree": -0.05,
                           "solo_whisper": 0.0, "solo_parakeet": -0.1}.get(w.get("agreement"), 0.0)
        confidence = round(max(0.0, min(1.0, confidence + agreement_bonus)), 3)
        w.update({
            "speaker": best["speaker"],
            "raw_speaker": best["speaker"],
            "timeline_speaker": best["speaker"],  # immutable provenance; later passes rewrite speaker
            "speaker_confidence": confidence,
            "speaker_assignment_reason": reason,
            "uncertain": confidence < UNCERTAIN_THRESHOLD,
        })


def mark_overlap_disputes(words: list[dict], raw_segments: list[dict]) -> int:
    """Flag words where the raw diarization hears two or more speakers at once.

    The exclusive timeline resolves overlap regions arbitrarily, so a word
    inside one is a genuine dispute: confidence drops and the word becomes
    eligible for embedding re-scoring instead of being trusted."""
    if not words or not raw_segments:
        return 0
    segments = sorted(raw_segments, key=lambda s: (s["start_sec"], s["end_sec"]))
    active: list[dict] = []
    seg_index = 0
    disputed = 0
    for word in sorted(words, key=lambda x: (x["start_sec"] + x["end_sec"]) / 2):
        mid = (word["start_sec"] + word["end_sec"]) / 2
        while seg_index < len(segments) and segments[seg_index]["start_sec"] <= mid:
            active.append(segments[seg_index])
            seg_index += 1
        active = [s for s in active if s["end_sec"] >= mid]
        if len({s["speaker"] for s in active}) >= 2:
            word["overlap_dispute"] = True
            word["speaker_confidence"] = round(
                max(0.0, word["speaker_confidence"] - OVERLAP_DISPUTE_PENALTY), 3)
            word["uncertain"] = word["speaker_confidence"] < UNCERTAIN_THRESHOLD
            disputed += 1
    return disputed


def snap_boundary_words(words: list[dict], timeline: list[dict]) -> int:
    """Re-decide words whose midpoint sits within SNAP_WINDOW_SEC of a speaker
    change by snapping the boundary to the largest inter-word silence beside
    it; when no pause exists the nearest words are flagged ambiguous so the
    embedding passes can arbitrate instead of the raw midpoint."""
    if not words or len(timeline) < 2:
        return 0
    snapped = 0
    for prev_seg, next_seg in zip(timeline, timeline[1:]):
        if prev_seg["speaker"] == next_seg["speaker"]:
            continue
        if next_seg["start_sec"] - prev_seg["end_sec"] > SNAP_MAX_SEG_GAP_SEC:
            continue
        boundary = (prev_seg["end_sec"] + next_seg["start_sec"]) / 2
        window = [i for i, word in enumerate(words)
                  if abs((word["start_sec"] + word["end_sec"]) / 2 - boundary) <= SNAP_WINDOW_SEC]
        if not window:
            continue
        span = range(max(0, window[0] - 1), min(len(words), window[-1] + 2))
        best_score, split = 0.0, None
        for a, b in zip(span, span[1:]):
            # Silence is the acoustic cue; punctuation is the linguistic one.
            # In rapid turn-taking the audible pause often falls after a stolen
            # word ("...doing? I'm | good"), so a split right after
            # sentence-final punctuation outranks a slightly longer gap after a
            # word that could not plausibly end a turn.
            score = words[b]["start_sec"] - words[a]["end_sec"]
            if SENTENCE_FINAL_RE.search(words[a]["text"].strip()):
                score += SNAP_PUNCT_BONUS
            elif normalize_token(words[a]["text"]) in NONFINAL_TOKENS:
                score -= SNAP_NONFINAL_PENALTY
            if score > best_score:
                best_score = score
                split = (words[a]["end_sec"] + words[b]["start_sec"]) / 2
        if split is not None and best_score >= SNAP_MIN_GAP_SEC:
            for i in window:
                word = words[i]
                mid = (word["start_sec"] + word["end_sec"]) / 2
                target = prev_seg["speaker"] if mid < split else next_seg["speaker"]
                if word["speaker"] != target:
                    word["speaker"] = word["raw_speaker"] = target
                    word["speaker_assignment_reason"] = "boundary_snap"
                    word["speaker_confidence"] = round(min(1.0, 0.6 + min(0.3, best_score)), 3)
                    word["uncertain"] = word["speaker_confidence"] < UNCERTAIN_THRESHOLD
                    snapped += 1
        else:
            for i in window:
                word = words[i]
                if abs((word["start_sec"] + word["end_sec"]) / 2 - boundary) > SNAP_AMBIGUOUS_SEC:
                    continue
                word["boundary_ambiguous"] = True
                word["speaker_confidence"] = min(
                    word["speaker_confidence"], round(UNCERTAIN_THRESHOLD - 0.05, 3))
                word["uncertain"] = True
    return snapped


def _isolated(words: list[dict], index: int) -> bool:
    word = words[index]
    if index > 0 and word["start_sec"] - words[index - 1]["end_sec"] < BACKCHANNEL_ISOLATION_SEC:
        return False
    if (index + 1 < len(words)
            and words[index + 1]["start_sec"] - word["end_sec"] < BACKCHANNEL_ISOLATION_SEC):
        return False
    return True


def _utterance_shaped(words: list[dict], index: int) -> bool:
    """A backchannel that stands as its own utterance rather than continuing a
    clause. The interesting "Okay." is the one said *over* the other speaker —
    it never gets the silence `_isolated` demands, so ASR punctuation is the
    only evidence left. Requiring the previous word to have closed its own
    sentence (or left a pause) keeps clause-internal "…are you okay?" and
    "…and I said no." out."""
    if not SENTENCE_FINAL_RE.search(words[index]["text"].strip()):
        return False
    if index == 0:
        return True
    prev = words[index - 1]
    return (bool(SENTENCE_FINAL_RE.search(prev["text"].strip()))
            or words[index]["start_sec"] - prev["end_sec"] >= BACKCHANNEL_ISOLATION_SEC)


def word_rescore_candidates(words: list[dict]) -> list[int]:
    """Short words whose midpoint assignment shouldn't be trusted: disputed
    overlap regions, no-pause boundary words, and backchannels ("Yeah") that
    midpoint placement absorbs into the surrounding speaker."""
    out = []
    for index, word in enumerate(words):
        if word["end_sec"] - word["start_sec"] > BACKCHANNEL_MAX_SEC:
            continue
        if (word.get("overlap_dispute") or word.get("boundary_ambiguous")
                or (normalize_token(word["text"]) in BACKCHANNEL_TOKENS
                    and (_isolated(words, index) or _utterance_shaped(words, index)))):
            out.append(index)
    return out


def rescore_words(words: list[dict], indices: list[int], waveform, centroids) -> int:
    """Per-word embedding vote against cluster centroids; flip on clear margin."""
    from . import diarize

    if centroids is None:
        return 0
    changed = 0
    for index in indices:
        word = words[index]
        scores = diarize.rescore_span(waveform, word["start_sec"], word["end_sec"], centroids)
        if not scores:
            continue
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        word["rescore"] = dict(ranked)
        best, best_score = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else -1.0
        confidence = round(min(1.0, 0.5 + best_score / 4), 3)
        if best != word["speaker"] and best_score - runner >= WORD_RESCORE_MARGIN:
            word["speaker"] = word["raw_speaker"] = best
            word["speaker_assignment_reason"] = "word_rescore"
            word["speaker_confidence"] = confidence
            changed += 1
        elif best == word["speaker"]:
            word["speaker_confidence"] = max(word["speaker_confidence"], confidence)
        word["uncertain"] = word["speaker_confidence"] < UNCERTAIN_THRESHOLD
    return changed


def build_turns(words: list[dict]) -> list[dict]:
    """Group attributed words into turns on speaker change or a long gap."""
    turns: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = join_text_pieces(w["text"] for w in current)
        confs = [w["speaker_confidence"] for w in current]
        turns.append({
            "raw_speaker": current[0]["speaker"],
            "speaker": current[0]["speaker"],
            "start_sec": current[0]["start_sec"],
            "end_sec": current[-1]["end_sec"],
            "text": text,
            "words": current,
            "speaker_confidence": round(sum(confs) / len(confs), 3),
            "speaker_assignment_reason": ("uncertain" if all(w["uncertain"] for w in current)
                                          else current[0]["speaker_assignment_reason"]),
            "uncertain": sum(w["uncertain"] for w in current) > len(current) / 2,
            "word_count": len(current),
            "turn_word_count": len(current),
            "turn_duration_sec": round(max(0.0, current[-1]["end_sec"] - current[0]["start_sec"]), 3),
            "engine_agreement": round(
                sum(1 for w in current if w.get("agreement") == "agree") / len(current), 3),
        })
        current = []

    for w in words:
        if current and (w["speaker"] != current[-1]["speaker"]
                        or w["start_sec"] - current[-1]["end_sec"] > TURN_GAP_SEC):
            flush()
        current.append(w)
    flush()
    return turns


def collapse_echo_turns(turns: list[dict]) -> tuple[list[dict], int]:
    """Drop immediate short repeats of an identical utterance (echo artifacts)."""
    out: list[dict] = []
    collapsed = 0
    for turn in turns:
        norm = " ".join(normalize_token(w["text"]) for w in turn["words"])
        # Same speaker only: two people trading "Okay." is a real exchange, and
        # collapsing it deletes the second person's words from the transcript.
        if (out and turn["word_count"] <= ECHO_MAX_WORDS
                and norm and norm == out[-1].get("_norm")
                and turn["speaker"] == out[-1]["speaker"]
                and turn["start_sec"] - out[-1]["end_sec"] <= ECHO_WINDOW_SEC):
            out[-1]["end_sec"] = turn["end_sec"]
            out[-1]["echo_repeats"] = out[-1].get("echo_repeats", 1) + 1
            collapsed += 1
            continue
        turn["_norm"] = norm
        out.append(turn)
    for turn in out:
        turn.pop("_norm", None)
    return out, collapsed


def rescore_uncertain_turns(turns: list[dict], waveform, centroids) -> int:
    """Re-score uncertain turns' pooled span embeddings against cluster
    centroids; reassign when a different cluster wins by a clear margin.
    Short turns that border a speaker change are checked even when confident —
    midpoint assignment is confidently wrong exactly there."""
    from . import diarize

    if centroids is None:
        return 0
    changed = 0
    for index, turn in enumerate(turns):
        if turn["turn_duration_sec"] < MIN_RESCORE_SEC:
            continue
        short_boundary = (
            turn["turn_word_count"] <= SHORT_TURN_RESCORE_WORDS
            and ((index > 0 and turns[index - 1]["speaker"] != turn["speaker"])
                 or (index + 1 < len(turns) and turns[index + 1]["speaker"] != turn["speaker"])))
        if not (turn["uncertain"] or short_boundary):
            continue
        scores = diarize.rescore_span(waveform, turn["start_sec"], turn["end_sec"], centroids)
        if not scores:
            continue
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        turn["rescore"] = dict(ranked)
        best, best_score = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else -1.0
        if best != turn["speaker"] and best_score - runner >= RESCORE_MARGIN:
            turn["speaker"] = turn["raw_speaker"] = best
            turn["speaker_assignment_reason"] = "embedding_rescore"
            turn["speaker_confidence"] = round(max(turn["speaker_confidence"], 0.5 + best_score / 4), 3)
            turn["uncertain"] = turn["speaker_confidence"] < UNCERTAIN_THRESHOLD
            for w in turn["words"]:
                # keep word provenance truthful: the turn decision now owns
                # these words
                w["speaker"] = w["raw_speaker"] = best
                w["speaker_assignment_reason"] = "embedding_rescore"
                w["speaker_confidence"] = turn["speaker_confidence"]
                w["uncertain"] = turn["uncertain"]
            changed += 1
    return changed


def repair_fragmented_sentences(words: list[dict]) -> int:
    """Reunite sentences scattered across clusters under one speaker.

    Word-per-turn shatter ("I | feel | like | it | kind of...") defeats any
    pairwise folding — each fragment ping-pongs between neighbors. A sentence
    is the right repair unit: split the stream at sentence-final punctuation
    (or a long silence), and when one sentence's words carry 2+ cluster labels,
    assign the whole sentence to the dominant cluster — but only when it truly
    dominates (>=60% of the words AND >=2x the runner-up), so an unpunctuated
    genuine hand-off is left alone. Embedding-confirmed interjections keep
    their speaker."""
    changed_sentences = 0
    sentence: list[int] = []

    def flush() -> None:
        nonlocal changed_sentences, sentence
        indices, sentence = sentence, []
        if not (SENTENCE_REPAIR_MIN_WORDS <= len(indices) <= SENTENCE_REPAIR_MAX_WORDS):
            return
        counts = Counter(words[i]["speaker"] for i in indices)
        if len(counts) < 2:
            return
        ranked = counts.most_common()
        winner, winner_count = ranked[0]
        if (winner_count < SENTENCE_REPAIR_MIN_SHARE * len(indices)
                or winner_count < 2 * ranked[1][1]):
            return
        moved = 0
        for i in indices:
            word = words[i]
            if word["speaker"] == winner:
                continue
            # Only a genuine interjection ("yeah", "okay") keeps an embedding-
            # confirmed speaker; for any other mid-sentence word, sentence
            # continuity outranks a noisy sub-second embedding vote.
            if (word.get("speaker_assignment_reason") == "word_rescore"
                    and normalize_token(word["text"]) in BACKCHANNEL_TOKENS):
                continue
            word["speaker"] = word["raw_speaker"] = winner
            word["speaker_assignment_reason"] = "sentence_repair"
            word["speaker_confidence"] = 0.6
            word["uncertain"] = False
            moved += 1
        if moved:
            changed_sentences += 1

    for idx, word in enumerate(words):
        if sentence and word["start_sec"] - words[idx - 1]["end_sec"] > CONTINUATION_MAX_GAP_SEC:
            flush()
        sentence.append(idx)
        if SENTENCE_FINAL_RE.search(word["text"].strip()):
            flush()
    flush()
    return changed_sentences


def absorb_sandwiched_turns(turns: list[dict], waveform, centroids) -> int:
    """Absorb a short foreign-cluster turn wedged between two turns of the
    same speaker unless its own cluster's embedding clearly defends it."""
    from . import diarize

    if centroids is None:
        return 0
    changed = 0
    for index in range(1, len(turns) - 1):
        prev, cur, nxt = turns[index - 1], turns[index], turns[index + 1]
        if prev["speaker"] != nxt["speaker"] or cur["speaker"] == prev["speaker"]:
            continue
        if (cur["turn_word_count"] > SANDWICH_MAX_WORDS
                or cur["turn_duration_sec"] > SANDWICH_MAX_SEC):
            continue
        if any(w.get("speaker_assignment_reason") == "word_rescore" for w in cur["words"]):
            continue  # embedding already confirmed this as a real interjection
        scores = diarize.rescore_span(
            waveform, cur["start_sec"], cur["end_sec"], centroids)
        if not scores:
            continue
        neighbor, own = scores.get(prev["speaker"]), scores.get(cur["speaker"])
        if neighbor is None or own is None or own - neighbor > SANDWICH_PRIOR:
            continue
        for word in cur["words"]:
            word["speaker"] = word["raw_speaker"] = prev["speaker"]
            word["speaker_assignment_reason"] = "sandwich_absorb"
        cur["speaker"] = cur["raw_speaker"] = prev["speaker"]
        changed += 1
    return changed


def _rebuild_turns(words: list[dict]) -> list[dict]:
    turns = build_turns(words)
    turns, _ = collapse_echo_turns(turns)
    return turns


def fuse(words: list[dict], diarization: dict, waveform, *, rescore: bool = True) -> dict[str, Any]:
    timeline = diarization["alignment_segments"] or diarization["raw_segments"]
    assign_words(words, timeline)
    disputed = mark_overlap_disputes(words, diarization["raw_segments"])
    snapped = snap_boundary_words(words, timeline)
    centroids = None
    words_rescored = 0
    if rescore:
        from . import diarize

        candidates = word_rescore_candidates(words)
        if candidates:
            centroids = diarize.build_cluster_centroids(waveform, diarization["raw_segments"])
            words_rescored = rescore_words(words, candidates, waveform, centroids)
    sentences_repaired = repair_fragmented_sentences(words)
    turns = build_turns(words)
    turns, echo_collapsed = collapse_echo_turns(turns)
    rescored = absorbed = 0
    if rescore and len(turns) > 1:
        from . import diarize

        clusters = {s["speaker"] for s in diarization["raw_segments"]}
        if centroids is None and len(clusters) > 1:
            centroids = diarize.build_cluster_centroids(waveform, diarization["raw_segments"])
        rescored = rescore_uncertain_turns(turns, waveform, centroids)
        if rescored:
            turns = _rebuild_turns(words)
        absorbed = absorb_sandwiched_turns(turns, waveform, centroids)
        if absorbed:
            turns = _rebuild_turns(words)
        # The embedding passes above can re-scatter a repaired sentence;
        # linguistic structure gets the final say over mid-sentence words.
        late_repairs = repair_fragmented_sentences(words)
        if late_repairs:
            sentences_repaired += late_repairs
            turns = _rebuild_turns(words)
    for index, turn in enumerate(turns):
        turn["turn_index"] = index
    similarity: dict[str, float] = {}
    if centroids is not None:
        from . import diarize

        similarity = diarize.centroid_similarity(centroids)
    return {"turns": turns, "echo_collapsed": echo_collapsed, "rescored_turns": rescored,
            "overlap_dispute_words": disputed, "boundary_snapped_words": snapped,
            "rescored_words": words_rescored, "sentences_repaired": sentences_repaired,
            "sandwich_absorbed": absorbed, "cluster_similarity": similarity}
