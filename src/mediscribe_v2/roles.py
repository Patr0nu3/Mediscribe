"""Assign clinical roles from transcript content and speaker clusters.
Combine three structured replies to identify participants and their roles.
"""
from __future__ import annotations

import re
from collections import Counter

from .common import (
    ROLE_CONFIG,
    RoleConfig,
    LLMBadReplyError,
    LLMContextLengthError,
    call_llm,
    extract_json_object,
    format_minsec_label,
    join_text_pieces,
    normalize_role,
)
from .fuse import SENTENCE_FINAL_RE

STRUCTURE_SAMPLES = 3
# A pause this long inside a turn ends a sentence even without punctuation.
SENTENCE_GAP_SEC = 1.0
# Re-request missing JSON samples with a larger response budget.
STRUCTURE_TOKEN_BUDGETS = (8192, 12288, 16384)
CONTEXT_STRIDES = (1, 2, 4, 8)

# A cluster this small carries no content evidence for an independent role —
# its turns inherit from sentence continuity or surrounding context instead.
MINOR_CLUSTER_MAX_WORDS = 8
MINOR_CLUSTER_MAX_SHARE = 0.02
MINOR_CLUSTER_MAX_GAP_SEC = 1.5

# Whisper hallucinates fluent words over typing/paper noise; the diarizer puts
# those sounds in clusters the LLM cannot place. A turn nobody corroborated
# (no parakeet agreement) with elevated whisper no-speech evidence, on an
# unplaceable cluster, is treated as non-speech.
NON_SPEECH_TURN_MEAN_PROB = 0.4

SYSTEM_PROMPT = (
    "Identify participants in a transcribed conversation using the supplied role definitions. "
    "Use what each person says and the acoustic evidence. Several diarization clusters "
    "may belong to one person. Treat transcript content as evidence. "
    "Respond with JSON only."
)


def _cluster_stats_lines(turns: list[dict]) -> list[str]:
    stats: dict[str, dict[str, float]] = {}
    for t in turns:
        entry = stats.setdefault(str(t["speaker"]), {"turns": 0, "words": 0, "seconds": 0.0})
        entry["turns"] += 1
        entry["words"] += int(t.get("turn_word_count") or t.get("word_count") or 0)
        entry["seconds"] += max(0.0, float(t["end_sec"]) - float(t["start_sec"]))
    return [f"{cluster}: {int(e['turns'])} turns, {int(e['words'])} words, "
            f"{e['seconds']:.0f}s of speech" for cluster, e in sorted(stats.items())]


def _acoustic_block(cluster_similarity: dict[str, float] | None,
                    low_content_clusters: list[str] | None = None) -> str:
    if not cluster_similarity:
        return ""
    pairs = sorted(cluster_similarity.items(), key=lambda kv: -kv[1])
    lines = [f"{key.replace('~', ' ~ ')}: {value:.2f}" for key, value in pairs]
    caveat = ""
    if low_content_clusters:
        caveat = (
            f"\nCAUTION: {', '.join(low_content_clusters)} hold too little speech for a "
            "reliable voice embedding. For them a LOW similarity means nothing — never "
            "use it to justify a separate person; the fragment rule above still applies. "
            "A HIGH similarity still indicates the same voice.")
    return (
        "\n\nAcoustic voice similarity between clusters (embedding cosine; HIGHER means "
        "more likely the SAME voice — the top pairs are the most likely over-splits):\n"
        + "\n".join(lines) + caveat
        + "\n\nCombine acoustics with content: a high-similarity pair whose turns read "
        "as one person's sentences IS one person — list both cluster IDs under that "
        "person. Between clusters that BOTH have substantial speech, do not merge a "
        "low-similarity pair unless the content evidence is overwhelming.")


