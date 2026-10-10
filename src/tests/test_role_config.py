"""Custom roles across inference, transcript export, and editor sessions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mediscribe_v2 import common, pipeline, roles
from mediscribe_v2.render import render_final_transcript


class RoleConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "config" / "roles" / "custom.json"
        self.path.parent.mkdir(parents=True)
        self.payload = {
            "roles": [
                {"name": "Host", "aliases": ["interviewer"], "description": "The person asking questions."},
                {"name": "Guest", "aliases": [], "description": "The person answering questions."},
            ],
            "instructions": "Assign roles from the interview content.",
        }
        self.turns = [
            {"speaker": "A", "text": "How did you get started?", "start_sec": 0.0, "end_sec": 2.0,
             "words": [], "turn_word_count": 5},
            {"speaker": "B", "text": "I joined a workshop.", "start_sec": 2.5, "end_sec": 4.0,
             "words": [], "turn_word_count": 4},
        ]

    def load(self, payload=None):
        self.path.write_text(json.dumps(self.payload if payload is None else payload), encoding="utf-8")
        return common.load_role_config(self.path)

    def test_custom_roles_reach_prompt_votes_and_export(self) -> None:
        config = self.load()
        reply = json.dumps({"department": "interview", "people": [
            {"role": "interviewer", "clusters": ["A"]}, {"role": "guest", "clusters": ["B"]}]})
        with mock.patch.object(roles, "call_llm", return_value=reply) as llm:
            structure = roles.infer_structure(self.turns, base_url="u", model="m", timeout_sec=1,
                                              role_config=config)
        prompt = llm.call_args.args[0]
        self.assertIn("Host: The person asking questions.", prompt)
        self.assertNotIn("Clinician", prompt)
        self.assertNotIn("Patient", prompt)
        self.assertNotIn("clinician", llm.call_args.kwargs["system"])
        self.assertEqual(structure["role_map"], {"A": "Host", "B": "Guest"})
        roles.apply_structure(self.turns, structure)
        output = self.root / "transcript.txt"
        render_final_transcript(self.turns, output, role_options=structure["role_options"])
        text = output.read_text(encoding="utf-8")
        self.assertIn("Host: How did you get started?", text)
        self.assertIn("Guest: I joined a workshop.", text)
        self.assertNotIn("Unknown:", text)

    def test_required_roles_do_not_inject_clinical_labels(self) -> None:
        self.payload["required_roles"] = ["Host", "Guest"]
        config = self.load()
        merged = roles._merge_samples([{"people": [{"role": "Host", "clusters": ["A", "B"]}]}],
                                      ["A", "B"], config)
        self.assertEqual(set(merged["role_map"].values()), {"Host", "Guest"})

    def test_custom_order_keeps_confidence_and_evidence_with_labels(self) -> None:
        self.payload["ordered_roles"] = ["Host", "Guest"]
        config = self.load()
        structure = roles._merge_samples([{"people": [
            {"role": "Guest", "clusters": ["A"], "evidence": "First voice"},
            {"role": "Host", "clusters": ["B"], "evidence": "Second voice"}]}] * 3,
            ["A", "B"], config)
        roles.apply_structure(self.turns, structure)
        self.assertEqual(self.turns[0]["final_role"], "Host")
        self.assertEqual(self.turns[0]["final_role_confidence"], 1.0)
        self.assertEqual(self.turns[1]["final_role"], "Guest")
        self.assertEqual(structure["evidence"]["Host"], "First voice")

    def test_invalid_config_fails_at_load(self) -> None:
        host = {"name": "Host", "aliases": [], "description": "First"}
        guest = {"name": "Guest", "aliases": [], "description": "Second"}
        invalid = [
            [], {"roles": []}, {"roles": {"Host": "Old format"}}, {"roles": ["Host"]},
            {"roles": [{**host, "name": "Unknown"}]},
            {"roles": [{**host, "description": ""}]},
            {"roles": [host, {**host, "name": "host"}]},
            {"roles": [{**host, "name": "Host: One"}]},
            {"roles": [{**host, "name": "SPEAKER_00"}]},
            {"roles": [host], "required_roles": ["Missing"]},
            {"roles": [host], "ordered_roles": ["Host", "Host"]},
            {"roles": [{**host, "aliases": "interviewer"}]},
            {"roles": [{**host, "aliases": [3]}]},
            {"roles": [{**host, "aliases": ["Unknown"]}]},
            {"roles": [host, {**guest, "aliases": ["Host"]}]},
            {"roles": [{**host, "aliases": ["speaker"]}, {**guest, "aliases": ["SPEAKER"]}]},
            {"roles": [host], "instructions": 3},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.load(payload)

    def test_word_lists_normalize_terms_and_allow_explicit_empty_list(self) -> None:
        path = self.root / "words.json"
        path.write_text('["Mm-hmm", "YEAH", "I\'m"]', encoding="utf-8")
        self.assertEqual(common.load_token_lexicon(path), frozenset({"mmhmm", "yeah", "i'm"}))
        path.write_text('[]', encoding="utf-8")
        self.assertEqual(common.load_token_lexicon(path), frozenset())
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            common.load_token_lexicon(path)

    def test_invalid_word_lists_fail_before_processing(self) -> None:
        path = self.root / "words.json"
        for entries in ({"words": ["yeah"]}, [3], ["..."]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                path.write_text(json.dumps(entries), encoding="utf-8")
                common.load_token_lexicon(path)

    def test_environment_override_reaches_editor_and_worker_imports(self) -> None:
        self.load()
        code = """
