"""Unit tests for the mediscribe_v2 pipeline stages."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mediscribe_v2 import asr, common, fuse, roles  # noqa: E402
from mediscribe_v2.pipeline import parse_args  # noqa: E402
from mediscribe_v2.render import final_turn_label  # noqa: E402


def w(text, start, end, engine="whisper", **extra):
    base = {"text": text, "norm": text.lower().strip(".,!?").replace(" ", ""),
            "start_sec": start, "end_sec": end, "engine": engine,
            "asr_prob": 0.9, "no_speech_prob": 0.1, "segment_index": 0}
    base.update(extra)
    return base


class MergeTests(unittest.TestCase):
    def test_agreement_and_solo_recovery(self) -> None:
        wa = [w("Hello", 1.0, 1.3), w("there.", 1.3, 1.6), w("Bye.", 9.0, 9.3)]
        wb = [w("hello", 1.05, 1.32, "parakeet"), w("there", 1.32, 1.62, "parakeet"),
              w("I", 4.0, 4.2, "parakeet"), w("missed", 4.2, 4.5, "parakeet"),
              w("this", 4.5, 4.8, "parakeet"), w("bye", 9.05, 9.35, "parakeet")]
        merged, stats = asr.merge_streams(wa, wb, [(0.8, 5.2), (8.8, 9.6)])
        self.assertEqual(stats["agree"], 3)
        self.assertEqual(stats["solo_parakeet_kept"], 3)
        self.assertEqual([x["text"] for x in merged],
                         ["Hello", "there.", "I", "missed", "this", "Bye."])

    def test_chunk_windows_tile_without_double_coverage(self) -> None:
        # The head-only trim re-emitted overlap_sec/2 of speech every hop; the
        # kept windows must tile the file exactly instead.
        windows = asr.chunk_keep_windows(300 * asr.ANALYSIS_SR, chunk_sec=30.0, overlap_sec=5.0)
        self.assertEqual(windows[0][1], 0.0)
        self.assertEqual(windows[-1][2], float("inf"))
        for (_o1, _f1, until), (_o2, keep_from, _u2) in zip(windows, windows[1:]):
            self.assertAlmostEqual(until, keep_from, places=6)

    def test_chunk_echo_of_whisper_word_dropped(self) -> None:
        # Parakeet re-decodes the overlap and repeats words whisper already
        # placed; those echoes must not reach the transcript.
        wa = [w("I'm", 1.0, 1.2), w("going", 1.2, 1.5), w("to", 1.5, 1.7),
              w("the", 1.7, 1.9), w("office.", 1.9, 2.3)]
        wb = [w(x, s, e, "parakeet") for x, s, e in
              [("i'm", 1.02, 1.22), ("going", 1.22, 1.52), ("to", 1.52, 1.72),
               ("the", 1.72, 1.92), ("office", 1.92, 2.32),
               ("going", 1.22, 1.52), ("to", 1.52, 1.72), ("the", 1.72, 1.92)]]
        merged, stats = asr.merge_streams(wa, wb, [(0.5, 3.0)])
        self.assertEqual([x["text"] for x in merged],
                         ["I'm", "going", "to", "the", "office."])
        self.assertEqual(stats["solo_parakeet_echo_dropped"], 3)

    def test_stray_parakeet_token_outside_speech_dropped(self) -> None:
        wa = [w("Hello.", 1.0, 1.4)]
        wb = [w("hello", 1.05, 1.35, "parakeet"), w("thanks", 20.0, 20.3, "parakeet")]
        merged, stats = asr.merge_streams(wa, wb, [(0.8, 2.0)])
        self.assertEqual(stats["solo_parakeet_dropped"], 1)
        self.assertEqual(len(merged), 1)


class GuardTests(unittest.TestCase):
    def test_non_speech_solo_tokens_dropped_and_marked(self) -> None:
        merged = [dict(w("Hello.", 1.0, 1.4), agreement="agree"),
                  dict(w("Thank", 10.0, 10.2, no_speech_prob=0.9), agreement="solo_whisper"),
                  dict(w("you.", 10.2, 10.4, no_speech_prob=0.9), agreement="solo_whisper")]
        kept, dropped, markers, stats = asr.apply_guard(merged, [(0.5, 2.0)], 15.0)
        self.assertEqual(len(kept), 1)
        self.assertEqual(stats["dropped_non_speech"], 2)
        self.assertTrue(markers and markers[0]["kind"] == "non_speech")

    def test_in_speech_hallucination_shaped_solo_dropped(self) -> None:
        # Silero false-positived on typing noise: whisper-only words with high
        # no-speech probability AND poor confidence are dropped even in-speech.
        merged = [dict(w("Hello.", 1.0, 1.4), agreement="solo_whisper"),
                  dict(w("Thank", 1.6, 1.8, no_speech_prob=0.9, asr_prob=0.1),
                       agreement="solo_whisper")]
        kept, dropped, _markers, stats = asr.apply_guard(merged, [(0.5, 2.0)], 5.0)
        self.assertEqual([x["text"] for x in kept], ["Hello."])
        self.assertEqual(stats["dropped_non_speech"], 1)
        # a confident whisper-only word in speech is untouched
        merged2 = [dict(w("stethoscope", 1.0, 1.5, no_speech_prob=0.9), agreement="solo_whisper")]
        kept2, _d, _m, _s = asr.apply_guard(merged2, [(0.5, 2.0)], 5.0)
        self.assertEqual(len(kept2), 1)


class FusionTests(unittest.TestCase):
    TIMELINE = [{"start_sec": 0.5, "end_sec": 5.5, "speaker": "SPEAKER_00"},
                {"start_sec": 8.5, "end_sec": 10.0, "speaker": "SPEAKER_01"}]

    def test_cross_speaker_repeat_is_not_collapsed(self) -> None:
        # Two people trading "Okay." is an exchange, not an ASR echo; collapsing
        # it deleted the second person's words outright.
        def turn(speaker, start, end):
            return {"speaker": speaker, "start_sec": start, "end_sec": end,
                    "word_count": 1, "words": [dict(w("Okay.", start, end), agreement="agree")]}
        same = fuse.collapse_echo_turns([turn("SPEAKER_00", 1.0, 1.4),
                                         turn("SPEAKER_00", 1.6, 2.0)])
        self.assertEqual((len(same[0]), same[1]), (1, 1))
        cross = fuse.collapse_echo_turns([turn("SPEAKER_00", 1.0, 1.4),
                                          turn("SPEAKER_01", 1.6, 2.0)])
        self.assertEqual((len(cross[0]), cross[1]), (2, 0))

    def test_overlapping_backchannel_is_a_rescore_candidate(self) -> None:
        # "Okay." said over the other speaker has no silence around it, so the
        # isolation test can never fire; its sentence shape has to carry it.
        words = [dict(w("instead.", 1.0, 1.4), agreement="agree"),
                 dict(w("Okay.", 1.41, 1.6), agreement="agree"),
                 dict(w("So", 1.61, 1.8), agreement="agree"),
                 dict(w("the", 1.81, 2.0), agreement="agree")]
        self.assertEqual(fuse.word_rescore_candidates(words), [1])
        # mid-clause "okay" (previous word did not close a sentence) stays out
        clause = [dict(w("are", 1.0, 1.2), agreement="agree"),
                  dict(w("you", 1.21, 1.4), agreement="agree"),
                  dict(w("okay?", 1.41, 1.7), agreement="agree")]
        self.assertEqual(fuse.word_rescore_candidates(clause), [])

    def test_zip_and_turns(self) -> None:
        words = [dict(w("Hello", 1.0, 1.3), agreement="agree"),
                 dict(w("there.", 1.3, 1.6), agreement="agree"),
                 dict(w("Bye.", 9.0, 9.3), agreement="agree")]
        fusion = fuse.fuse(words, {"alignment_segments": self.TIMELINE,
                                   "raw_segments": self.TIMELINE}, None, rescore=False)
        turns = fusion["turns"]
        self.assertEqual([t["speaker"] for t in turns], ["SPEAKER_00", "SPEAKER_01"])
        self.assertFalse(any(t["uncertain"] for t in turns))

    def test_gap_word_stays_labeled_but_uncertain(self) -> None:
        words = [dict(w("orphan", 7.0, 7.2), agreement="solo_whisper")]
        fusion = fuse.fuse(words, {"alignment_segments": self.TIMELINE,
                                   "raw_segments": self.TIMELINE}, None, rescore=False)
        turn = fusion["turns"][0]
        self.assertIn(turn["speaker"], ("SPEAKER_00", "SPEAKER_01"))  # never "Unknown"
        self.assertTrue(turn["uncertain"])

    def test_boundary_snap_returns_stolen_edge_word(self) -> None:
        # "tail" is SPEAKER_00's last word but its midpoint (5.1) drifts past
        # the 5.0 boundary; the real pause is after it (5.4 -> 5.6).
        timeline = [{"start_sec": 0.0, "end_sec": 5.0, "speaker": "SPEAKER_00"},
                    {"start_sec": 5.0, "end_sec": 10.0, "speaker": "SPEAKER_01"}]
        words = [dict(w("word", 4.5, 4.9), agreement="agree"),
                 dict(w("tail.", 4.8, 5.4), agreement="agree"),
                 dict(w("Hello", 5.6, 5.9), agreement="agree")]
        fusion = fuse.fuse(words, {"alignment_segments": timeline,
                                   "raw_segments": timeline}, None, rescore=False)
        self.assertEqual(words[1]["speaker"], "SPEAKER_00")
        self.assertEqual(words[1]["speaker_assignment_reason"], "boundary_snap")
        self.assertEqual(fusion["boundary_snapped_words"], 1)
        self.assertEqual([t["speaker"] for t in fusion["turns"]],
                         ["SPEAKER_00", "SPEAKER_01"])

    def test_boundary_without_pause_marks_ambiguous(self) -> None:
        timeline = [{"start_sec": 0.0, "end_sec": 5.0, "speaker": "SPEAKER_00"},
                    {"start_sec": 5.0, "end_sec": 10.0, "speaker": "SPEAKER_01"}]
        words = [dict(w("a", 4.7, 4.95), agreement="agree"),
                 dict(w("b", 4.95, 5.05), agreement="agree"),
                 dict(w("c", 5.05, 5.3), agreement="agree")]
        fusion = fuse.fuse(words, {"alignment_segments": timeline,
                                   "raw_segments": timeline}, None, rescore=False)
        self.assertEqual(fusion["boundary_snapped_words"], 0)
        self.assertTrue(words[1].get("boundary_ambiguous"))
        self.assertTrue(words[1]["uncertain"])
        self.assertFalse(words[0].get("boundary_ambiguous"))

    def test_overlap_dispute_lowers_confidence(self) -> None:
        raw = [{"start_sec": 0.0, "end_sec": 6.0, "speaker": "SPEAKER_00"},
               {"start_sec": 4.0, "end_sec": 10.0, "speaker": "SPEAKER_01"}]
        exclusive = [{"start_sec": 0.0, "end_sec": 5.0, "speaker": "SPEAKER_00"},
                     {"start_sec": 5.0, "end_sec": 10.0, "speaker": "SPEAKER_01"}]
        words = [dict(w("clear", 1.0, 1.4), agreement="agree"),
                 dict(w("contested", 4.3, 4.6), agreement="agree")]
        fusion = fuse.fuse(words, {"alignment_segments": exclusive,
                                   "raw_segments": raw}, None, rescore=False)
        self.assertEqual(fusion["overlap_dispute_words"], 1)
        self.assertTrue(words[1].get("overlap_dispute"))
        self.assertFalse(words[0].get("overlap_dispute"))
        self.assertLess(words[1]["speaker_confidence"], words[0]["speaker_confidence"])

    def test_backchannel_lexicon_loaded_and_normalized(self) -> None:
        # config/lexicons/backchannels.json is the source; entries like
        # "uh-huh"/"mm-hmm" must arrive in normalize_token form
        self.assertIn("uhhuh", fuse.BACKCHANNEL_TOKENS)
        self.assertIn("mmhmm", fuse.BACKCHANNEL_TOKENS)
        self.assertIn("yeah", fuse.BACKCHANNEL_TOKENS)
        self.assertNotIn("uh-huh", fuse.BACKCHANNEL_TOKENS)

    def test_boundary_snap_prefers_punctuation_over_larger_gap(self) -> None:
        # Acoustic-only snapping would keep "I'm" with the clinician (larger
        # pause after it); the sentence-final "?" before it must win instead.
        timeline = [{"start_sec": 0.0, "end_sec": 5.0, "speaker": "SPEAKER_00"},
                    {"start_sec": 5.0, "end_sec": 10.0, "speaker": "SPEAKER_01"}]
        words = [dict(w("doing?", 4.3, 4.75), agreement="agree"),
                 dict(w("I'm", 4.85, 5.05), agreement="agree"),
                 dict(w("good.", 5.3, 5.55), agreement="agree")]
        fusion = fuse.fuse(words, {"alignment_segments": timeline,
                                   "raw_segments": timeline}, None, rescore=False)
        self.assertEqual(words[1]["speaker"], "SPEAKER_01")
        self.assertEqual(words[1]["speaker_assignment_reason"], "boundary_snap")
        self.assertEqual(fusion["boundary_snapped_words"], 1)

    def test_sentence_continuation_folds_fragment(self) -> None:
        # "I've | had a lot of pain." split across two clusters mid-sentence:
        # the one-word fragment folds into the larger side's cluster.
        timeline = [{"start_sec": 0.0, "end_sec": 1.0, "speaker": "SPEAKER_00"},
                    {"start_sec": 1.1, "end_sec": 1.5, "speaker": "SPEAKER_01"},
                    {"start_sec": 1.6, "end_sec": 4.0, "speaker": "SPEAKER_02"}]
        words = [dict(w("I'm", 0.2, 0.4), agreement="agree"),
                 dict(w("good.", 0.4, 0.8), agreement="agree"),
                 dict(w("I've", 1.1, 1.4), agreement="agree"),
                 dict(w("had", 1.6, 1.8), agreement="agree"),
                 dict(w("a", 1.8, 1.9), agreement="agree"),
                 dict(w("lot", 1.9, 2.1), agreement="agree"),
                 dict(w("of", 2.1, 2.2), agreement="agree"),
                 dict(w("pain.", 2.2, 2.6), agreement="agree")]
        fusion = fuse.fuse(words, {"alignment_segments": timeline,
                                   "raw_segments": timeline}, None, rescore=True)
        self.assertEqual(fusion["sentences_repaired"], 1)
        self.assertEqual(words[2]["speaker"], "SPEAKER_02")
        self.assertEqual(words[2]["speaker_assignment_reason"], "sentence_repair")
        self.assertEqual([t["speaker"] for t in fusion["turns"]],
                         ["SPEAKER_00", "SPEAKER_02"])
        self.assertTrue(fusion["turns"][1]["text"].startswith("I've had"))

    def test_tiny_fragment_folds_despite_embedding_defense(self) -> None:
        # The fragment's own cluster "defends" it — but that embedding is the
        # same evidence that mis-clustered it, so a 1-word fragment must fold
        # on sentence continuity regardless.
        from mediscribe_v2 import diarize

        timeline = [{"start_sec": 0.0, "end_sec": 1.0, "speaker": "SPEAKER_00"},
                    {"start_sec": 1.1, "end_sec": 1.5, "speaker": "SPEAKER_01"},
                    {"start_sec": 1.6, "end_sec": 4.0, "speaker": "SPEAKER_02"}]
        words = [dict(w("I'm", 0.2, 0.4), agreement="agree"),
                 dict(w("good.", 0.4, 0.8), agreement="agree"),
                 dict(w("I've", 1.1, 1.4), agreement="agree"),
                 dict(w("had", 1.6, 1.8), agreement="agree"),
                 dict(w("some", 1.8, 2.0), agreement="agree"),
                 dict(w("pain.", 2.0, 2.4), agreement="agree")]
        orig_centroids, orig_rescore = diarize.build_cluster_centroids, diarize.rescore_span
        diarize.build_cluster_centroids = lambda wf, segs: {"SPEAKER_00": 1, "SPEAKER_01": 1,
                                                           "SPEAKER_02": 1}
        diarize.rescore_span = lambda wf, s, e, c: (
            {"SPEAKER_00": 0.1, "SPEAKER_01": 0.9, "SPEAKER_02": 0.1} if 1.0 <= s <= 1.5
            else {"SPEAKER_00": 0.9, "SPEAKER_01": 0.05, "SPEAKER_02": 0.05} if e <= 1.0
            else {"SPEAKER_00": 0.05, "SPEAKER_01": 0.05, "SPEAKER_02": 0.9})
        try:
            fusion = fuse.fuse(words, {"alignment_segments": timeline,
                                       "raw_segments": timeline}, None, rescore=True)
        finally:
            diarize.build_cluster_centroids = orig_centroids
            diarize.rescore_span = orig_rescore
        self.assertEqual(fusion["sentences_repaired"], 1)
        self.assertEqual(words[2]["speaker"], "SPEAKER_02")
        self.assertEqual([t["speaker"] for t in fusion["turns"]],
                         ["SPEAKER_00", "SPEAKER_02"])

    def test_word_per_turn_shatter_reunited(self) -> None:
        # "I feel like it kind of is getting better." shattered across three
        # clusters word-by-word — pairwise folding ping-pongs; the sentence
        # plurality vote must reunite it under the dominant cluster.
        timeline = [{"start_sec": 0.0, "end_sec": 4.05, "speaker": "SPEAKER_00"},
                    {"start_sec": 4.05, "end_sec": 4.45, "speaker": "SPEAKER_01"},
                    {"start_sec": 4.45, "end_sec": 4.85, "speaker": "SPEAKER_02"},
                    {"start_sec": 4.85, "end_sec": 5.25, "speaker": "SPEAKER_00"},
                    {"start_sec": 5.25, "end_sec": 9.0, "speaker": "SPEAKER_02"}]
        words = [dict(w("worsening?", 3.0, 3.5), agreement="agree"),
                 dict(w("I", 3.8, 4.0), agreement="agree"),
                 dict(w("feel", 4.1, 4.4), agreement="agree"),
                 dict(w("like", 4.5, 4.8), agreement="agree"),
                 dict(w("it", 4.9, 5.2), agreement="agree"),
                 dict(w("kind", 5.3, 5.5), agreement="agree"),
                 dict(w("of", 5.5, 5.6), agreement="agree"),
                 dict(w("is", 5.6, 5.8), agreement="agree"),
                 dict(w("getting", 5.8, 6.1), agreement="agree"),
                 dict(w("better.", 6.1, 6.4), agreement="agree")]
        fusion = fuse.fuse(words, {"alignment_segments": timeline,
                                   "raw_segments": timeline}, None, rescore=False)
        self.assertEqual(fusion["sentences_repaired"], 1)
        for word in words[1:]:
            self.assertEqual(word["speaker"], "SPEAKER_02")
        self.assertEqual([t["speaker"] for t in fusion["turns"]],
                         ["SPEAKER_00", "SPEAKER_02"])

    def test_sentence_repair_overrides_non_backchannel_word_rescore(self) -> None:
        # a mid-sentence "feel" flipped by a noisy embedding vote must yield to
        # sentence continuity; a lexicon backchannel keeps its confirmed speaker
        def wd(text, start, end, speaker, reason="timeline"):
            word = dict(w(text, start, end), agreement="agree")
            word.update({"speaker": speaker, "raw_speaker": speaker,
                         "speaker_confidence": 0.9, "uncertain": False,
                         "speaker_assignment_reason": reason})
            return word
        words = [wd("I", 1.0, 1.1, "S2"),
                 wd("feel", 1.2, 1.4, "S1", reason="word_rescore"),
                 wd("like", 1.5, 1.7, "S2"),
                 wd("it's", 1.8, 2.0, "S2"),
                 wd("getting", 2.1, 2.4, "S2"),
                 wd("better.", 2.5, 2.8, "S2"),
                 wd("Well", 3.0, 3.2, "S2"),
                 wd("yeah", 3.3, 3.5, "S0", reason="word_rescore"),
                 wd("I", 3.6, 3.7, "S2"),
                 wd("think", 3.8, 4.0, "S2"),
                 wd("so.", 4.1, 4.3, "S2")]
        repaired = fuse.repair_fragmented_sentences(words)
        self.assertEqual(repaired, 1)
        self.assertEqual(words[1]["speaker"], "S2")          # "feel" repaired
        self.assertEqual(words[1]["speaker_assignment_reason"], "sentence_repair")
        self.assertEqual(words[7]["speaker"], "S0")          # "yeah" protected

    def test_unpunctuated_handoff_left_alone(self) -> None:
        # near-even split with no punctuation = plausibly a real hand-off
        # whisper failed to punctuate; the repair must not touch it.
        timeline = [{"start_sec": 0.0, "end_sec": 2.0, "speaker": "SPEAKER_00"},
                    {"start_sec": 2.1, "end_sec": 4.0, "speaker": "SPEAKER_01"}]
        words = [dict(w("you", 1.0, 1.2), agreement="agree"),
                 dict(w("take", 1.2, 1.5), agreement="agree"),
                 dict(w("metformin", 1.5, 1.9), agreement="agree"),
                 dict(w("yes", 2.2, 2.4), agreement="agree"),
                 dict(w("every", 2.4, 2.7), agreement="agree"),
                 dict(w("morning", 2.7, 3.0), agreement="agree")]
        fusion = fuse.fuse(words, {"alignment_segments": timeline,
                                   "raw_segments": timeline}, None, rescore=False)
        self.assertEqual(fusion["sentences_repaired"], 0)
        self.assertEqual([t["speaker"] for t in fusion["turns"]],
                         ["SPEAKER_00", "SPEAKER_01"])

    def test_sandwich_turn_absorbed_without_embedding_defense(self) -> None:
        from mediscribe_v2 import diarize

        timeline = [{"start_sec": 0.0, "end_sec": 2.0, "speaker": "SPEAKER_00"},
                    {"start_sec": 2.2, "end_sec": 2.8, "speaker": "SPEAKER_01"},
                    {"start_sec": 3.0, "end_sec": 5.0, "speaker": "SPEAKER_00"}]
        words = [dict(w("So", 0.5, 0.7), agreement="agree"),
                 dict(w("tell", 0.7, 1.0), agreement="agree"),
                 dict(w("me.", 1.0, 1.3), agreement="agree"),
                 dict(w("Right.", 2.3, 2.6), agreement="agree"),
                 dict(w("about", 3.1, 3.4), agreement="agree"),
                 dict(w("your", 3.4, 3.6), agreement="agree"),
                 dict(w("pain.", 3.6, 4.0), agreement="agree")]
        orig_centroids, orig_rescore = diarize.build_cluster_centroids, diarize.rescore_span
        diarize.build_cluster_centroids = lambda wf, segs: {"SPEAKER_00": 1, "SPEAKER_01": 1}
        # margin too small for a rescore flip, and no clear defense of its own
        # cluster -> the sandwiched turn is absorbed into the surrounding one
        diarize.rescore_span = lambda wf, s, e, c: {"SPEAKER_00": 0.45, "SPEAKER_01": 0.4}
        try:
            fusion = fuse.fuse(words, {"alignment_segments": timeline,
                                       "raw_segments": timeline}, None, rescore=True)
        finally:
            diarize.build_cluster_centroids = orig_centroids
            diarize.rescore_span = orig_rescore
        self.assertEqual(fusion["sandwich_absorbed"], 1)
        self.assertEqual(words[3]["speaker"], "SPEAKER_00")
        self.assertEqual([t["speaker"] for t in fusion["turns"]], ["SPEAKER_00"])
        self.assertEqual(fusion["cluster_similarity"], {"SPEAKER_00~SPEAKER_01": 1.0})

    def test_backchannel_word_rescore_flips_speaker(self) -> None:
        from mediscribe_v2 import diarize

        timeline = [{"start_sec": 0.5, "end_sec": 5.5, "speaker": "SPEAKER_00"}]
        words = [dict(w("Symptoms", 1.0, 1.3), agreement="agree"),
                 dict(w("started", 1.3, 1.6), agreement="agree"),
                 dict(w("Yeah.", 2.0, 2.2), agreement="agree"),
                 dict(w("recently", 3.0, 3.4), agreement="agree")]
        self.assertEqual(fuse.word_rescore_candidates(words), [2])
        orig_centroids, orig_rescore = diarize.build_cluster_centroids, diarize.rescore_span
        diarize.build_cluster_centroids = lambda wf, segs: {"SPEAKER_00": 1, "SPEAKER_01": 1}
        # only the "Yeah." span (2.0-2.2) sounds like SPEAKER_01
        diarize.rescore_span = lambda wf, s, e, c: (
            {"SPEAKER_00": 0.1, "SPEAKER_01": 0.6} if 1.9 <= s and e <= 2.3
            else {"SPEAKER_00": 0.7, "SPEAKER_01": 0.1})
        try:
            fusion = fuse.fuse(words, {"alignment_segments": timeline,
                                       "raw_segments": timeline}, None, rescore=True)
        finally:
            diarize.build_cluster_centroids = orig_centroids
            diarize.rescore_span = orig_rescore
        self.assertEqual(words[2]["speaker"], "SPEAKER_01")
        self.assertEqual(words[2]["speaker_assignment_reason"], "word_rescore")
        self.assertEqual(fusion["rescored_words"], 1)
        self.assertEqual([t["speaker"] for t in fusion["turns"]],
                         ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"])

    def test_turn_rescore_keeps_word_provenance_truthful(self) -> None:
        from mediscribe_v2 import diarize

        def turn(speaker, start, end, n):
            words = [dict(w(f"w{i}", start + i * 0.2, start + i * 0.2 + 0.15), speaker=speaker,
                          raw_speaker=speaker, timeline_speaker=speaker, speaker_confidence=0.9,
                          uncertain=False, speaker_assignment_reason="timeline", agreement="agree")
                     for i in range(n)]
            return {"speaker": speaker, "raw_speaker": speaker, "start_sec": start, "end_sec": end,
                    "words": words, "turn_word_count": n, "turn_duration_sec": end - start,
                    "uncertain": False, "speaker_confidence": 0.9}
        turns = [turn("SPEAKER_00", 0.0, 2.0, 8), turn("SPEAKER_01", 2.1, 2.5, 2), turn("SPEAKER_00", 2.6, 5.0, 8)]
        orig = diarize.rescore_span
        diarize.rescore_span = lambda wf, s, e, c: {"SPEAKER_00": 0.8, "SPEAKER_01": 0.1}
        try:
            self.assertEqual(fuse.rescore_uncertain_turns(turns, None, {"SPEAKER_00": 1, "SPEAKER_01": 1}), 1)
        finally:
            diarize.rescore_span = orig
        moved = turns[1]["words"][0]
        # the words now carry the turn decision, not a stale timeline reason
        self.assertEqual((moved["speaker"], moved["speaker_assignment_reason"]), ("SPEAKER_00", "embedding_rescore"))
        self.assertEqual(moved["speaker_confidence"], turns[1]["speaker_confidence"])
        self.assertEqual(moved["timeline_speaker"], "SPEAKER_01")  # immutable provenance survives

    def test_echo_collapse(self) -> None:
        def turn(start):
            words = [dict(w("Thank", start, start + 0.1), speaker="S0"),
                     dict(w("you.", start + 0.1, start + 0.2), speaker="S0")]
            return {"speaker": "S0", "raw_speaker": "S0", "start_sec": start,
                    "end_sec": start + 0.2, "text": "Thank you.", "words": words,
                    "word_count": 2, "turn_duration_sec": 0.2}
        collapsed, n = fuse.collapse_echo_turns([turn(1.0), turn(3.0), turn(5.0)])
        self.assertEqual(len(collapsed), 1)
        self.assertEqual(n, 2)
        self.assertEqual(collapsed[0]["echo_repeats"], 3)


class StructureTests(unittest.TestCase):
    def test_majority_merge_and_constraints(self) -> None:
        merged = roles._merge_samples([
            {"department": "cardiology",
             "people": [{"role": "Clinician", "clusters": ["A"]},
                        {"role": "Patient", "clusters": ["B", "C"]}]},
            {"department": "cardiology",
             "people": [{"role": "Clinician", "clusters": ["A"]},
                        {"role": "Patient", "clusters": ["B", "C"]}]},
            {"department": "general",
             "people": [{"role": "Clinician", "clusters": ["A", "C"]},
                        {"role": "Patient", "clusters": ["B"]}]},
        ], ["A", "B", "C"])
        self.assertEqual(merged["department"], "cardiology")
        self.assertEqual(merged["role_map"], {"A": "Clinician", "B": "Patient", "C": "Patient"})
        self.assertEqual(merged["people_inferred"], 2)

    def test_centroid_similarity_pairs(self) -> None:
        import numpy as np
        from mediscribe_v2 import diarize

        a = np.array([1.0, 0.0])
        b = np.array([0.8, 0.6])  # unit norm, cos = 0.8
        self.assertEqual(diarize.centroid_similarity({"A": a, "B": b}), {"A~B": 0.8})
        self.assertEqual(diarize.centroid_similarity({"A": a}), {})
        self.assertEqual(diarize.centroid_similarity(None), {})

    def test_prompt_carries_acoustics_and_uncertainty(self) -> None:
        turns = [{"speaker": "SPEAKER_00", "start_sec": 0, "end_sec": 10,
                  "text": "What brings you in?", "turn_word_count": 4},
                 {"speaker": "SPEAKER_01", "start_sec": 11, "end_sec": 12,
                  "text": "I've", "turn_word_count": 1, "uncertain": True},
                 {"speaker": "SPEAKER_02", "start_sec": 12, "end_sec": 20,
                  "text": "had a lot of pain.", "turn_word_count": 5}]
        prompt = roles.build_structure_prompt(
            turns, cluster_similarity={"SPEAKER_01~SPEAKER_02": 0.81,
                                       "SPEAKER_00~SPEAKER_01": 0.22,
                                       "SPEAKER_00~SPEAKER_02": 0.25})
        self.assertIn("SPEAKER_01 ~ SPEAKER_02: 0.81", prompt)
        self.assertIn("(cluster label uncertain): I've", prompt)
        # the 1-word cluster's low similarity must be marked unreliable
        caution_line = prompt[prompt.index("CAUTION:"):].split("\n")[0]
        self.assertIn("SPEAKER_01", caution_line)
        # sorted most-similar first
        self.assertLess(prompt.index("SPEAKER_01 ~ SPEAKER_02"),
                        prompt.index("SPEAKER_00 ~ SPEAKER_02"))
        # no acoustic block when similarity is unavailable
        self.assertNotIn("Acoustic voice similarity",
                         roles.build_structure_prompt(turns))

    def test_minor_cluster_role_inherited_not_voted(self) -> None:
        def turn(speaker, start, end, text, words):
            return {"speaker": speaker, "raw_speaker": speaker, "start_sec": start,
                    "end_sec": end, "text": text, "turn_word_count": words, "words": []}
        turns = [turn("A", 0.0, 30.0, "Long clinician intro and history taking.", 120),
                 turn("B", 31.0, 33.0, "I was saying", 3),
                 turn("D", 33.2, 33.5, "something", 1),          # phantom fragment
                 turn("B", 33.8, 35.0, "about the pain.", 3),
                 turn("D", 35.2, 35.5, "okay", 1),               # sandwiched fragment
                 turn("B", 35.8, 37.0, "It still hurts.", 3)]
        structure = {"role_map": {"A": "Clinician", "B": "Patient", "D": "Medical Staff"},
                     "cluster_role_votes": {"A": {"Clinician": 3}, "B": {"Patient": 3},
                                            "D": {"Medical Staff": 2}}}
        roles.apply_structure(turns, structure)
        self.assertEqual(structure["minor_clusters"], ["D"])
        self.assertEqual(turns[2]["final_role"], "Patient")
        self.assertEqual(turns[2]["role_source"], "minor_cluster_continuation")
        self.assertEqual(turns[4]["final_role"], "Patient")
        self.assertEqual(turns[4]["role_source"], "minor_cluster_context")
        self.assertEqual(structure["minor_cluster_turns_repaired"], 2)
        self.assertEqual(turns[1]["final_role"], "Patient")  # majors untouched

    def test_unassigned_abstentions_outvote_stray_role(self) -> None:
        # 2 samples say "too little content to place", 1 hallucinates Medical
        # Staff — the abstention majority must win, not the single stray vote.
        merged = roles._merge_samples([
            {"people": [{"role": "Clinician", "clusters": ["A"]},
                        {"role": "Patient", "clusters": ["B"]}],
             "unassigned_clusters": ["N"]},
            {"people": [{"role": "Clinician", "clusters": ["A"]},
                        {"role": "Patient", "clusters": ["B"]}],
             "unassigned_clusters": ["N"]},
            {"people": [{"role": "Clinician", "clusters": ["A"]},
                        {"role": "Patient", "clusters": ["B"]},
                        {"role": "Medical Staff", "clusters": ["N"]}]},
        ], ["A", "B", "N"])
        self.assertEqual(merged["role_map"]["N"], "Unknown")
        self.assertEqual(merged["role_map"]["A"], "Clinician")
        self.assertEqual(merged["cluster_role_votes"]["N"],
                         {"Unknown": 2, "Medical Staff": 1})

    def test_hallucination_turn_flagged_non_speech(self) -> None:
        def turn(speaker, start, end, text, words, word_dicts):
            return {"speaker": speaker, "raw_speaker": speaker, "start_sec": start,
                    "end_sec": end, "text": text, "turn_word_count": words,
                    "words": word_dicts}
        turns = [turn("A", 0.0, 30.0, "Long history discussion.", 120,
                      [{"agreement": "agree", "no_speech_prob": 0.05}]),
                 turn("B", 31.0, 33.0, "It hurts here.", 3,
                      [{"agreement": "agree", "no_speech_prob": 0.1}]),
                 turn("N", 40.0, 41.0, "Thank you. Thank you.", 4,
                      [{"agreement": "solo_whisper", "no_speech_prob": 0.55}] * 4)]
        structure = {"role_map": {"A": "Clinician", "B": "Patient"},
                     "cluster_role_votes": {"A": {"Clinician": 3}, "B": {"Patient": 3}}}
        roles.apply_structure(turns, structure)
        self.assertTrue(turns[2].get("suspected_non_speech"))
        self.assertFalse(turns[2]["mark_unknown"])
        self.assertEqual(structure["suspected_non_speech_turns"], 1)
        self.assertNotIn("suspected_non_speech", turns[0])  # corroborated turns never flagged

    def test_clinician_temporal_order_swap(self) -> None:
        structure = {"role_map": {"A": "Clinician2", "B": "Clinician", "C": "Patient"},
                     "cluster_role_votes": {"A": {"Clinician2": 3}, "B": {"Clinician": 3},
                                            "C": {"Patient": 3}}}
        turns = [{"speaker": "A", "start_sec": 1.0}, {"speaker": "C", "start_sec": 5.0},
                 {"speaker": "B", "start_sec": 300.0}]
        roles.order_roles_by_first_appearance(turns, structure)
        self.assertEqual(structure["role_map"], {"A": "Clinician", "B": "Clinician2", "C": "Patient"})
        self.assertTrue(structure.get("role_order_changed"))
        self.assertEqual(structure["cluster_role_votes"]["A"], {"Clinician": 3})

    def test_patient_constraint_repair(self) -> None:
        merged = roles._merge_samples(
            [{"people": [{"role": "Clinician", "clusters": ["A"]},
                         {"role": "Medical Staff", "clusters": ["B"]}]}], ["A", "B"])
        self.assertIn("Patient", merged["role_map"].values())


class CpuBudgetTests(unittest.TestCase):
    def test_configure_cpu_caps_threads_and_reports(self) -> None:
        import os
        import torch
        from mediscribe_v2 import common

        before = torch.get_num_threads()
        try:
            applied = common.configure_cpu(reserve_cores=4, nice_increment=0)
            self.assertEqual(applied["cpu_threads"], max(2, (os.cpu_count() or 4) - 4))
            self.assertEqual(torch.get_num_threads(), applied["cpu_threads"])
            self.assertIsNone(applied["nice"])  # 0 means untouched
        finally:
            torch.set_num_threads(before)


class CliTests(unittest.TestCase):
    def test_webui_invocation_parses(self) -> None:
        args = parse_args([
            "input.wav", "--intermediate-root", "/tmp/i", "--output-root", "/tmp/o",
            "--debug-json", "--keep-intermediate",
            "--llm-base-url", "http://192.0.2.10:8011/v1", "--llm-model", "my-model",
        ])
        self.assertTrue(args.debug_json)
        self.assertEqual(args.min_speakers, 2)
        self.assertEqual(args.max_speakers, 5)

    def test_defaults(self) -> None:
        args = parse_args(["input.wav"])
        self.assertEqual(args.llm_base_url, common.LLM_BASE_URL_DEFAULT)
        self.assertEqual(args.llm_model, common.LLM_MODEL_DEFAULT)


class ResumeTests(unittest.TestCase):
    def test_resume_loads_diarizer_for_fusion_rescoring(self) -> None:
        import hashlib
        import json
        import tempfile
        from unittest import mock

        import numpy as np
        import soundfile as sf

        from mediscribe_v2 import diarize, pipeline

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "visit.wav"
            wave = np.zeros(16000, dtype="float32")
            sf.write(str(audio), wave, 16000, subtype="PCM_16")
            inter = root / "intermediate" / "visit"
            inter.mkdir(parents=True)
            sf.write(str(inter / "visit_converted.wav"), wave, 16000, subtype="PCM_16")
            (inter / "visit_audio_clock.json").write_text(json.dumps({
                "input_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(), "duration_sec": 1.0}))
            (inter / "visit_merged_words.json").write_text(json.dumps(
                {"words": [], "markers": [], "dropped": [], "meta": {}}))
            (inter / "visit_diarization.json").write_text(json.dumps(
                {"raw_segments": [], "alignment_segments": [], "exclusive_source": "pipeline_exclusive"}))
            args = parse_args(["visit.wav", "--intermediate-root", str(root / "intermediate"),
                               "--output-root", str(root / "output")])
            fusion = {"turns": [], "echo_collapsed": 0, "rescored_turns": 0, "boundary_snapped_words": 0,
                      "rescored_words": 0, "overlap_dispute_words": 0, "sentences_repaired": 0,
                      "sandwich_absorbed": 0, "cluster_similarity": {}}
            with mock.patch.object(diarize, "load_diarization_pipeline") as load, \
                    mock.patch.object(pipeline.fuse, "fuse", return_value=fusion):
                ctx = pipeline.run_audio_stages(args, audio, "cpu", lambda event: None, resume=True)
            self.assertTrue(ctx.resumed)
            load.assert_called_once_with("cpu")

            with mock.patch.object(diarize, "load_diarization_pipeline") as load, \
                    mock.patch.object(pipeline.fuse, "fuse", return_value=fusion):
                args.rescore = False
                pipeline.run_audio_stages(args, audio, "cpu", lambda event: None, resume=True)
            load.assert_not_called()


class RenderTests(unittest.TestCase):
    def test_suspected_non_speech_excluded_from_render(self) -> None:
        import tempfile
        from mediscribe_v2.render import render_final_transcript

        turns = [{"start_sec": 5.0, "end_sec": 6.0, "text": "Hello there.",
                  "final_role": "Clinician", "final_role_confidence": 0.9},
                 {"start_sec": 70.0, "end_sec": 71.0, "text": "Thank you.",
                  "final_role": "Unknown", "final_role_confidence": 0.0,
                  "suspected_non_speech": True}]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "final.txt"
            render_final_transcript(turns, out)
            text = out.read_text()
        self.assertIn("Clinician: Hello there.", text)
        self.assertNotIn("Thank you.", text)

    def test_label_logic(self) -> None:
        self.assertEqual(final_turn_label({"final_role": "Clinician", "final_role_confidence": 0.9}), "Clinician")
        self.assertEqual(final_turn_label({"final_role": "Clinician", "final_role_confidence": 0.1}), "Unknown")
        self.assertEqual(final_turn_label({"final_role": "Unknown", "final_role_confidence": 1.0}), "Unknown")



class LLMRetryTests(unittest.TestCase):
    """Bounded retries for missing JSON replies and transient request failures."""

    def setUp(self) -> None:
        import json as _json
        from unittest import mock
        from mediscribe_v2 import common
        self.json, self.mock, self.common = _json, mock, common
        self.turns = [
            {"speaker": "A", "text": "What brings you in today?", "start_sec": 0.0, "end_sec": 2.0,
             "words": [], "turn_word_count": 5},
            {"speaker": "B", "text": "My knee hurts.", "start_sec": 2.5, "end_sec": 4.0,
             "words": [], "turn_word_count": 3},
        ]
        self.good = self.json.dumps({"department": "rheumatology", "people": [
            {"role": "Clinician", "clusters": ["A"]}, {"role": "Patient", "clusters": ["B"]}]})

    def test_structure_reasks_only_missing_samples_with_larger_budget(self) -> None:
        calls: list[int] = []

        def fake_call(prompt, **kwargs):
            calls.append(kwargs["max_tokens"])
            # first round: one sample answers JSON, one overran (empty), one prose
            if len(calls) == 1:
                return self.good
            if len(calls) == 2:
                return ""
            if len(calls) == 3:
                return "I think the clinician is cluster A."
            return self.good

        with self.mock.patch.object(roles, "call_llm", side_effect=fake_call):
            structure = roles.infer_structure(self.turns, base_url="u", model="m", timeout_sec=1)
        self.assertEqual(structure["samples_parsed"], 3)
        self.assertEqual(structure["sample_rounds"], 2)
        self.assertEqual(structure["role_map"], {"A": "Clinician", "B": "Patient"})
        self.assertEqual(calls, [8192] * 3 + [12288] * 2)

    def test_structure_gives_up_after_bounded_json_retries(self) -> None:
        calls = []
        def prose(prompt, **kwargs):
            calls.append(kwargs["max_tokens"])
            return "no json here"
        with self.mock.patch.object(roles, "call_llm", side_effect=prose):
            with self.assertRaises(self.common.LLMBadReplyError):
                roles.infer_structure(self.turns, base_url="u", model="m", timeout_sec=1)
        self.assertEqual(calls, [budget for budget in roles.STRUCTURE_TOKEN_BUDGETS for _ in range(3)])

    def test_structure_recovers_with_a_larger_response_budget(self) -> None:
        def larger_reply(prompt, **kwargs):
            return self.good if kwargs["max_tokens"] == roles.STRUCTURE_TOKEN_BUDGETS[-1] else ""
        with self.mock.patch.object(roles, "call_llm", side_effect=larger_reply):
            structure = roles.infer_structure(self.turns, base_url="u", model="m", timeout_sec=1)
        self.assertEqual(structure["samples_parsed"], 3)
        self.assertEqual(structure["sample_rounds"], len(roles.STRUCTURE_TOKEN_BUDGETS))

    def test_call_llm_retries_transient_failures(self) -> None:
        import io
        import urllib.error
        common = self.common
        body = self.json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
        attempts: list[str] = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def flaky(request, *, timeout):
            attempts.append(request.get_method())
            if len(attempts) == 1:
                raise urllib.error.URLError("connection reset")
            if len(attempts) == 2:
                raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, io.BytesIO(b"busy"))
            return Response(body.encode("utf-8"))

        with self.mock.patch.object(common, "wait_for_llm"), \
                self.mock.patch.object(common.time, "sleep") as sleep, \
                self.mock.patch.object(common, "_urlopen", side_effect=flaky):
            reply = common.call_llm("hi", base_url="http://u/v1", model="m", timeout_sec=1)
        self.assertEqual(reply, "{}")
        self.assertEqual(attempts, ["POST"] * 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [3.0, 6.0])

    def test_call_llm_does_not_retry_context_length(self) -> None:
        import io
        import urllib.error
        common = self.common
        calls = []

        def too_long(request, *, timeout):
            calls.append(1)
            raise urllib.error.HTTPError(request.full_url, 400, "bad", {},
                                         io.BytesIO(b"This model's maximum context length is 65536"))

        with self.mock.patch.object(common, "wait_for_llm"), \
                self.mock.patch.object(common.time, "sleep"), \
                self.mock.patch.object(common, "_urlopen", side_effect=too_long):
            with self.assertRaises(common.LLMContextLengthError):
                common.call_llm("hi", base_url="http://u/v1", model="m", timeout_sec=1)
        self.assertEqual(len(calls), 1)

    def test_call_llm_gives_up_after_bounded_attempts(self) -> None:
        import urllib.error
        common = self.common
        with self.mock.patch.object(common, "wait_for_llm"), \
                self.mock.patch.object(common.time, "sleep"), \
                self.mock.patch.object(common, "_urlopen",
                                       side_effect=urllib.error.URLError("down")) as opened:
            with self.assertRaises(common.LLMUnavailableError):
                common.call_llm("hi", base_url="http://u/v1", model="m", timeout_sec=1)
        self.assertEqual(opened.call_count, common.LLM_GENERATION_ATTEMPTS)

    def test_extract_json_object_survives_stray_braces_in_prose(self) -> None:
        extract = self.common.extract_json_object
        self.assertEqual(extract('Answer: {"a": 1}\nNote: {this is not json}'), {"a": 1})
        self.assertEqual(extract('```json\n{"a": [1, 2]}\n```'), {"a": [1, 2]})
        self.assertIsNone(extract("no braces at all"))
        self.assertEqual(extract('[{"a": 1}] wrapped {oops'), {"a": 1})


if __name__ == "__main__":
    unittest.main()