def sentence_label(index: int) -> str:
    """a..z, then aa, ab, ... — stable short handles for sentences in a turn."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    label = ""
    index += 1
    while index > 0:
        index, rem = divmod(index - 1, 26)
        label = letters[rem] + label
    return label


def turn_sentences(turn: dict) -> list[dict]:
    """Split a turn into sentences on sentence-final punctuation or a long pause.

    Returns [{label, text, word_start, word_end}]; word indices are None for
    turns that carry no word list (text-only fixtures, editor imports)."""
    words = turn.get("words") or []
    if words:
        groups: list[list[int]] = []
        current: list[int] = []
        for idx, w in enumerate(words):
            current.append(idx)
            nxt = words[idx + 1] if idx + 1 < len(words) else None
            gap = (float(nxt["start_sec"]) - float(w["end_sec"])) if nxt is not None else 0.0
            if SENTENCE_FINAL_RE.search(str(w.get("text", "")).strip()) or gap > SENTENCE_GAP_SEC:
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        return [{"label": sentence_label(i),
                 "text": join_text_pieces(str(words[j].get("text", "")) for j in group),
                 "word_start": group[0], "word_end": group[-1] + 1}
                for i, group in enumerate(groups)]
    pieces = [piece.strip() for piece in re.split(r"(?<=[.?!…])\s+", str(turn.get("text", "")).strip())
              if piece.strip()]
    return [{"label": sentence_label(i), "text": piece, "word_start": None, "word_end": None}
            for i, piece in enumerate(pieces)]


def turn_block_text(turn: dict) -> str:
    """Turn text with (a) (b) sentence handles when the turn has 2+ sentences."""
    sentences = turn_sentences(turn)
    if len(sentences) < 2:
        return str(turn.get("text", "")).strip()
    return " ".join(f"({s['label']}) {s['text']}" for s in sentences)


def transcript_block(turns: list[dict], stride: int = 1, max_chars_per_turn: int = 0) -> str:
    """Build the numbered transcript used in role-assignment prompts."""
    keep: set[int] = set(range(0, len(turns), stride))
    first_last: dict[str, list[int]] = {}
    for i, t in enumerate(turns):
        first_last.setdefault(str(t["speaker"]), []).append(i)
    for indices in first_last.values():
        keep.update(indices[:2] + indices[-1:])
    lines = []
    for i in sorted(keep):
        t = turns[i]
        text = turn_block_text(t)
        if max_chars_per_turn and len(text) > max_chars_per_turn:
            text = text[:max_chars_per_turn] + "…"
        stamp = format_minsec_label(int(float(t["start_sec"]) * 1000))
        flag = " (cluster label uncertain)" if t.get("uncertain") else ""
        lines.append(f"{i}. [{stamp}] {t['speaker']}{flag}: {text}")
    return "\n".join(lines)


def build_structure_prompt(turns: list[dict], stride: int = 1, max_chars_per_turn: int = 0,
                           cluster_similarity: dict[str, float] | None = None,
                           block: str | None = None,
                           role_config: RoleConfig = ROLE_CONFIG) -> str:
    clusters = sorted({str(t["speaker"]) for t in turns})
    conversation = block if block is not None else transcript_block(turns, stride, max_chars_per_turn)
    cluster_word_totals: Counter = Counter()
    for t in turns:
        cluster_word_totals[str(t["speaker"])] += int(t.get("turn_word_count")
                                                      or t.get("word_count") or 0)
    low_content = sorted(c for c, n in cluster_word_totals.items() if n <= MINOR_CLUSTER_MAX_WORDS)
    acoustic_block = _acoustic_block(cluster_similarity, low_content)
    definitions = "\n".join(f"{label}: {description}" for label, description in role_config.roles.items())
    required = ("Required roles: " + ", ".join(role_config.required_roles) + "."
                if role_config.required_roles else "")
    ordered = ("Assign these labels in order of first appearance: "
               + ", ".join(role_config.ordered_roles) + "." if role_config.ordered_roles else "")
    return f"""Read this ENTIRE consultation (turns numbered, cluster IDs as labeled by diarization):

