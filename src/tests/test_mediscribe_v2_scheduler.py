"""The shared transcript block, the two-lane scheduler, and the resident worker protocol."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

SRC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC_ROOT))

from mediscribe_v2 import pipeline, roles, scheduler  # noqa: E402


def make_turn(spk: str, role: str, sentences: list[str], t0: float) -> tuple[dict, float]:
    words = []
    t = t0
    for sentence in sentences:
        for w in sentence.split():
            words.append({"text": w, "start_sec": round(t, 2), "end_sec": round(t + 0.3, 2),
                          "speaker": spk, "speaker_confidence": 0.9, "agreement": "agree"})
            t += 0.35
        t += 0.2
    turn = {"speaker": spk, "raw_speaker": spk, "final_role": role, "final_role_confidence": 1.0,
            "assigned_role": role, "words": words, "text": " ".join(sentences),
            "start_sec": words[0]["start_sec"], "end_sec": words[-1]["end_sec"],
            "turn_word_count": len(words), "word_count": len(words)}
    return turn, t + 0.6


def make_transcript(spec: list[tuple[str, str, list[str]]]) -> list[dict]:
    turns = []
    t = 0.0
    for spk, role, sentences in spec:
        turn, t = make_turn(spk, role, sentences, t)
        turns.append(turn)
    for i, turn in enumerate(turns):
        turn["turn_index"] = i
    return turns


CONSULT = [
    ("A", "Clinician", ["Hi, come on in.", "Sorry about the wait."]),
    ("B", "Patient", ["No problem."]),
    ("A", "Clinician", ["So what brings you in today?"]),
    ("B", "Patient", ["I've had this cough for three weeks.", "Any fever with it?"]),   # b is clinician's
    ("A", "Clinician", ["Maybe a low fever at first.", "Any blood when you cough?"]),   # a is patient's
    ("B", "Patient", ["No blood."]),
    ("A", "Clinician", ["Let me listen to your chest."]),
    ("B", "Patient", ["Okay."]),
    ("A", "Clinician", ["I'd like a chest x-ray today."]),
    ("B", "Patient", ["Thank you doctor.", "Where did I park?"]),
]


class TranscriptBlockTests(unittest.TestCase):
    def test_sentence_letters_only_for_multi_sentence_turns(self) -> None:
        turns = make_transcript(CONSULT[:2])
        block = roles.transcript_block(turns)
        self.assertIn("A: (a) Hi, come on in. (b) Sorry about the wait.", block)
        self.assertIn("B: No problem.", block)
        self.assertNotIn("(a) No problem", block)

    def test_structure_prompt_starts_with_shared_block(self) -> None:
        turns = make_transcript(CONSULT)
        block = roles.transcript_block(turns)
        prompt = roles.build_structure_prompt(turns, block=block)
        self.assertIn(block, prompt)
        self.assertLess(prompt.index(block), 200)

    def test_sentence_split_on_long_pause_without_punctuation(self) -> None:
        turn, _ = make_turn("A", "Clinician", ["okay so"], 0.0)
        turn["words"].append({"text": "then", "start_sec": 5.0, "end_sec": 5.3})
        labels = [s["label"] for s in roles.turn_sentences(turn)]
        self.assertEqual(labels, ["a", "b"])


class SchedulerTests(unittest.TestCase):
    def _args(self, root: Path) -> argparse.Namespace:
        return pipeline.parse_args([str(root / "x.wav"), "--intermediate-root", str(root / "int"),
                                    "--output-root", str(root / "out"), "--llm-concurrency", "2"])

    def test_audio_lane_overlaps_llm_lane_and_models_stay(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            args = self._args(root)
            events: list[dict] = []
            lock = threading.Lock()
            timeline: list[tuple[str, str, float]] = []

            def emit(event):
                with lock:
                    events.append(event)

            def fake_audio(a, input_audio, device, emit_fn, *, job_id=None, resume=None):
                timeline.append(("audio_start", input_audio.stem, time.monotonic()))
                time.sleep(0.05)
                ctx = pipeline.new_context(a, input_audio, job_id)
                timeline.append(("audio_end", input_audio.stem, time.monotonic()))
                return ctx

            def fake_llm(a, ctx, emit_fn):
                timeline.append(("llm_start", ctx.base_name, time.monotonic()))
                time.sleep(0.15)
                timeline.append(("llm_end", ctx.base_name, time.monotonic()))
                return "ok"

            with mock.patch.object(pipeline, "run_audio_stages", side_effect=fake_audio), \
                    mock.patch.object(pipeline, "run_llm_stages", side_effect=fake_llm):
                files = [root / f"{n}.wav" for n in ("a", "b", "c")]
                results = scheduler.run_batch(args, files, "cpu", emit=emit)
            self.assertEqual(results, {"a": "ok", "b": "ok", "c": "ok"})
            by = {(k, n): t for k, n, t in timeline}
            # b's audio started before a's LLM stage finished: the lanes overlap
            self.assertLess(by[("audio_start", "b")], by[("llm_end", "a")])
            kinds = [e["event"] for e in events]
            self.assertEqual(kinds.count("file_done"), 3)
            self.assertIn("lane", kinds)

    def test_failed_file_does_not_stop_the_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            args = self._args(root)
            events: list[dict] = []

            def fake_audio(a, input_audio, device, emit_fn, *, job_id=None, resume=None):
                if input_audio.stem == "bad":
                    raise RuntimeError("decode exploded")
                return pipeline.new_context(a, input_audio, job_id)

            with mock.patch.object(pipeline, "run_audio_stages", side_effect=fake_audio), \
                    mock.patch.object(pipeline, "run_llm_stages", return_value="ok"):
                results = scheduler.run_batch(args, [root / "bad.wav", root / "good.wav"], "cpu",
                                              emit=events.append)
            self.assertEqual(results, {"bad": "failed", "good": "ok"})
            failed = next(e for e in events if e["event"] == "file_failed")
            self.assertIn("decode exploded", failed["error"])
            state = json.loads((root / "int" / "bad" / "bad_pipeline_state.json").read_text())
            self.assertEqual(state["state"], "failed")


class WorkerProtocolTests(unittest.TestCase):
    def test_worker_reports_ready_and_shuts_down(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("pipeline env not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            process = subprocess.Popen(
                [sys.executable, "-u", str(SRC_ROOT / "worker.py"), "--intermediate-root", str(root / "i"),
                 "--output-root", str(root / "o"), "--device", "cpu"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            assert process.stdin and process.stdout
            events = []
            process.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
            process.stdin.flush()
            for line in process.stdout:
                if line.startswith("@@EVENT "):
                    events.append(json.loads(line[len("@@EVENT "):]))
            process.wait(timeout=60)
        kinds = [e["event"] for e in events]
        self.assertEqual(kinds[0], "worker_ready")
        self.assertEqual(kinds[-1], "worker_exit")
        self.assertEqual(events[-1]["reason"], "shutdown")


if __name__ == "__main__":
    unittest.main()
