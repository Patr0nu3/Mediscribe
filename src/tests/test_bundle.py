from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mediscribe_v2 import bundle  # noqa: E402


def make_session(data_root: Path, name: str, *, finished: bool = False, state: str = "ready") -> None:
    (data_root / "input").mkdir(parents=True, exist_ok=True)
    (data_root / "input" / f"{name}.m4a").write_bytes(b"audio-" + name.encode())
    intermediate = data_root / "intermediate" / name
    intermediate.mkdir(parents=True)
    (intermediate / f"{name}_converted.wav").write_bytes(b"RIFF-converted")
    (intermediate / f"{name}_source_pcm.wav").write_bytes(b"RIFF-source")
    (intermediate / f"{name}_sen_aligned_segments.json").write_text("[]")
    (intermediate / f"{name}_editor.json").write_text(json.dumps({"finished": finished, "turns": []}))
    (intermediate / f"{name}_pipeline_state.json").write_text(json.dumps({"state": state}))
    (intermediate / f".{name}_editor.json.abc.tmp").write_text("{}")
    output = data_root / "output" / name
    output.mkdir(parents=True)
    (output / f"{name}_aligned_transcript.txt").write_text("[00:00]\nClinician: Hello.\n")
    (output / f"{name}_revisions.jsonl").write_text('{"event_id": "e1"}\n')


def zip_bytes(entries: dict[str, bytes]) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    buffer.seek(0)
    return buffer


class BundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "machine_a"
        self.target = root / "machine_b"
        self.zip_path = root / "visit.zip"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_round_trip_carries_review_state_and_skips_rebuildable_audio(self) -> None:
        make_session(self.source, "visit", finished=True)
        manifest = bundle.export_bundle(self.source, ["visit"], self.zip_path)
        self.assertEqual(manifest["sessions"][0]["input"], "visit.m4a")
        self.assertTrue(manifest["sessions"][0]["finished"])
        with zipfile.ZipFile(self.zip_path) as archive:
            names = set(archive.namelist())
        self.assertIn(bundle.MANIFEST_NAME, names)
        self.assertIn("input/visit.m4a", names)
        self.assertIn("intermediate/visit/visit_editor.json", names)
        self.assertIn("output/visit/visit_revisions.jsonl", names)
        self.assertNotIn("intermediate/visit/visit_source_pcm.wav", names)
        self.assertFalse(any("/." in name for name in names))

        result = bundle.import_bundle(self.target, self.zip_path)
        self.assertEqual(result["sessions"], ["visit"])
        self.assertEqual(result["replaced"], [])
        self.assertEqual((self.target / "input" / "visit.m4a").read_bytes(), b"audio-visit")
        editor = json.loads((self.target / "intermediate" / "visit" / "visit_editor.json").read_text())
        self.assertTrue(editor["finished"])
        self.assertEqual(list(self.target.glob(".bundle-import-*")), [])

    def test_existing_recording_is_a_conflict_until_replace(self) -> None:
        make_session(self.source, "visit")
        bundle.export_bundle(self.source, ["visit"], self.zip_path)
        make_session(self.target, "visit", finished=True)
        (self.target / "intermediate" / "visit" / "visit_stale.json").write_text("{}")

        with self.assertRaises(bundle.BundleConflictError) as raised:
            bundle.import_bundle(self.target, self.zip_path)
        self.assertEqual(raised.exception.names, ["visit"])
        self.assertTrue((self.target / "intermediate" / "visit" / "visit_stale.json").exists())

        result = bundle.import_bundle(self.target, self.zip_path, replace=True)
        self.assertEqual(result["replaced"], ["visit"])
        self.assertFalse((self.target / "intermediate" / "visit" / "visit_stale.json").exists())
        editor = json.loads((self.target / "intermediate" / "visit" / "visit_editor.json").read_text())
        self.assertFalse(editor["finished"])

    def test_transcripts_for_local_audio_import_without_conflict(self) -> None:
        (self.target / "input").mkdir(parents=True)
        (self.target / "input" / "visit.wav").write_bytes(b"local")
        source = zip_bytes({"output/visit/visit_aligned_transcript.txt": b"[00:00]\n"})
        result = bundle.import_bundle(self.target, source)
        self.assertEqual(result["replaced"], [])
        self.assertEqual((self.target / "input" / "visit.wav").read_bytes(), b"local")
        self.assertTrue((self.target / "output" / "visit" / "visit_aligned_transcript.txt").exists())

    def test_zipped_data_folder_is_accepted(self) -> None:
        source = zip_bytes({
            "data/input/visit.mp3": b"audio",
            "data/output/visit/visit_aligned_transcript.txt": b"[00:00]\n",
            "data/notes.txt": b"ignored",
            "__MACOSX/data/._visit.mp3": b"ignored",
        })
        result = bundle.import_bundle(self.target, source)
        self.assertEqual(result["sessions"], ["visit"])
        self.assertEqual(result["ignored"], 1)
        self.assertTrue((self.target / "input" / "visit.mp3").exists())

    def test_unsafe_members_are_refused_and_leave_nothing(self) -> None:
        for entries in (
            {"output/../../evil.txt": b"x"},
            {"/output/visit/visit.txt": b"x"},
            {"output\\visit\\visit.txt": b"x"},
            {"output/.hidden/file.txt": b"x"},
        ):
            with self.subTest(entries=list(entries)):
                with self.assertRaises(bundle.BundleError):
                    bundle.import_bundle(self.target, zip_bytes(entries))
        link = io.BytesIO()
        with zipfile.ZipFile(link, "w") as archive:
            info = zipfile.ZipInfo("output/visit/visit_canonical.json")
            info.external_attr = (0o120777 << 16)
            archive.writestr(info, "/etc/passwd")
        link.seek(0)
        with self.assertRaises(bundle.BundleError):
            bundle.import_bundle(self.target, link)
        self.assertFalse(self.target.exists() and any(self.target.iterdir()))

    def test_bad_zip_and_foreign_or_newer_manifest_are_refused(self) -> None:
        with self.assertRaises(bundle.BundleError):
            bundle.import_bundle(self.target, io.BytesIO(b"not a zip"))
        with self.assertRaises(bundle.BundleError):
            bundle.import_bundle(self.target, zip_bytes({
                bundle.MANIFEST_NAME: json.dumps({"format": "other"}).encode(),
                "output/visit/visit.txt": b"x",
            }))
        with self.assertRaises(bundle.BundleError):
            bundle.import_bundle(self.target, zip_bytes({
                bundle.MANIFEST_NAME: json.dumps({"format": bundle.BUNDLE_FORMAT, "version": 99}).encode(),
                "output/visit/visit.txt": b"x",
            }))
        with self.assertRaises(bundle.BundleError):
            bundle.import_bundle(self.target, zip_bytes({"readme.txt": b"x"}))

    def test_size_limit_and_busy_recordings_are_refused(self) -> None:
        source = zip_bytes({"output/visit/visit_aligned_transcript.txt": b"x" * 100})
        with self.assertRaises(bundle.BundleError):
            bundle.import_bundle(self.target, source, max_bytes=10)
        with self.assertRaises(bundle.BundleError):
            bundle.import_bundle(self.target, source, busy={"visit"})

    def test_bundle_made_mid_run_imports_as_awaiting_resume(self) -> None:
        make_session(self.source, "visit", state="running")
        bundle.export_bundle(self.source, ["visit"], self.zip_path)
        bundle.import_bundle(self.target, self.zip_path)
        state = json.loads((self.target / "intermediate" / "visit" / "visit_pipeline_state.json").read_text())
        self.assertEqual(state["state"], "awaiting_resume")
        self.assertEqual(state["reason"], "imported")

    def test_cli_exports_all_and_imports(self) -> None:
        make_session(self.source, "a")
        make_session(self.source, "b")
        bundle.main(["export", "--all", "--data-root", str(self.source), "-o", str(self.zip_path)])
        bundle.main(["import", str(self.zip_path), "--data-root", str(self.target)])
        self.assertEqual(bundle.processed_names(self.target), ["a", "b"])
        with self.assertRaises(SystemExit):
            bundle.main(["import", str(self.zip_path), "--data-root", str(self.target)])
        with self.assertRaises(SystemExit):
            bundle.main(["export", "missing", "--data-root", str(self.source), "-o", str(self.zip_path)])


if __name__ == "__main__":
    unittest.main()