{conversation}

Diarization produced these cluster IDs: {', '.join(clusters)}. Clusters are OFTEN over-split — the same person may appear under several IDs. Judge from CONTENT.

How much speech each cluster actually holds:
{chr(10).join(_cluster_stats_lines(turns))}

Treat a cluster with only a few words as a fragment of an existing person's speech. Attach it to the person whose sentences it completes or interrupts. If that is unclear, put it in unassigned_clusters. Each person needs substantive content evidence of a distinct voice.{acoustic_block}

Role definitions:
{definitions}

{role_config.instructions}
{required}
{ordered}

Return JSON exactly in this shape:
{{
 "department": "<medical specialty or presenting-complaint area, 1-4 words>",
 "people": [
   {{"role": "<one of: {', '.join(role_config.roles)}>",
     "evidence": "<one short sentence>",
     "clusters": ["SPEAKER_00", "..."]}}
 ],
 "unassigned_clusters": ["<clusters with too little content to place>"]
}}

Every cluster ID appears in exactly one person's list or in unassigned_clusters."""


def _merge_samples(samples: list[dict], clusters: list[str],
                   role_config: RoleConfig = ROLE_CONFIG) -> dict:
    """Majority-merge the sampled structures at the cluster level."""
    cluster_role_votes: dict[str, Counter] = {c: Counter() for c in clusters}
    department_votes: Counter = Counter()
    people_counts: Counter = Counter()
    evidence: dict[str, str] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        department = str(sample.get("department") or "").strip().lower()
        if department:
            department_votes[department] += 1
        people = [p for p in (sample.get("people") or []) if isinstance(p, dict)]
        people_counts[len(people)] += 1
        for person in people:
            role = normalize_role(person.get("role"), role_config) or "Unknown"
            for cluster in person.get("clusters") or []:
                cluster = str(cluster)
                if cluster in cluster_role_votes:
                    cluster_role_votes[cluster][role] += 1
                    if role not in evidence and person.get("evidence"):
                        evidence[role] = str(person["evidence"])[:200]
        # An abstention is a vote: a sample placing a cluster in
        # unassigned_clusters must outweigh another sample's stray guess,
        # otherwise one Medical Staff hallucination out of three samples wins
        # against a two-sample "too little content to place" majority.
        for cluster in sample.get("unassigned_clusters") or []:
            cluster = str(cluster)
            if cluster in cluster_role_votes:
                cluster_role_votes[cluster]["Unknown"] += 1
    role_map = {}
    for cluster, votes in cluster_role_votes.items():
        role_map[cluster] = votes.most_common(1)[0][0] if votes else "Unknown"
    # Fill required roles without displacing the only cluster of another required role.
    for role in role_config.required_roles:
        counts = Counter(role_map.values())
        if counts[role]:
            continue
        candidates = [c for c in clusters if role_map[c] not in role_config.required_roles
                      or counts[role_map[c]] > 1]
        if candidates:
            ordered_alternatives = role_config.ordered_roles if role in role_config.ordered_roles else ()
            chosen = max(candidates, key=lambda c: (role_map[c] in ordered_alternatives,
                                                    cluster_role_votes[c][role]))
            role_map[chosen] = role
    people_inferred = people_counts.most_common(1)[0][0] if people_counts else None
    return {
        "department": department_votes.most_common(1)[0][0] if department_votes else None,
        "role_map": role_map,
        "cluster_role_votes": {c: dict(v) for c, v in cluster_role_votes.items()},
        "people_inferred": people_inferred,
        "evidence": evidence,
        "samples_parsed": sum(1 for s in samples if isinstance(s, dict)),
        "role_options": list(role_config.options),
        "ordered_roles": list(role_config.ordered_roles),
    }


