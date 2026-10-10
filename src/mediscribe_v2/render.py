"""Final transcript rendering in the minute-block format.

The WebUI text parser and the exports read this exact line grammar, so the
label logic, run-condensing, and 25-word splitting must change together with
them: "[MM:00]" headers, "Label: text" lines, and "No one spoke during this
time." for empty minutes. The editor renders through the same functions and
passes its own ``merge_text`` so word provenance survives a merge.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from .common import ROLE_OPTIONS, join_text_pieces, turn_word_count_from_text

LOW_CONFIDENCE_THRESHOLD = 0.45
MAX_LINE_WORDS = 25

RenderItem = dict[str, Any]
MergeText = Callable[[list[RenderItem]], str]


def final_turn_label(turn: dict[str, Any], low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
                     role_options: tuple[str, ...] | list[str] = ROLE_OPTIONS) -> str:
    final_role = str(turn.get("final_role", turn.get("assigned_role", "Unknown")))
    final_confidence = float(turn.get("final_role_confidence", turn.get("role_confidence", 0.0)))
    if final_role not in role_options or final_role == "Unknown":
        return "Unknown"
    if turn.get("refined_by_llm") and turn.get("mark_unknown"):
        return f"[Unknown] {final_role}"
    if final_confidence < low_confidence_threshold:
        return "Unknown"
    return final_role


def has_obvious_render_boundary(text: str) -> bool:
    return bool(re.search(r"[,\.!?]", text))


def can_continue_render_run(text: str) -> bool:
    return not has_obvious_render_boundary(text) or turn_word_count_from_text(text) < 5


def _join_run_text(run: list[RenderItem]) -> str:
    return join_text_pieces(str(item["text"]) for item in run)


def condense_same_label_render_items(items: list[RenderItem], *,
                                     merge_text: MergeText | None = None) -> list[RenderItem]:
    """Merge consecutive same-label items until one of them ends a sentence.

    A run keeps growing while the next item has the same label and either has
    no punctuation boundary or is shorter than five words; an item that closes
    a boundary ends the run after joining it. ``merge_text`` decides how a
    run's texts are joined (the editor passes a provenance-aware joiner).
    """
    merge = merge_text or _join_run_text
    condensed: list[RenderItem] = []
    run: list[RenderItem] = []

    def flush_run() -> None:
        nonlocal run
        if not run:
            return
        if len(run) == 1:
            condensed.append(run[0])
        else:
            condensed.append({"label": run[0]["label"], "text": merge(run)})
        run = []

    for item in items:
        if run:
            if run[0]["label"] == item["label"] and can_continue_render_run(item["text"]):
                run.append(item)
                if has_obvious_render_boundary(item["text"]):
                    flush_run()
                continue
            flush_run()
        if not has_obvious_render_boundary(item["text"]):
            run.append(item)
            continue
        condensed.append(item)
    flush_run()
    return condensed


def split_long_render_items_on_periods(items: list[RenderItem], *,
                                       max_words: int = MAX_LINE_WORDS) -> list[RenderItem]:
    """Break items over ``max_words`` into sentence-aligned chunks."""
    split_items: list[RenderItem] = []
    for item in items:
        text = item["text"].strip()
        if turn_word_count_from_text(text) <= max_words or "." not in text:
            split_items.append(item)
            continue
        sentences = [s.strip() for s in re.split(r"(?<=\.)\s+", text) if s.strip()]
        if len(sentences) <= 1:
            split_items.append(item)
            continue
        chunk: list[str] = []
        chunk_words = 0
        for sentence in sentences:
            sentence_words = turn_word_count_from_text(sentence)
            if chunk and chunk_words + sentence_words > max_words:
                split_items.append({"label": item["label"], "text": " ".join(chunk).strip()})
                chunk = [sentence]
                chunk_words = sentence_words
            else:
                chunk.append(sentence)
                chunk_words += sentence_words
        if chunk:
            split_items.append({"label": item["label"], "text": " ".join(chunk).strip()})
    return split_items


def render_block_items(items: list[RenderItem], *, merge_text: MergeText | None = None) -> list[RenderItem]:
    """The lines of one block: condense runs, split long lines, condense the
    short tails the split may have left next to a same-label item."""
    condensed = condense_same_label_render_items(items, merge_text=merge_text)
    return condense_same_label_render_items(split_long_render_items_on_periods(condensed),
                                            merge_text=merge_text)


def group_turns_by_minute(turns: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    blocks: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for turn in turns:  # turns are strictly time-ordered; no clamping needed
        blocks[int(float(turn["start_sec"]) // 60)].append(turn)
    return blocks


def render_final_transcript(turns: list[dict[str, Any]], final_txt_path: Path, *,
                            low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
                            role_options: tuple[str, ...] | list[str] = ROLE_OPTIONS) -> None:
    turns = [t for t in turns if not t.get("suspected_non_speech")]
    if not turns:
        final_txt_path.write_text("", encoding="utf-8")
        return
    blocks = group_turns_by_minute(turns)
    start_minute = int(min(float(t["start_sec"]) for t in turns) // 60)
    end_minute = int(max(float(t["end_sec"]) for t in turns) // 60)
    lines: list[str] = []
    for minute in range(start_minute, end_minute + 1):
        lines.append("")
        lines.append(f"[{minute:02d}:00]")
        block_turns = blocks.get(minute, [])
        if not block_turns:
            lines.append("No one spoke during this time.")
            continue
        items = [{"label": final_turn_label(t, low_confidence_threshold, role_options),
                  "text": str(t["text"]).strip()}
                 for t in block_turns if str(t.get("text", "")).strip()]
        for item in render_block_items(items):
            lines.append(f"{item['label']}: {item['text']}")
    final_txt_path.write_text("\n".join(lines), encoding="utf-8")