import json
import sys
from pathlib import Path
from mediscribe_v2.common import ROLE_OPTIONS
from WebUI.server import EditorStore
store = EditorStore(Path(sys.argv[1]))
paths = store.paths_for('interview')
paths.output_dir.mkdir(parents=True, exist_ok=True)
paths.final_txt.write_text('[00:00]\\nHost: Welcome.\\nGuest: Hello.\\n', encoding='utf-8')
session = store.load_session('interview')
print(json.dumps({'roles': ROLE_OPTIONS, 'choices': session['role_options'],
                  'speakers': session['speakers'], 'turns': [turn['label'] for turn in session['turns']]}))
"""
        env = {**os.environ, "PYTHONPATH": str(SRC), "MEDISCRIBE_ROLES_CONFIG": str(self.path)}
        result = subprocess.run([sys.executable, "-c", code, str(self.root)], env=env,
                                capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["roles"], ["Host", "Guest", "Unknown"])
        self.assertEqual(payload["choices"], payload["roles"])
        self.assertEqual(payload["speakers"], payload["roles"])
        self.assertEqual(payload["turns"], ["Host", "Guest"])


class DefaultInputTests(unittest.TestCase):
    def test_missing_default_folder_is_created_before_configuration_is_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data = Path(tmpdir) / "data"
            with mock.patch.object(pipeline, "DATA_ROOT", data), \
                    mock.patch.object(pipeline, "validate_llm_config") as validate:
                with self.assertRaisesRegex(SystemExit, "No input audio files found"):
                    pipeline.main([])
            self.assertTrue((data / "input").is_dir())
            validate.assert_not_called()

    def test_no_path_processes_recordings_from_default_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data = Path(tmpdir) / "data"
            recording = data / "input" / "visit.wav"
            recording.parent.mkdir(parents=True)
            recording.write_bytes(b"synthetic recording fixture")
            with mock.patch.object(pipeline, "DATA_ROOT", data), \
                    mock.patch.object(pipeline, "resolve_device", return_value="cpu"), \
                    mock.patch.object(pipeline, "configure_cpu", return_value={"cpu_threads": 1, "cpu_cores": 1, "nice": None}), \
                    mock.patch.object(pipeline, "process_audio_file", return_value="ok") as process:
                pipeline.main(["--llm-base-url", "https://api.example.com/v1", "--llm-model", "model"])
            self.assertEqual(process.call_args.args[1], recording)

    def test_explicit_inputs_override_default_folder(self) -> None:
        args = pipeline.parse_args(["one.wav", "two.m4a", "recordings/"])
        self.assertEqual(args.input_path, [Path("one.wav"), Path("two.m4a"), Path("recordings/")])


if __name__ == "__main__":
    unittest.main()