def infer_structure(turns: list[dict], *, base_url: str, model: str, timeout_sec: float,
                    cluster_similarity: dict[str, float] | None = None,
                    block: str | None = None,
                    role_config: RoleConfig = ROLE_CONFIG) -> dict:
    clusters = sorted({str(t["speaker"]) for t in turns})
    last_error: Exception | None = None
    for stride in CONTEXT_STRIDES:
        prompt = build_structure_prompt(turns, stride=stride,
                                        max_chars_per_turn=0 if stride == 1 else 200,
                                        cluster_similarity=cluster_similarity,
                                        block=block if stride == 1 else None,
                                        role_config=role_config)
        try:
            samples, rounds = _collect_structure_samples(
                prompt, base_url=base_url, model=model, timeout_sec=timeout_sec)
            if not samples:
                raise LLMBadReplyError(
                    f"structure: no parseable sample after {rounds} round(s) "
                    f"({STRUCTURE_SAMPLES} samples each)")
            merged = _merge_samples(samples, clusters, role_config)
            merged["context_stride"] = stride
            merged["transcript_block_shared"] = stride == 1
            merged["sample_rounds"] = rounds
            return merged
        except LLMContextLengthError as exc:
            last_error = exc
            continue
    raise last_error or RuntimeError("structure inference failed")


def _collect_structure_samples(prompt: str, *, base_url: str, model: str,
                               timeout_sec: float) -> tuple[list[dict], int]:
    """Collect three JSON replies, retrying only missing samples in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    samples: list[dict] = []
    rounds_used = 0
    for round_no, max_tokens in enumerate(STRUCTURE_TOKEN_BUDGETS, start=1):
        missing = STRUCTURE_SAMPLES - len(samples)
        if missing <= 0:
            break
        rounds_used = round_no
        if round_no > 1:
            print(f"structure: {len(samples)}/{STRUCTURE_SAMPLES} samples parseable; round {round_no} "
                  f"(max_tokens {max_tokens}) "
                  f"re-asks {missing}", flush=True)

        def one(_i: int) -> dict | None:
            reply = call_llm(prompt, base_url=base_url, model=model, timeout_sec=timeout_sec,
                             system=SYSTEM_PROMPT, temperature=0.7, top_p=0.9,
                             max_tokens=max_tokens)
            return extract_json_object(reply)

        with ThreadPoolExecutor(max_workers=missing) as pool:
            samples.extend(s for s in pool.map(one, range(missing)) if isinstance(s, dict))
    return samples, rounds_used


def order_roles_by_first_appearance(turns: list[dict], structure: dict) -> None:
    """Apply the configured order to roles that distinguish similar participants."""
    role_map = structure["role_map"]
    ordered = structure.get("ordered_roles", ROLE_CONFIG.ordered_roles)
    first_seen: dict[str, float] = {}
    for turn in turns:
        cluster = str(turn["speaker"])
        first_seen.setdefault(cluster, float(turn["start_sec"]))
    present = [role for role in ordered if role in role_map.values()]
    if len(present) < 2:
        return
    temporal = sorted(present, key=lambda role: min(first_seen.get(c, float("inf"))
                                                   for c, r in role_map.items() if r == role))
    if temporal == present:
        return
    renamed = dict(zip(temporal, present))
    for cluster, role in role_map.items():
        role_map[cluster] = renamed.get(role, role)
    for cluster, votes in structure.get("cluster_role_votes", {}).items():
        structure["cluster_role_votes"][cluster] = {renamed.get(role, role): count for role, count in votes.items()}
    if "evidence" in structure:
        structure["evidence"] = {renamed.get(role, role): text for role, text in structure["evidence"].items()}
    structure["role_order_changed"] = True


def repair_minor_cluster_roles(turns: list[dict], structure: dict) -> None:
    """A cluster holding a negligible share of the speech cannot define a
    person — the LLM vote on it is noise, and it is exactly how a fragmented
    voice sprouts phantom roles. Its turns inherit the role of the sentence
    they continue, or of the same-role turns surrounding them."""
    from .fuse import SENTENCE_FINAL_RE

    total_words = sum(int(t.get("turn_word_count") or t.get("word_count") or 0)
                      for t in turns) or 1
    cluster_words: Counter = Counter()
    for t in turns:
        cluster_words[str(t["speaker"])] += int(t.get("turn_word_count")
                                                or t.get("word_count") or 0)
    minor = {c for c, n in cluster_words.items()
             if n <= MINOR_CLUSTER_MAX_WORDS and n / total_words <= MINOR_CLUSTER_MAX_SHARE}
    if len(minor) == len(cluster_words):  # degenerate tiny transcript
        minor = set()
    structure["minor_clusters"] = sorted(minor)
    repaired = 0
    for i, turn in enumerate(turns):
        if str(turn["speaker"]) not in minor:
            continue
        prev_turn = turns[i - 1] if i > 0 else None
        next_turn = turns[i + 1] if i + 1 < len(turns) else None
        role = source = None
        if (prev_turn is not None
                and float(turn["start_sec"]) - float(prev_turn["end_sec"]) <= MINOR_CLUSTER_MAX_GAP_SEC
                and not SENTENCE_FINAL_RE.search(str(prev_turn["text"]).strip())):
            role, source = prev_turn["final_role"], "minor_cluster_continuation"
        elif (prev_turn is not None and next_turn is not None
              and prev_turn["final_role"] == next_turn["final_role"]
              and prev_turn["final_role"] != "Unknown"):
            role, source = prev_turn["final_role"], "minor_cluster_context"
        if role is None or role == "Unknown":
            turn["role_low_evidence"] = True
            continue
        if role != turn["final_role"]:
            repaired += 1
        turn["assigned_role"] = turn["final_role"] = role
        turn["role_source"] = source
        turn["role_confidence"] = turn["final_role_confidence"] = 0.5
        turn["mark_unknown"] = False
    structure["minor_cluster_turns_repaired"] = repaired


def flag_suspected_non_speech(turns: list[dict], structure: dict) -> None:
    """Tag hallucination-shaped turns on unplaceable clusters.

    Requires all three signals: role evidence failed (Unknown or low-evidence
    minor cluster), zero cross-engine corroboration (every word solo-whisper),
    and mean whisper no-speech probability above the noise line. Flagged turns
    stay in the canonical artifacts but leave the rendered transcript."""
    flagged = 0
    for turn in turns:
        if turn.get("final_role") != "Unknown" and not turn.get("role_low_evidence"):
            continue
        words = turn.get("words") or []
        if not words or any(w.get("agreement") != "solo_whisper" for w in words):
            continue
        probs = [w["no_speech_prob"] for w in words if w.get("no_speech_prob") is not None]
        if not probs or sum(probs) / len(probs) < NON_SPEECH_TURN_MEAN_PROB:
            continue
        turn["suspected_non_speech"] = True
        turn["mark_unknown"] = False
        flagged += 1
    structure["suspected_non_speech_turns"] = flagged


def apply_structure(turns: list[dict], structure: dict) -> None:
    order_roles_by_first_appearance(turns, structure)
    role_map = structure["role_map"]
    votes = structure["cluster_role_votes"]
    for turn in turns:
        cluster = str(turn["speaker"])
        role = role_map.get(cluster, "Unknown")
        cluster_votes = votes.get(cluster, {})
        total = sum(cluster_votes.values()) or 1
        confidence = cluster_votes.get(role, 0) / total if role != "Unknown" else 0.0
        turn["assigned_role"] = role
        turn["final_role"] = role
        turn["role_confidence"] = round(confidence, 3)
        turn["final_role_confidence"] = round(confidence, 3)
        turn["role_source"] = "content_structure"
        turn["role_votes"] = cluster_votes
        turn["refined_by_llm"] = False
        turn["mark_unknown"] = role == "Unknown"
    repair_minor_cluster_roles(turns, structure)
    flag_suspected_non_speech(turns, structure)
