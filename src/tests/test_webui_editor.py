from __future__ import annotations

import errno
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import types
import unittest
import wave
import zipfile
from pathlib import Path
from typing import Any
from unittest import mock


SRC_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SRC_ROOT / "WebUI" / "server.py"


def load_webui_module():
    sys.modules.pop("mediscribe_webui_server", None)
    spec = importlib.util.spec_from_file_location("mediscribe_webui_server", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


WEBUI = load_webui_module()


class WebUIEditorTests(unittest.TestCase):
    def test_safe_session_name_rejects_path_traversal(self) -> None:
        with self.assertRaises(ValueError):
            WEBUI.safe_session_name("../outside")

    def test_safe_session_name_preserves_edge_spaces_for_existing_artifacts(self) -> None:
        self.assertEqual(WEBUI.safe_session_name("visit "), "visit ")

    def test_safe_input_filename_rejects_bad_upload_names(self) -> None:
        with self.assertRaises(ValueError):
            WEBUI.safe_input_filename("../outside.wav")
        with self.assertRaises(ValueError):
            WEBUI.safe_input_filename("notes.txt")

    def test_webui_accepts_only_loopback_hosts(self) -> None:
        self.assertTrue(WEBUI.is_loopback_address("127.0.0.1"))
        self.assertTrue(WEBUI.is_loopback_address("localhost"))
        self.assertFalse(WEBUI.is_loopback_address("0.0.0.0"))
        self.assertFalse(WEBUI.is_loopback_address("192.168.1.10"))

    def test_http_server_falls_back_to_os_selected_port_when_preferred_port_is_busy(
        self,
    ) -> None:
        fallback_server = mock.Mock(server_address=("127.0.0.1", 49_152))
        address_in_use = OSError(errno.EADDRINUSE, "Address already in use")

        with mock.patch.object(
            WEBUI,
            "ThreadingHTTPServer",
            side_effect=[address_in_use, fallback_server],
        ) as server_factory:
            server = WEBUI.create_http_server(
                "127.0.0.1",
                7_860,
                mock.sentinel.handler,
                allow_port_fallback=True,
            )

        self.assertIs(server, fallback_server)
        self.assertEqual(
            server_factory.call_args_list,
            [
                mock.call(("127.0.0.1", 7_860), mock.sentinel.handler),
                mock.call(("127.0.0.1", 0), mock.sentinel.handler),
            ],
        )

    def test_http_server_strict_port_does_not_fall_back(self) -> None:
        address_in_use = OSError(errno.EADDRINUSE, "Address already in use")

        with mock.patch.object(
            WEBUI,
            "ThreadingHTTPServer",
            side_effect=address_in_use,
        ) as server_factory:
            with self.assertRaises(OSError):
                WEBUI.create_http_server(
                    "127.0.0.1",
                    7_860,
                    mock.sentinel.handler,
                    allow_port_fallback=False,
                )

        server_factory.assert_called_once_with(("127.0.0.1", 7_860), mock.sentinel.handler)

    def test_store_uses_data_runtime_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = WEBUI.EditorStore(root)

            self.assertEqual(store.data_root, root.resolve() / "data")
            self.assertEqual(store.input_root, root.resolve() / "data" / "input")
            self.assertEqual(store.intermediate_root, root.resolve() / "data" / "intermediate")
            self.assertEqual(store.output_root, root.resolve() / "data" / "output")

    def test_send_file_treats_write_reset_as_client_disconnect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "audio.wav"
            file_path.write_bytes(b"audio-bytes")
            handler = object.__new__(WEBUI.WebUIRequestHandler)
            handler.headers = {}
            handler.wfile = types.SimpleNamespace(write=lambda chunk: (_ for _ in ()).throw(ConnectionResetError()))
            handler.send_response = lambda status: None
            handler.send_header = lambda name, value: None
            handler.end_headers = lambda: None

            with self.assertRaises(WEBUI.ClientDisconnected):
                handler.send_file(file_path)

    def test_static_assets_are_not_reused_across_local_restarts(self) -> None:
        handler = object.__new__(WEBUI.WebUIRequestHandler)
        handler.send_file = mock.Mock()

        handler.send_static("/app.js")

        handler.send_file.assert_called_once_with(
            (WEBUI.STATIC_ROOT / "app.js").resolve(),
            cache_control="no-store",
        )

    def test_store_lists_input_audio_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            wav_path = input_root / "visit.wav"
            with wave.open(str(wav_path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(8000)
                handle.writeframes(b"\0\0" * 8000)
            (input_root / "notes.txt").write_text("skip", encoding="utf-8")

            files = WEBUI.EditorStore(root).list_input_audio_files()

        self.assertEqual([item["path"] for item in files], ["visit.wav"])
        self.assertEqual(files[0]["duration_sec"], 1.0)
        self.assertGreater(files[0]["size"], 0)

    def test_store_imports_audio_without_overwriting_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            (input_root / "visit.wav").write_bytes(b"existing")
            store = WEBUI.EditorStore(root)

            saved = store.save_input_audio("visit.wav", io.BytesIO(b"new-audio"), len(b"new-audio"))

        self.assertEqual(saved["path"], "visit_2.wav")
        self.assertEqual(saved["size"], len(b"new-audio"))
        self.assertFalse(saved["duplicate"])

    def test_store_moves_a_reviewed_session_between_machines_as_a_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = WEBUI.EditorStore(root / "a")
            (source.input_root).mkdir(parents=True)
            (source.input_root / "visit.wav").write_bytes(b"audio")
            source.save_session("visit", {
                "turns": [{"id": "t1", "speaker": "Clinician", "text": "Hello there.", "start_sec": 0, "end_sec": 1}],
                "finished": True,
            })
            bundle_path = source.export_bundle_file(["visit"])
            payload = bundle_path.read_bytes()
            bundle_path.unlink()

            target = WEBUI.EditorStore(root / "b")
            result = target.import_bundle_upload(io.BytesIO(payload), len(payload))
            with self.assertRaises(WEBUI.BundleConflictError):
                target.import_bundle_upload(io.BytesIO(payload), len(payload))
            session = target.load_session("visit")
            listed = target.list_sessions()
            leftovers = list(target.data_root.glob(".bundle-*"))

        self.assertEqual(result["sessions"], ["visit"])
        self.assertTrue(session["finished"])
        self.assertTrue(session["audio"]["available"])
        self.assertEqual(session["turns"][0]["text"], "Hello there.")
        self.assertEqual(listed[0]["state"], "ready")
        self.assertEqual(leftovers, [])

    def test_session_without_intermediate_files_loads_canonical_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = WEBUI.EditorStore(Path(tmpdir))
            paths = store.paths_for("visit")
            paths.output_dir.mkdir(parents=True)
            paths.final_txt.write_text("[00:00]\nClinician: Hello there.\n", encoding="utf-8")
            turn = {
                "id": "turn_0",
                "start_sec": 1.5,
                "end_sec": 2.5,
                "text": "Hello there.",
                "final_role": "Clinician",
                "final_role_confidence": 0.9,
                "words": [
                    {"word": "Hello", "start_sec": 1.5, "end_sec": 1.9},
                    {"word": "there.", "start_sec": 2.0, "end_sec": 2.5},
                ],
            }
            paths.canonical_json.write_text(json.dumps({"role_assignment": {"turns": [turn]}}), encoding="utf-8")

            turns = store.load_turns(paths)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["start_sec"], 1.5)
        self.assertEqual([word["start_sec"] for word in turns[0]["words"]], [1.5, 2.0])

    def test_store_skips_byte_identical_audio_already_imported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            store = WEBUI.EditorStore(root)
            data = b"RIFF" + b"audio-bytes" * 64

            first = store.save_input_audio("visit.wav", io.BytesIO(data), len(data))
            # Same content + same name -> already here, not re-imported.
            same_name = store.save_input_audio("visit.wav", io.BytesIO(data), len(data))
            # Same content under a different name -> still a duplicate.
            renamed = store.save_input_audio("copy.wav", io.BytesIO(data), len(data))

            self.assertFalse(first["duplicate"])
            self.assertTrue(same_name["duplicate"])
            self.assertEqual(same_name["name"], "visit.wav")
            self.assertTrue(renamed["duplicate"])
            self.assertEqual(renamed["name"], "visit.wav")

            wavs = sorted(path.name for path in input_root.glob("*.wav"))
            self.assertEqual(wavs, ["visit.wav"])

            # The WebUI asks the user first; a confirmed duplicate is stored under its own name.
            forced = store.save_input_audio("copy.wav", io.BytesIO(data), len(data), allow_duplicate=True)
            self.assertFalse(forced["duplicate"])
            self.assertEqual(forced["name"], "copy.wav")
            self.assertEqual(
                sorted(path.name for path in input_root.glob("*.wav")), ["copy.wav", "visit.wav"]
            )
            # No leftover temp import artifacts.
            self.assertEqual(list(input_root.glob(".import-*")), [])

    def test_pipeline_subprocess_env_puts_interpreter_bin_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_root = Path(tmpdir) / "envs" / "scribe"
            bin_dir = env_root / "bin"
            bin_dir.mkdir(parents=True)
            (env_root / "conda-meta").mkdir()
            python_bin = bin_dir / "python"
            python_bin.write_text("", encoding="utf-8")

            env = WEBUI.pipeline_subprocess_env(str(python_bin))

            self.assertEqual(env["PATH"].split(os.pathsep)[0], str(bin_dir))
            self.assertEqual(env["CONDA_PREFIX"], str(env_root))
            self.assertEqual(env["PYTHONUNBUFFERED"], "1")

    def test_resolve_ffprobe_prefers_path_then_env_bin(self) -> None:
        WEBUI._RESOLVED_FFPROBE.clear()
        try:
            with mock.patch.object(WEBUI.shutil, "which", return_value="/usr/bin/ffprobe"):
                self.assertEqual(WEBUI.resolve_ffprobe(), "/usr/bin/ffprobe")

            WEBUI._RESOLVED_FFPROBE.clear()
            with tempfile.TemporaryDirectory() as tmpdir:
                bin_dir = Path(tmpdir) / "bin"
                bin_dir.mkdir()
                ffprobe = bin_dir / "ffprobe"
                ffprobe.write_text("", encoding="utf-8")
                ffprobe.chmod(0o755)
                with mock.patch.object(WEBUI.shutil, "which", return_value=None), mock.patch.object(
                    WEBUI, "resolve_pipeline_python", return_value=str(bin_dir / "python")
                ):
                    self.assertEqual(WEBUI.resolve_ffprobe(), str(ffprobe))
        finally:
            WEBUI._RESOLVED_FFPROBE.clear()

    def test_pipeline_input_resolution_stays_inside_input_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            audio_path = input_root / "visit.wav"
            audio_path.write_bytes(b"fake")
            store = WEBUI.EditorStore(root)

            self.assertEqual(store.resolve_pipeline_input("visit.wav"), audio_path.resolve())
            with self.assertRaises(ValueError):
                store.resolve_pipeline_input("../visit.wav")

    def test_pipeline_runner_uses_data_roots_in_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            (input_root / "visit.wav").write_bytes(b"fake")
            runner = WEBUI.PipelineRunner(WEBUI.EditorStore(root))

            with mock.patch("threading.Thread.start", lambda self: None):
                job = runner.start("visit.wav")

        self.assertIn(str(root / "data" / "intermediate"), job.command)
        self.assertIn(str(root / "data" / "output"), job.command)
        self.assertTrue(job.command[2].endswith("src/worker.py"))

    def test_pipeline_runner_passes_configured_llm_endpoint_to_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            (input_root / "visit.wav").write_bytes(b"fake")
            runner = WEBUI.PipelineRunner(
                WEBUI.EditorStore(root),
                llm_base_url="http://host.docker.internal:8123/v1",
                llm_model="test-model",
                llm_concurrency=3,
                worker_idle_sec=600,
            )

            with mock.patch("threading.Thread.start", lambda self: None):
                job = runner.start("visit.wav")

        option_index = job.command.index("--llm-base-url")
        self.assertEqual(job.command[option_index + 1], "http://host.docker.internal:8123/v1")
        model_option_index = job.command.index("--llm-model")
        self.assertEqual(job.command[model_option_index + 1], "test-model")
        self.assertEqual(job.command[job.command.index("--llm-concurrency") + 1], "3")
        self.assertEqual(job.command[job.command.index("--idle-sec") + 1], "600.0")

    def test_worker_script_is_found_next_to_the_server_not_under_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = WEBUI.PipelineRunner(WEBUI.EditorStore(Path(tmpdir)))
            command = runner.worker_command()
        self.assertEqual(command[2], str(WEBUI.WORKER_SCRIPT))
        self.assertTrue(WEBUI.WORKER_SCRIPT.is_file())
        self.assertFalse(str(WEBUI.WORKER_SCRIPT).startswith(tmpdir))

    def test_webui_accepts_https_endpoint(self) -> None:
        with mock.patch.object(sys, "argv", ["server.py", "--llm-base-url",
                "https://api.example.com/v1", "--llm-model", "test-model"]):
            args = WEBUI.parse_args()
        self.assertEqual(args.llm_base_url, "https://api.example.com/v1")
        self.assertEqual(args.llm_model, "test-model")

    def test_webui_reads_endpoint_configuration(self) -> None:
        with mock.patch.dict(os.environ, {
            "MEDISCRIBE_LLM_BASE_URL": "https://api.example.com/v1",
            "MEDISCRIBE_LLM_MODEL": "test-model",
        }), mock.patch.object(sys, "argv", ["server.py"]):
            args = WEBUI.parse_args()
        self.assertEqual(args.llm_base_url, "https://api.example.com/v1")
        self.assertEqual(args.llm_model, "test-model")

    def test_webui_requires_explicit_endpoint_configuration(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "argv", ["server.py"]):
            args = WEBUI.parse_args()
        self.assertEqual(args.llm_base_url, "")
        self.assertEqual(args.llm_model, "")

    def test_build_handler_wires_pipeline_llm_url_into_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = WEBUI.build_handler(
                Path(tmpdir),
                llm_base_url="http://container-host:8000/v1",
                llm_model="test-model",
            )

        self.assertEqual(handler.runner.llm_base_url, "http://container-host:8000/v1")
        self.assertEqual(handler.runner.llm_model, "test-model")

    def test_pipeline_runner_reprocess_removes_artifacts_and_skips_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            (input_root / "visit.wav").write_bytes(b"fake")
            intermediate_dir = root / "data" / "intermediate" / "visit"
            output_dir = root / "data" / "output" / "visit"
            intermediate_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            (intermediate_dir / "visit_pipeline_state.json").write_text(
                json.dumps({"state": "awaiting_resume"}),
                encoding="utf-8",
            )
            (intermediate_dir / "visit_editor.json").write_text("{}", encoding="utf-8")
            (output_dir / "visit_aligned_transcript.txt").write_text("old", encoding="utf-8")
            runner = WEBUI.PipelineRunner(WEBUI.EditorStore(root))

            with mock.patch("threading.Thread.start", lambda self: None):
                job = runner.start("visit.wav", reprocess=True)

        self.assertTrue(job.reprocess)
        self.assertFalse(runner.files["visit"].resume)
        self.assertFalse(intermediate_dir.exists())
        self.assertFalse(output_dir.exists())
        self.assertIn("Preparing clean reprocess", job.log[0])

    def test_pipeline_runner_marks_awaiting_resume_file_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            (input_root / "visit.wav").write_bytes(b"fake")
            intermediate_dir = root / "data" / "intermediate" / "visit"
            intermediate_dir.mkdir(parents=True)
            (intermediate_dir / "visit_pipeline_state.json").write_text(
                json.dumps({"state": "awaiting_resume"}), encoding="utf-8"
            )
            runner = WEBUI.PipelineRunner(WEBUI.EditorStore(root))
            with mock.patch("threading.Thread.start", lambda self: None):
                runner.start("visit.wav")
        self.assertTrue(runner.files["visit"].resume)

    def test_pipeline_runner_queues_submissions_while_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            (input_root / "first.wav").write_bytes(b"fake")
            (input_root / "second.wav").write_bytes(b"fake")
            runner = WEBUI.PipelineRunner(WEBUI.EditorStore(root))

            with mock.patch("threading.Thread.start", lambda self: None):
                first = runner.submit("first.wav")
                second = runner.submit("second.wav", reprocess=True)
                again = runner.submit("second.wav")

        self.assertEqual(first["job"]["status"], "running")
        self.assertEqual(second["queued"]["name"], "second")
        self.assertTrue(second["queued"]["reprocess"])
        self.assertEqual(len(second["queue"]), 1)
        self.assertTrue(again["already_queued"])
        statuses = {f["name"]: f["status"] for f in runner.status_dict()["files"]}
        self.assertEqual(statuses, {"first": "running", "second": "queued"})

    def test_worker_events_drive_per_file_progress_and_job_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            for name in ("first.wav", "second.wav"):
                (input_root / name).write_bytes(b"fake")
            runner = WEBUI.PipelineRunner(WEBUI.EditorStore(root))
            with mock.patch("threading.Thread.start", lambda self: None):
                runner.submit("first.wav")
                runner.submit("second.wav")
            job_first = runner.files["first"].job_id
            job_second = runner.files["second"].job_id

            runner.handle_worker_event({"event": "worker_ready", "device": "cuda", "llm_concurrency": 2})
            runner.handle_worker_event({"event": "stage", "file": "first", "job_id": job_first,
                                        "stage": "asr", "index": 2, "total": 7, "lane": "audio",
                                        "label": "dual-engine ASR"})
            runner.handle_worker_event({"event": "log", "file": "first", "job_id": job_first,
                                        "line": "  merge: ok"})
            runner.handle_worker_event({"event": "stage", "file": "first", "job_id": job_first,
                                        "stage": "roles", "index": 5, "total": 7, "lane": "llm",
                                        "label": "content-first roles"})
            runner.handle_worker_event({"event": "stage", "file": "second", "job_id": job_second,
                                        "stage": "prepare", "index": 1, "total": 7, "lane": "audio",
                                        "label": "preparing audio views"})
            status = runner.status_dict()
            by_name = {f["name"]: f for f in status["files"]}
            self.assertEqual(by_name["first"]["lane"], "llm")
            self.assertEqual(by_name["first"]["stage_number"], 5)
            self.assertEqual(by_name["second"]["status"], "running")
            self.assertEqual(status["worker"]["llm_lane"], ["first"])
            self.assertEqual(status["worker"]["audio_lane"], "second")
            self.assertTrue(any("[first]   merge: ok" == entry["line"] for entry in status["log"]))

            runner.handle_worker_event({"event": "file_done", "file": "first", "job_id": job_first,
                                        "status": "ok", "elapsed_sec": 12.5,
                                        "stats": {"turns": 40, "moves_applied": 2}})
            runner.handle_worker_event({"event": "file_failed", "file": "second", "job_id": job_second,
                                        "error": "RuntimeError: boom", "traceback": "Traceback\nboom"})
            status = runner.status_dict()
            by_name = {f["name"]: f for f in status["files"]}
            self.assertEqual(by_name["first"]["status"], "succeeded")
            self.assertEqual(by_name["first"]["stats"]["moves_applied"], 2)
            self.assertEqual(by_name["second"]["status"], "failed")
            self.assertEqual(by_name["second"]["error"], "RuntimeError: boom")
            self.assertEqual(runner.jobs[job_first].status, "succeeded")
            self.assertEqual(runner.jobs[job_second].status, "failed")
            self.assertEqual(status["last_finished"]["id"], job_second)
            self.assertEqual(status["queue"], [])

    def test_worker_exit_fails_unfinished_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            (input_root / "visit.wav").write_bytes(b"fake")
            runner = WEBUI.PipelineRunner(WEBUI.EditorStore(root))
            with mock.patch("threading.Thread.start", lambda self: None):
                runner.submit("visit.wav")
            fake = mock.Mock()
            fake.poll.return_value = 1
            runner.worker = fake
            runner._worker_exited(fake, 1)
            self.assertEqual(runner.files["visit"].status, "failed")
            self.assertIn("worker exited", runner.files["visit"].error)
            self.assertIsNone(runner.worker)
            with self.assertRaises(ValueError):
                with mock.patch("threading.Thread.start", lambda self: None):
                    runner.submit("visit.wav")
                    runner.release_worker()

    def test_folder_submission_expands_to_audio_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            for name in ("b.wav", "a.m4a", "notes.txt"):
                (input_root / name).write_bytes(b"fake")
            runner = WEBUI.PipelineRunner(WEBUI.EditorStore(root))
            with mock.patch("threading.Thread.start", lambda self: None):
                payload = runner.submit(None)
        self.assertEqual(payload["job"]["files"], ["a", "b"])
        self.assertEqual([f["status"] for f in payload["files"]], ["running", "queued"])

    def test_store_loads_debug_turns_and_speakers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_dir = root / "data" / "intermediate" / "visit_a"
            session_dir.mkdir(parents=True)
            (session_dir / "visit_a_debug.json").write_text(
                json.dumps(
                    {
                        "merged_turns": [
                            {
                                "final_role": "Clinician",
                                "raw_speaker": "SPEAKER_00",
                                "start_sec": 1.0,
                                "end_sec": 2.0,
                                "text": "Please sit here.",
                                "words": [
                                    {"raw_text": "Please", "start_sec": 1.0, "end_sec": 1.2},
                                    {"raw_text": "sit", "start_sec": 1.2, "end_sec": 1.4},
                                ],
                            }
                        ],
                        "diarization": {
                            "alignment_segments_original": [
                                {"speaker": "SPEAKER_00", "start_sec": 1.0, "end_sec": 2.0}
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            session = WEBUI.EditorStore(root).load_session("visit_a")

        self.assertEqual(session["turns"][0]["label"], "Clinician")
        self.assertEqual(session["turns"][0]["words"][0]["text"], "Please")
        self.assertIn("Clinician", session["speakers"])
        self.assertIn("Clinician2", session["speakers"])
        self.assertNotIn("SPEAKER_00", session["speakers"])
        self.assertEqual(session["diarization"][0]["speaker"], "SPEAKER_00")

    def test_load_session_reads_each_large_json_artifact_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_dir = root / "data" / "intermediate" / "visit_once"
            session_dir.mkdir(parents=True)
            editor_path = session_dir / "visit_once_editor.json"
            debug_path = session_dir / "visit_once_debug.json"
            editor_path.write_text(
                json.dumps(
                    {
                        "finished": False,
                        "turns": [
                            {
                                "id": "turn-1",
                                "label": "Clinician",
                                "start_sec": 0.0,
                                "end_sec": 1.0,
                                "text": "Hello.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            debug_path.write_text(
                json.dumps(
                    {
                        "diarization": {
                            "alignment_segments_original": [
                                {"speaker": "SPEAKER_00", "start_sec": 0.0, "end_sec": 1.0}
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            original_read = WEBUI.read_json_or_default
            reads: list[Path] = []

            def tracked_read(path: Path, default: Any) -> Any:
                reads.append(path)
                return original_read(path, default)

            with mock.patch.object(WEBUI, "read_json_or_default", side_effect=tracked_read):
                WEBUI.EditorStore(root).load_session("visit_once")

        self.assertEqual(reads.count(editor_path), 1)
        self.assertEqual(reads.count(debug_path), 1)

    def test_save_session_writes_editor_state_and_final_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = WEBUI.EditorStore(root)
            result = store.save_session(
                "visit_b",
                {
                    "speakers": ["Clinician", "Patient", "SPEAKER_00"],
                    "finished": True,
                    "turns": [
                        {
                            "id": "turn-1",
                            "label": "Clinician",
                            "start_sec": 0.2,
                            "end_sec": 1.0,
                            "text": "How are you?",
                            "playbackRate": 0.75,
                            "bookmarked": True,
                        },
                        {
                            "id": "turn-2",
                            "label": "Patient",
                            "start_sec": 61.0,
                            "end_sec": 62.0,
                            "text": "Better today.",
                        },
                    ],
                },
            )
            editor_json = Path(result["editor_json"])
            final_txt = Path(result["final_txt"])
            editor_payload = json.loads(editor_json.read_text(encoding="utf-8"))
            final_text = final_txt.read_text(encoding="utf-8")

        self.assertEqual(editor_payload["turns"][0]["label"], "Clinician")
        self.assertTrue(editor_payload["finished"])
        self.assertNotIn("SPEAKER_00", editor_payload["speakers"])
        self.assertEqual(editor_payload["turns"][0]["playback_rate"], 0.75)
        self.assertTrue(editor_payload["turns"][0]["bookmarked"])
        self.assertTrue(editor_payload["turns"][0]["timing_reliable"])
        self.assertIn("[00:00]\nClinician: How are you?", final_text)
        self.assertIn("[01:00]\nPatient: Better today.", final_text)

    def test_save_session_round_trips_manual_non_clinical_flag(self) -> None:
        # A turn the user marked unrelated in the WebUI carries unclear_intro;
        # it must survive save (coerce_turn) and surface between the
        # [Unrelated start]/[Unrelated end] markers in the final transcript.
        with tempfile.TemporaryDirectory() as tmpdir:
            store = WEBUI.EditorStore(Path(tmpdir))
            result = store.save_session(
                "visit_nc",
                {
                    "speakers": ["Clinician", "Patient"],
                    "finished": False,
                    "turns": [
                        {
                            "id": "turn-1",
                            "label": "Clinician",
                            "start_sec": 0.2,
                            "end_sec": 1.0,
                            "text": "Just confirming your study ID before we start.",
                            "unclear_intro": True,
                        },
                        {
                            "id": "turn-2",
                            "label": "Patient",
                            "start_sec": 61.0,
                            "end_sec": 62.0,
                            "text": "Better today.",
                        },
                    ],
                },
            )
            editor_payload = json.loads(Path(result["editor_json"]).read_text(encoding="utf-8"))
            final_text = Path(result["final_txt"]).read_text(encoding="utf-8")

        self.assertTrue(editor_payload["turns"][0]["unclear_intro"])
        self.assertFalse(editor_payload["turns"][1]["unclear_intro"])
        self.assertIn("[Unrelated start]:", final_text)
        self.assertIn("[Unrelated end]", final_text)
        self.assertNotIn("[Unclear]:", final_text)
        self.assertLess(final_text.index("[Unrelated start]"), final_text.index("study ID"))
        self.assertLess(final_text.index("study ID"), final_text.index("[Unrelated end]"))

    def test_save_session_appends_revision_events_and_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = WEBUI.EditorStore(root)
            result = store.save_session(
                "visit_revision",
                {
                    "speakers": ["Clinician"],
                    "finished": False,
                    "baseline": {"version": 1, "name": "visit_revision", "speakers": ["Clinician"], "turns": []},
                    "revision_events": [
                        {
                            "kind": "text_edit",
                            "turn_ids": ["turn-1"],
                            "before": {"id": "turn-1", "text": "Hallo"},
                            "after": {"id": "turn-1", "text": "Hello"},
                        }
                    ],
                    "checkpoint": True,
                    "checkpoint_kind": "manual",
                    "turns": [
                        {
                            "id": "turn-1",
                            "label": "Clinician",
                            "start_sec": 0.0,
                            "end_sec": 1.0,
                            "text": "Hello",
                            "words": [
                                {
                                    "id": "word-1",
                                    "text": "Hello",
                                    "start_sec": 0.2,
                                    "end_sec": 0.6,
                                    "timing_source": "inherited",
                                }
                            ],
                        }
                    ],
                },
            )
            revisions_path = Path(result["final_txt"]).with_name("visit_revision_revisions.jsonl")
            snapshots_path = Path(result["final_txt"]).with_name("visit_revision_revision_snapshots.json")
            events = [json.loads(line) for line in revisions_path.read_text(encoding="utf-8").splitlines()]
            snapshots = json.loads(snapshots_path.read_text(encoding="utf-8"))
            loaded = store.load_revisions("visit_revision")

        self.assertEqual(Path(result["final_txt"]).parent, root.resolve() / "data" / "output" / "visit_revision")
        self.assertEqual(result["revision_events"], 1)
        self.assertEqual(events[0]["session"], "visit_revision")
        self.assertEqual(events[0]["kind"], "text_edit")
        self.assertEqual(snapshots["latest"]["turns"][0]["words"][0]["timing_source"], "inherited")
        self.assertEqual(len(snapshots["checkpoints"]), 1)
        self.assertEqual(snapshots["checkpoints"][0]["kind"], "manual")
        self.assertEqual(loaded["events"][0]["turn_ids"], ["turn-1"])

    def test_final_transcript_wraps_unrelated_span_across_minutes(self) -> None:
        # One contiguous unrelated run gets exactly one start and one end marker,
        # placed at the run's boundaries even when it crosses a minute header.
        with tempfile.TemporaryDirectory() as tmpdir:
            store = WEBUI.EditorStore(Path(tmpdir))
            store.save_session(
                "visit_span",
                {
                    "speakers": ["Clinician", "Patient"],
                    "turns": [
                        {"id": "t1", "label": "Clinician", "start_sec": 1.0, "end_sec": 2.0, "text": "How are you feeling?"},
                        {"id": "t2", "label": "Patient", "start_sec": 10.0, "end_sec": 11.0, "text": "Study logistics chat.", "unclear_intro": True},
                        {"id": "t3", "label": "Clinician", "start_sec": 61.0, "end_sec": 62.0, "text": "More study chat.", "unclear_intro": True},
                        {"id": "t4", "label": "Patient", "start_sec": 70.0, "end_sec": 71.0, "text": "Back to symptoms."},
                    ],
                },
            )
            _, transcript = store.final_transcript_for_session("visit_span")

        self.assertEqual(transcript.count("[Unrelated start]"), 1)
        self.assertEqual(transcript.count("[Unrelated end]"), 1)
        order = [
            transcript.index("How are you feeling?"),
            transcript.index("[Unrelated start]"),
            transcript.index("Study logistics chat."),
            transcript.index("[01:00]"),
            transcript.index("More study chat."),
            transcript.index("[Unrelated end]"),
            transcript.index("Back to symptoms."),
        ]
        self.assertEqual(order, sorted(order))

    def test_parse_transcript_text_restores_unrelated_span(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_dir = root / "data" / "output" / "visit_txt"
            session_dir.mkdir(parents=True)
            (session_dir / "visit_txt_aligned_transcript.txt").write_text(
                "\n[00:00]\n"
                "Clinician: Hello there.\n"
                f"{WEBUI.UNRELATED_START_LINE}\n"
                "Patient: Study paperwork talk.\n"
                f"{WEBUI.UNRELATED_END_LINE}\n"
                "Clinician: Any pain today?\n",
                encoding="utf-8",
            )

            turns = WEBUI.EditorStore(root).load_session("visit_txt")["turns"]

        self.assertEqual([turn["text"] for turn in turns], ["Hello there.", "Study paperwork talk.", "Any pain today?"])
        self.assertEqual([turn["unclear_intro"] for turn in turns], [False, True, False])

    def test_finished_transcripts_zip_exports_only_finished_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = WEBUI.EditorStore(root)
            store.save_session(
                "finished_visit",
                {
                    "speakers": ["Clinician"],
                    "finished": True,
                    "turns": [
                        {
                            "id": "turn-1",
                            "label": "Clinician",
                            "start_sec": 0.0,
                            "end_sec": 1.0,
                            "text": "Ready to export.",
                        }
                    ],
                },
            )
            store.save_session(
                "draft_visit",
                {
                    "speakers": ["Patient"],
                    "finished": False,
                    "turns": [
                        {
                            "id": "turn-1",
                            "label": "Patient",
                            "start_sec": 0.0,
                            "end_sec": 1.0,
                            "text": "Still editing.",
                        }
                    ],
                },
            )

            filename, body, count = store.finished_final_transcripts_zip()
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                names = archive.namelist()
                transcript = archive.read("finished_visit_aligned_transcript.txt").decode("utf-8")

        self.assertEqual(filename, "mediscribe_finished_aligned_transcripts.zip")
        self.assertEqual(count, 1)
        self.assertEqual(names, ["finished_visit_aligned_transcript.txt"])
        self.assertIn("Clinician: Ready to export.", transcript)

    def test_finished_transcripts_zip_can_filter_selected_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = WEBUI.EditorStore(root)
            for name in ("visit_one", "visit_two"):
                store.save_session(
                    name,
                    {
                        "speakers": ["Clinician"],
                        "finished": True,
                        "turns": [
                            {
                                "id": "turn-1",
                                "label": "Clinician",
                                "start_sec": 0.0,
                                "end_sec": 1.0,
                                "text": name,
                            }
                        ],
                    },
                )

            filename, body, count = store.finished_final_transcripts_zip(["visit_two"])
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                names = archive.namelist()

        self.assertEqual(filename, "mediscribe_selected_aligned_transcripts.zip")
        self.assertEqual(count, 1)
        self.assertEqual(names, ["visit_two_aligned_transcript.txt"])

    def test_text_only_sessions_mark_synthetic_timing_unreliable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_dir = root / "data" / "output" / "visit_text"
            session_dir.mkdir(parents=True)
            (session_dir / "visit_text_aligned_transcript.txt").write_text(
                "[00:00]\nClinician: Please sit here.\nPatient: Okay.\n",
                encoding="utf-8",
            )

            turns = WEBUI.EditorStore(root).load_session("visit_text")["turns"]

        self.assertFalse(turns[0]["timing_reliable"])
        self.assertTrue(all(word["manual"] for word in turns[0]["words"]))

    def test_final_transcript_export_uses_pipeline_output_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = WEBUI.EditorStore(root)
            store.save_session(
                "visit_export",
                {
                    "speakers": ["Clinician"],
                    "turns": [
                        {
                            "id": "turn-1",
                            "label": "Clinician",
                            "start_sec": 2.0,
                            "end_sec": 3.0,
                            "text": "Please take a",
                        },
                        {
                            "id": "turn-2",
                            "label": "Clinician",
                            "start_sec": 3.0,
                            "end_sec": 4.0,
                            "text": "seat right",
                        },
                        {
                            "id": "turn-3",
                            "label": "Clinician",
                            "start_sec": 4.0,
                            "end_sec": 5.0,
                            "text": "there",
                        }
                    ],
                },
            )

            filename, transcript = store.final_transcript_for_session("visit_export")

        self.assertEqual(filename, "visit_export_aligned_transcript.txt")
        self.assertEqual(transcript, "\n[00:00]\nClinician: Please take a seat right there")

    def test_final_transcript_export_preserves_canonical_turn_boundaries(self) -> None:
        def turn(
            *,
            turn_id: str,
            text: str,
            raw_text: str,
            char_start: int,
            char_end: int,
            start_sec: float,
        ) -> dict[str, object]:
            return {
                "id": turn_id,
                "label": "Clinician",
                "start_sec": start_sec,
                "end_sec": start_sec + 0.5,
                "text": text,
                "words": [
                    {
                        "token_id": f"run:0:{turn_id}",
                        "asr_run_id": "run",
                        "segment_index": 0,
                        "text": text,
                        "raw_text": raw_text,
                        "canonical_char_start": char_start,
                        "canonical_char_end": char_end,
                        "start_sec": start_sec,
                        "end_sec": start_sec + 0.5,
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            store = WEBUI.EditorStore(Path(tmpdir))
            store.save_session(
                "canonical_boundary",
                {
                    "speakers": ["Clinician"],
                    "turns": [
                        turn(
                            turn_id="turn-1",
                            text="well—",
                            raw_text="well—",
                            char_start=0,
                            char_end=5,
                            start_sec=0.0,
                        ),
                        turn(
                            turn_id="turn-2",
                            text="hello",
                            raw_text="hello",
                            char_start=5,
                            char_end=10,
                            start_sec=0.5,
                        ),
                    ],
                },
            )
            _filename, transcript = store.final_transcript_for_session("canonical_boundary")

            store.save_session(
                "canonical_space",
                {
                    "speakers": ["Clinician"],
                    "turns": [
                        turn(
                            turn_id="turn-1",
                            text="Hello",
                            raw_text="Hello",
                            char_start=0,
                            char_end=5,
                            start_sec=0.0,
                        ),
                        turn(
                            turn_id="turn-2",
                            text="world",
                            raw_text=" world",
                            char_start=5,
                            char_end=11,
                            start_sec=0.5,
                        ),
                    ],
                },
            )
            _filename, spaced_transcript = store.final_transcript_for_session(
                "canonical_space"
            )

        self.assertEqual(transcript, "\n[00:00]\nClinician: well—hello")
        self.assertEqual(spaced_transcript, "\n[00:00]\nClinician: Hello world")

    def test_find_audio_prefers_converted_intermediate_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            audio_path = root / "data" / "intermediate" / "visit_c" / "visit_c_converted.wav"
            audio_path.parent.mkdir(parents=True)
            audio_path.write_bytes(b"fake wav")

            found = WEBUI.EditorStore(root).find_audio_path("visit_c")

        self.assertEqual(found, audio_path)

    def test_pipeline_runner_tracks_step_progress_from_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = WEBUI.PipelineRunner(WEBUI.EditorStore(Path(tmpdir)))
            job = WEBUI.PipelineJob(id=1, input_path="visit.wav", command=[])

            runner._append_log(job, "Step 5/9: transcribing with OpenAI Whisper (turbo)...")

        self.assertEqual(job.stage_number, 5)
        self.assertEqual(job.stage_total, 9)
        self.assertEqual(job.stage_name, "transcribing with OpenAI Whisper (turbo)")
        self.assertGreater(job.stage_started, 0)

    def test_clear_selected_removes_only_named_recording_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ("visit_a", "visit_b"):
                (root / "data" / "intermediate" / name).mkdir(parents=True)
                (root / "data" / "output" / name).mkdir(parents=True)
                input_audio = root / "data" / "input" / f"{name}.wav"
                input_audio.parent.mkdir(parents=True, exist_ok=True)
                input_audio.write_bytes(b"audio")
            store = WEBUI.EditorStore(root)

            result = store.clear_selected(["visit_a"])

            self.assertFalse((root / "data" / "intermediate" / "visit_a").exists())
            self.assertFalse((root / "data" / "output" / "visit_a").exists())
            self.assertFalse((root / "data" / "input" / "visit_a.wav").exists())
            self.assertTrue((root / "data" / "intermediate" / "visit_b").exists())
            self.assertEqual(result["removed"], {"input": 1, "intermediate": 1, "output": 1})

    def test_clear_selected_removes_session_artifacts_when_input_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            intermediate_dir = root / "data" / "intermediate" / "visit"
            output_dir = root / "data" / "output" / "visit"
            intermediate_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            legacy_intermediate = root / "data" / "intermediate" / "visit_pipeline_state.json"
            legacy_output = root / "data" / "output" / "visit_aligned_transcript.txt"
            legacy_intermediate.write_text("{}", encoding="utf-8")
            legacy_output.write_text("transcript", encoding="utf-8")
            store = WEBUI.EditorStore(root)

            result = store.clear_selected(["visit"])

            self.assertFalse(intermediate_dir.exists())
            self.assertFalse(output_dir.exists())
            self.assertFalse(legacy_intermediate.exists())
            self.assertFalse(legacy_output.exists())
            self.assertEqual(result["removed"], {"input": 0, "intermediate": 2, "output": 2})

    def test_refresh_ignores_inputs_deleted_after_listing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = WEBUI.EditorStore(root)
            input_root = root / "data" / "input"
            input_root.mkdir(parents=True)
            audio = input_root / "missing_later.wav"
            audio.write_bytes(b"fake")
            store.list_input_audio_files()
            audio.unlink()

            sessions = store.list_sessions()

        self.assertEqual(sessions, [])

    def test_list_sessions_reports_cannot_resume_when_intermediate_lacks_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "data" / "intermediate" / "visit_missing_input"
            state_dir.mkdir(parents=True)
            (state_dir / "visit_missing_input_pipeline_state.json").write_text(
                json.dumps({"state": "awaiting_resume", "reason": "local_llm_unavailable"}),
                encoding="utf-8",
            )

            sessions = WEBUI.EditorStore(root).list_sessions()

        self.assertEqual(sessions[0]["state"], "cannot_resume")
        self.assertIn("Input audio", sessions[0]["state_reason"])

    def test_list_sessions_reports_awaiting_resume_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_audio = root / "data" / "input" / "visit_resume.wav"
            input_audio.parent.mkdir(parents=True)
            input_audio.write_bytes(b"fake")
            state_dir = root / "data" / "intermediate" / "visit_resume"
            state_dir.mkdir(parents=True)
            (state_dir / "visit_resume_pipeline_state.json").write_text(
                json.dumps({"state": "awaiting_resume", "reason": "local_llm_unavailable"}),
                encoding="utf-8",
            )

            sessions = WEBUI.EditorStore(root).list_sessions()

        self.assertEqual(sessions[0]["state"], "awaiting_resume")
        self.assertEqual(sessions[0]["state_reason"], "local_llm_unavailable")

    def test_list_sessions_treats_transcript_output_as_ready_over_stale_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_audio = root / "data" / "input" / "visit_done.wav"
            input_audio.parent.mkdir(parents=True)
            input_audio.write_bytes(b"fake")
            state_dir = root / "data" / "intermediate" / "visit_done"
            output_dir = root / "data" / "output" / "visit_done"
            state_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            (state_dir / "visit_done_pipeline_state.json").write_text(
                json.dumps({"state": "awaiting_resume", "reason": "local_llm_unavailable"}),
                encoding="utf-8",
            )
            (output_dir / "visit_done_aligned_transcript.txt").write_text("Clinician: Ready\n", encoding="utf-8")

            sessions = WEBUI.EditorStore(root).list_sessions()

        self.assertEqual(sessions[0]["state"], "ready")
        self.assertEqual(sessions[0]["state_reason"], "")

    def test_list_sessions_supports_output_artifacts_with_edge_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            intermediate_dir = root / "data" / "intermediate" / "visit_edge "
            output_dir = root / "data" / "output" / "visit_edge "
            intermediate_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            (intermediate_dir / "visit_edge _converted.wav").write_bytes(b"fake wav")
            (output_dir / "visit_edge _aligned_transcript.txt").write_text("Clinician: Ready\n", encoding="utf-8")
            store = WEBUI.EditorStore(root)

            sessions = store.list_sessions()
            session = store.load_session(sessions[0]["name"])

        self.assertEqual(sessions[0]["name"], "visit_edge ")
        self.assertTrue(sessions[0]["has_final"])
        self.assertEqual(sessions[0]["state"], "review_only")
        self.assertEqual(session["audio"]["url"], "/api/session/visit_edge%20/audio")

    def test_load_session_falls_back_to_final_transcript_when_editor_state_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            intermediate_dir = root / "data" / "intermediate" / "visit_edge "
            output_dir = root / "data" / "output" / "visit_edge "
            intermediate_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            (intermediate_dir / "visit_edge _editor.json").write_text(
                json.dumps({"version": 1, "turns": []}),
                encoding="utf-8",
            )
            (output_dir / "visit_edge _aligned_transcript.txt").write_text(
                "\n[00:00]\nClinician: Ready to review.\n",
                encoding="utf-8",
            )

            session = WEBUI.EditorStore(root).load_session("visit_edge ")

        self.assertEqual(session["name"], "visit_edge ")
        self.assertEqual(len(session["turns"]), 1)
        self.assertEqual(session["turns"][0]["text"], "Ready to review.")

    def test_load_session_exposes_stable_audio_metadata_for_bounded_waveforms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            intermediate_dir = root / "data" / "intermediate" / "visit"
            output_dir = root / "data" / "output" / "visit"
            intermediate_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            audio_path = intermediate_dir / "visit_converted.wav"
            audio_path.write_bytes(b"synthetic-audio")
            (output_dir / "visit_aligned_transcript.txt").write_text(
                "Clinician: Ready to review.\n",
                encoding="utf-8",
            )

            session = WEBUI.EditorStore(root).load_session("visit")
            stat = audio_path.stat()

        self.assertEqual(session["audio"]["size_bytes"], stat.st_size)
        self.assertEqual(session["audio"]["version"], f"{stat.st_mtime_ns:x}-{stat.st_size:x}")

    def test_conversation_load_bounds_browser_work_and_avoids_duplicate_render(self) -> None:
        app_js = (SRC_ROOT / "WebUI" / "static" / "app.js").read_text(encoding="utf-8")
        css = (SRC_ROOT / "WebUI" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("MAX_EAGER_WAVEFORM_DURATION_SEC", app_js)
        self.assertIn("MAX_EAGER_WAVEFORM_BYTES", app_js)
        self.assertIn("MAX_WAVEFORM_SAMPLES_PER_BUCKET", app_js)
        self.assertIn("Math.ceil(blockSize / MAX_WAVEFORM_SAMPLES_PER_BUCKET)", app_js)
        self.assertIn("decodeAudioData(arrayBuffer)", app_js)
        self.assertNotIn("decodeAudioData(buffer.slice(0))", app_js)
        self.assertIn("loadSession(recording.name, { activeTab: options.tab })", app_js)
        self.assertIn("setActiveTab(options.activeTab, { skipTurnRender: true })", app_js)
        self.assertIn("!options.skipTurnRender", app_js)
        self.assertIn("const fragment = document.createDocumentFragment()", app_js)
        self.assertIn("fragment.append(row)", app_js)
        self.assertIn("for (const row of rows) observeTurnRow(row)", app_js)
        self.assertIn("queueWordStripAlignment", app_js)
        self.assertIn("new IntersectionObserver", app_js)
        self.assertIn("visibleTurnRows", app_js)
        self.assertIn("content-visibility: auto", css)
        self.assertIn("contain-intrinsic-size: auto", css)

    def test_static_editor_matches_expected_surface(self) -> None:
        html = (SRC_ROOT / "WebUI" / "static" / "index.html").read_text(encoding="utf-8")
        app_js = (SRC_ROOT / "WebUI" / "static" / "app.js").read_text(encoding="utf-8")
        css = (SRC_ROOT / "WebUI" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="pipelinePanel"', html)
        self.assertIn('class="app-tabs"', html)
        self.assertIn('id="dashboardView"', html)
        self.assertIn('id="processingView"', html)
        self.assertIn('id="reviewView"', html)
        self.assertIn('id="revisionsView"', html)
        self.assertIn('id="settingsView"', html)
        self.assertIn('id="recordingTable"', html)
        self.assertIn('id="processingBacklogList"', html)
        self.assertIn('id="pipelineFileGrid"', html)
        self.assertIn('id="pipelineLanes"', html)
        self.assertIn('id="releaseWorker"', html)
        self.assertNotIn('id="pipelineQueueList"', html)
        self.assertIn('id="runInputFolder"', html)
        self.assertIn("Run All Unprocessed", html)
        self.assertIn('id="importAudioButton"', html)
        self.assertIn('id="refreshSessions"', html)
        self.assertIn('id="clearCache"', html)
        # The review toolbar is keyboard-first: Undo/Redo/Split/Mark buttons were
        # removed in favor of shortcuts and the per-row hover flags.
        self.assertNotIn('id="toggleBookmark"', html)
        self.assertNotIn('id="undoButton"', html)
        self.assertNotIn('id="redoButton"', html)
        self.assertNotIn('id="splitButton"', html)
        self.assertIn('id="nextBookmark"', html)
        self.assertIn('id="showBookmarks"', html)
        self.assertIn('id="audioPlayer" class="native-audio-player" controls', html)
        self.assertIn('id="speedSlider"', html)
        self.assertIn('id="speedValue"', html)
        self.assertIn('id="openSpeakerDialog"', html)
        self.assertIn("Speaker Tools", html)
        self.assertNotIn("Add Speaker", html)
        self.assertNotIn("Active turn speaker", html)
        self.assertIn('id="openBulkDialog"', html)
        self.assertIn('id="toggleTurnSelectionMode"', html)
        self.assertIn(">Select All<", html)
        self.assertNotIn('id="bulkSelectionCount"', html)
        self.assertIn('id="showBookmarks" title="Show only bookmarked turns" hidden', html)
        self.assertIn('id="searchCount" class="search-count" hidden', html)
        self.assertIn('id="toggleFinished"', html)
        self.assertIn('id="exportTranscript"', html)
        self.assertIn('id="exportAllFinished"', html)
        self.assertIn('id="selectAllRecordings"', html)
        self.assertIn('id="clearRecordingSelection"', html)
        self.assertIn('id="reprocessSelectedRecordings"', html)
        self.assertIn('id="reprocessSelectedInProcessing"', html)
        self.assertIn('id="showRevisions"', html)
        self.assertIn('id="revisionPanel"', html)
        self.assertIn('id="restoreRevisionBefore"', html)
        self.assertIn('id="restoreRevisionAfter"', html)
        self.assertIn('id="playPauseButton"', html)
        self.assertIn('id="jumpBack10"', html)
        self.assertIn('id="jumpForward10"', html)
        self.assertIn('id="currentTimeLabel"', html)
        self.assertIn('id="durationLabel"', html)
        self.assertIn('id="timelineCanvas"', html)
        self.assertIn('id="settingRoleMenuBehavior"', html)
        self.assertNotIn('id="settingPlaybackEngine"', html)
        self.assertNotIn('id="settingSoundTouchBuffer"', html)
        self.assertNotIn('id="settingAudioEngineStatus"', html)
        self.assertNotIn('id="settingPreservePitch"', html)
        self.assertIn('id="settingVisualLatency"', html)
        self.assertIn('id="settingVisualLatencyValue"', html)
        self.assertIn('id="settingAutoScrollDelay"', html)
        self.assertIn('id="settingAutoScrollDelayValue"', html)
        self.assertIn('id="settingClickTurnPlays"', html)
        self.assertIn('id="settingFollowAudioTurn"', html)
        self.assertIn('id="settingShowMergeButtons"', html)
        self.assertNotIn('id="settingLoopAutoPlay"', html)
        self.assertIn('id="settingSpaceTogglesPlayback"', html)
        self.assertIn('class="shortcut-list"', html)
        self.assertIn("<kbd>Q</kbd><span>Play previous turn</span>", html)
        self.assertIn("<kbd>W</kbd><span>Select hovered turn</span>", html)
        self.assertIn("<kbd>E</kbd><span>Play next turn</span>", html)
        self.assertIn("<kbd>M</kbd><span>Bookmark hovered or active turn</span>", html)
        self.assertIn("<kbd>N</kbd>", html)
        self.assertIn("<kbd>X</kbd><span>Start, then end, a span of turns to delete (undo with Ctrl+Z)</span>", html)
        self.assertIn("<kbd>S</kbd><span>Split at hovered word bar into a new turn</span>", html)
        self.assertNotIn("SoundTouch high quality", html)
        self.assertIn('id="modalBackdrop"', html)
        self.assertIn('id="modalBody"', html)
        self.assertIn('class="hidden-control"', html)
        self.assertNotIn('class="topbar-actions"', html)
        self.assertNotIn('class="recording-field"', html)
        self.assertNotIn('id="resumeSession"', html)
        self.assertNotIn('id="runSelectedInput"', html)
        self.assertNotIn("Playback Settings", html)
        self.assertNotIn("playLineButton", html)
        self.assertNotIn('id="mergeButton"', html)
        self.assertNotIn("loopAB", html)
        self.assertNotIn("turnSpeedSelect", html)
        self.assertNotIn("setLoopA", html)
        self.assertNotIn("setLoopB", html)

        self.assertIn("confirmPipelineRun", app_js)
        self.assertIn("showModal", app_js)
        self.assertIn("runAllUnprocessed", app_js)
        self.assertIn("reprocessRecordings", app_js)
        self.assertIn("reprocessableRecordings", app_js)
        self.assertIn("reprocess: true", app_js)
        self.assertIn("unprocessedRecordings", app_js)
        self.assertIn("recordingCannotResume", app_js)
        self.assertIn("recordingReviewOnly", app_js)
        self.assertIn("recordingProcessingVisible", app_js)
        self.assertIn("sessionNameForRecording", app_js)
        self.assertIn("const name = sessionNameForRecording(session);", app_js)
        self.assertNotIn("const name = cleanText(session.name);", app_js)
        self.assertIn("inputPathMatches", app_js)
        self.assertIn("formatAudioLength", app_js)
        self.assertIn("formatFileSize", app_js)
        self.assertIn("recordingDisplayName", app_js)
        self.assertIn("loadedAudioDisplayName", app_js)
        # Header status line is gone: errors surface in the modal, progress text is silent.
        self.assertNotIn('id="statusText"', html)
        self.assertIn("function showErrorNotice(error)", app_js)
        self.assertIn("async function confirmDuplicateImports(duplicates)", app_js)
        self.assertIn("&allow_duplicate=1", app_js)
        self.assertIn('"Length"', app_js)
        self.assertIn('"Size"', app_js)
        self.assertNotIn("window.confirm", app_js)
        self.assertNotIn("window.prompt", app_js)
        self.assertIn("setActiveTab", app_js)
        self.assertIn("renderDashboard", app_js)
        self.assertIn("recordingStatus", app_js)
        self.assertIn("renderProcessing", app_js)
        self.assertIn("processingBacklogList", app_js)
        self.assertIn("renderPipelineFiles", app_js)
        self.assertIn("renderLanes", app_js)
        self.assertIn("/api/pipeline/worker/release", app_js)
        self.assertNotIn("PIPELINE_STAGES", app_js)
        self.assertIn("/final-transcript", app_js)
        self.assertIn("/final-transcripts.zip", app_js)
        self.assertIn("/revisions", app_js)
        self.assertIn("revision_events", app_js)
        self.assertIn("revisionRestorePair", app_js)
        self.assertIn("restoreRevisionSnapshot", app_js)
        self.assertIn("restoreSelectedRevisionSide", app_js)
        self.assertIn("revision_restore", app_js)
        self.assertIn("TIMED_WORD_CLIPBOARD_TYPE", app_js)
        self.assertIn("globalWordAtTime", app_js)
        self.assertIn("timelineScrub", app_js)
        self.assertIn("timelineDisplayTime", app_js)
        self.assertIn("timelineTimeFromPointer", app_js)
        self.assertIn("beginTimelineScrub", app_js)
        self.assertIn("moveTimelineScrub", app_js)
        self.assertIn("finishTimelineScrub", app_js)
        self.assertIn('els.timeline.addEventListener("pointerdown", beginTimelineScrub)', app_js)
        self.assertIn('els.timeline.addEventListener("pointermove", moveTimelineScrub)', app_js)
        self.assertIn('els.timeline.addEventListener("pointerup", finishTimelineScrub)', app_js)
        self.assertIn("setPointerCapture", app_js)
        self.assertIn("releasePointerCapture", app_js)
        self.assertIn("if (els.timeline) {", app_js)
        self.assertIn("visualLatencySec: 0.2", app_js)
        self.assertIn("visualLatencySec: clampNumber(payload.visualLatencySec, 0, 0.5", app_js)
        self.assertIn('updateSetting("visualLatencySec"', app_js)
        self.assertIn("autoScrollDelaySec: 0.65", app_js)
        self.assertIn("autoScrollDelaySec: clampNumber(payload.autoScrollDelaySec, 0, 2", app_js)
        self.assertIn('updateSetting("autoScrollDelaySec"', app_js)
        self.assertIn("autoScrollTargetDelayMs", app_js)
        self.assertIn("showMergeButtons: false", app_js)
        self.assertIn("showMergeButtons: payload.showMergeButtons === true", app_js)
        self.assertIn('updateSetting("showMergeButtons"', app_js)
        self.assertIn("if (state.settings.showMergeButtons)", app_js)
        self.assertIn("visualAudioTime", app_js)
        self.assertIn("exportTranscript", app_js)
        self.assertIn("exportAllFinished", app_js)
        self.assertIn("finishedSessionCount", app_js)
        self.assertIn("appendFinishedMarker", app_js)
        self.assertIn("toggleTurnBookmark", app_js)
        self.assertIn("bookmarkedTurns", app_js)
        self.assertIn("matchExistingWords", app_js)
        self.assertIn("synthesizeInsertedWord", app_js)
        self.assertIn("deletedWordSlots", app_js)
        self.assertIn("word-timing-strip", app_js)
        # Line wrapping measures real pixel widths, rewraps live while typing,
        # and the word strip left-aligns under the text instead of centering.
        self.assertIn("turnTextMetrics", app_js)
        self.assertIn("textMeasureContext", app_js)
        self.assertIn("turnLineAvailableWidthPx", app_js)
        self.assertIn("TURN_ROW_TEXT_OVERHEAD_PX", app_js)
        self.assertIn("maybeRewrapTurnLines", app_js)
        self.assertIn("spaceWidthPx", app_js)
        self.assertIn("textRect.left - stripRect.left", app_js)
        self.assertIn("WORD_STRIP_TEXT_PADDING_PX", app_js)
        self.assertIn("alignWordStripToText", app_js)
        self.assertIn("alignAllWordStrips", app_js)
        self.assertIn("renderTurnLines", app_js)
        self.assertIn("turnLineSegments", app_js)
        self.assertIn("splitTurnLineAtCaret", app_js)
        self.assertIn("splitTurnAtLineCaret", app_js)
        self.assertIn("splitTurnAtBoundary", app_js)
        self.assertIn("turnWordSplitIndexForLine", app_js)
        self.assertIn("renderSplitTurnPatch", app_js)
        self.assertIn("renderMergeTurnPatch", app_js)
        self.assertIn("syncSplitPlaybackToTurn", app_js)
        self.assertIn("playbackTurnHold", app_js)
        self.assertIn("reviewAutoScroll", app_js)
        self.assertIn("AUTO_SCROLL_USER_COOLDOWN_MS", app_js)
        self.assertIn("AUTO_SCROLL_TEXT_EXIT_COOLDOWN_MS", app_js)
        self.assertIn("AUTO_SCROLL_TARGET_COOLDOWN_MS", app_js)
        self.assertIn("PROGRAMMATIC_SCROLL_GRACE_MS", app_js)
        self.assertIn("ACTIVE_TURN_SCROLL_FRACTION = 1 / 3", app_js)
        self.assertIn("scrollTurnRowIntoFocus", app_js)
        self.assertIn("listRect.height * ACTIVE_TURN_SCROLL_FRACTION", app_js)
        self.assertIn("noteTurnListScroll", app_js)
        self.assertIn("pauseAutoScrollForTextFocus", app_js)
        self.assertIn("resumeAutoScrollAfterTextFocus", app_js)
        self.assertIn("shouldAutoScrollPlayingTurn", app_js)
        self.assertIn('els.turnList.addEventListener("scroll", noteTurnListScroll', app_js)
        self.assertIn("const wasPlaying = !audioIsPaused();", app_js)
        self.assertIn("recordTurnPatchUndo", app_js)
        self.assertIn('type: "turn_patch"', app_js)
        self.assertIn("inverseHistorySnapshot", app_js)
        self.assertIn('element.dataset.skipBlurSync = "true"', app_js)
        self.assertIn('text.dataset.skipBlurSync === "true"', app_js)
        self.assertIn("wordsMatchText", app_js)
        self.assertIn("event.shiftKey", app_js)
        self.assertIn("splitTurnAtLineCaret(turn, element)", app_js)
        self.assertIn("words: afterWords", app_js)
        self.assertIn("text.textContent = segment.text", app_js)
        # The section boundary / A-B loop feature was removed outright.
        self.assertNotIn("turn-boundary", app_js)
        self.assertNotIn("section-controls", app_js)
        self.assertNotIn("loopAB", app_js)
        self.assertNotIn("loopAutoPlay", app_js)
        self.assertNotIn("toggleSectionLoop", app_js)
        self.assertNotIn("setSectionSpeed", app_js)
        self.assertIn("playTurn(turn)", app_js)
        self.assertIn("setGlobalPlaybackRate", app_js)
        self.assertIn("textEditPlaybackSlow", app_js)
        self.assertIn("roleMenuPlaybackSlow", app_js)
        self.assertIn("roleMenuBehavior", app_js)
        self.assertIn("clickTurnPlays", app_js)
        self.assertIn("followAudioTurn", app_js)
        self.assertIn("textEditSlowsAudio", app_js)
        self.assertIn("wordDragSlowsAudio", app_js)
        self.assertIn("spaceTogglesPlayback", app_js)
        self.assertIn("shouldSpaceTogglePlayback", app_js)
        self.assertIn("togglePlaybackFromShortcut", app_js)
        self.assertIn("!isTextEntryTarget(event.target)", app_js)
        self.assertIn('window.addEventListener("keyup"', app_js)
        self.assertIn("wordClickPlays", app_js)
        self.assertIn("computeLineDiff", app_js)
        self.assertIn("els.searchCount.hidden = total === 0", app_js)
        self.assertIn("clear-selected", app_js)
        self.assertIn("bindRoleMenuSpeed", app_js)
        self.assertIn("beginTextEditPlayback", app_js)
        self.assertIn("openSpeakerDialog", app_js)
        self.assertIn("openBulkDialog", app_js)
        self.assertIn("changeSpeakerScope", app_js)
        self.assertIn("turnSelectionMode", app_js)
        self.assertIn("toggleTurnSelectionMode", app_js)
        self.assertIn("async function toggleFinished()", app_js)
        self.assertIn("await saveSession();", app_js)
        self.assertIn('els.toggleFinished.addEventListener("click", () => toggleFinished().catch((error) => showErrorNotice(error)))', app_js)
        self.assertIn('els.turnList.classList.toggle("selection-mode", state.turnSelectionMode)', app_js)
        self.assertIn('turnNumber.className = "turn-number"', app_js)
        self.assertIn('turnNumber.type = "button"', app_js)
        self.assertIn("turnNumber.textContent = turnIndex >= 0 ? String(turnIndex + 1)", app_js)
        self.assertIn("selectedTurnIds", app_js)
        self.assertIn("applyBulkSpeakerToSelected", app_js)
        self.assertIn("deleteTurns", app_js)
        self.assertIn("renderSingleTurnPatch", app_js)
        self.assertIn("renderChangedTurnsPatch", app_js)
        self.assertIn("renderTurnPatchRestore", app_js)
        self.assertIn("renderTurnPatchRestore(", app_js)
        self.assertIn("|| renderChangedTurnsPatch(beforeTurns, state.turns, state.activeTurnId)", app_js)
        self.assertIn("turnsHaveSameOrder", app_js)
        self.assertIn("changedTurnIds", app_js)
        self.assertIn("renderWordMovePatch", app_js)
        self.assertIn("removeTurnRowPatch", app_js)
        self.assertNotIn("refreshTurnBoundaryLabelsFor", app_js)
        self.assertIn("renderTurns({ scrollActive: false, scrollAnchorTurnId: target.id })", app_js)
        self.assertIn("mergeTurnDown", app_js)
        self.assertIn('mergeUpButton.textContent = "↑ Merge"', app_js)
        self.assertIn('mergeDownButton.textContent = "↓ Merge"', app_js)
        self.assertIn("handleReviewTabShortcut", app_js)
        # Tab supports single-step and dwell-timed hold-to-cycle modes.
        self.assertIn("if (event.repeat) return true;", app_js)
        # Bookmark / unrelated marking: hover flags + M / N shortcuts, where N
        # drives a start/end span flow with an Esc cancel.
        self.assertIn("handleTurnFlagShortcut", app_js)
        self.assertIn("markUnrelatedSpan", app_js)
        self.assertIn("setTurnsUnrelated", app_js)
        self.assertIn("clearUnrelatedPending", app_js)
        self.assertIn("unrelated-pending-mode", app_js)
        self.assertIn("turn-flags", app_js)
        self.assertIn("unrelated_mark", app_js)
        self.assertNotIn("toggleTurnNonClinical", app_js)
        # Turn deletion reuses the same start/end span flow on X: a pending
        # start, an "end here" second press, Esc cancel, and undoable removal
        # behind a confirmation that lists the span, speakers, and turn text.
        self.assertIn("deleteTurnSpan", app_js)
        self.assertIn("clearDeletePending", app_js)
        self.assertIn("delete-pending-mode", app_js)
        self.assertIn('key !== "m" && key !== "n" && key !== "x"', app_js)
        self.assertIn("confirmTurnDeletion", app_js)
        self.assertIn("delete-preview-row", app_js)
        self.assertIn("DELETE_PREVIEW_MAX_ROWS", app_js)
        # Refresh is retried, renders partial data, and shows a busy spinner.
        self.assertIn("setRefreshBusy", app_js)
        self.assertIn("loadListing", app_js)
        self.assertIn("isDiarizationSpeaker", app_js)
        self.assertIn("normalizeSpeakerList", app_js)
        self.assertIn("speakerListFromValues", app_js)
        self.assertNotIn("chooseTranscriptBoundary", app_js)
        self.assertIn("onTurnDragStart", app_js)
        self.assertIn("onWordPointerDown", app_js)
        self.assertNotIn("handleReviewMergeShortcut", app_js)
        self.assertNotIn('if (key === "w") mergeTurnUp(turn.id);', app_js)
        self.assertIn("handleHoveredWordShortcut", app_js)
        self.assertNotIn("handleHoveredWordBoundaryShortcut", app_js)
        self.assertNotIn("handleSelectedWordBoundaryShortcut", app_js)
        self.assertNotIn("handleSelectedWordEnterShortcut", app_js)
        self.assertIn("onWordPointerUp", app_js)
        self.assertIn("activateWordBar", app_js)
        self.assertIn("selectedSingleWordRef", app_js)
        self.assertIn("hoveredWordBarRef", app_js)
        self.assertIn('document.querySelector(".word-chip:hover")', app_js)
        self.assertNotIn("wordClickSeekTime", app_js)
        self.assertNotIn("WORD_CLICK_PREROLL_SEC", app_js)
        self.assertIn("setAudioTime(seekTime)", app_js)
        self.assertIn("state.settings.wordClickPlays && els.audio.src", app_js)
        self.assertIn("handleTurnPlaybackShortcut", app_js)
        self.assertIn('if (key !== "q" && key !== "e" && key !== "w") return false;', app_js)
        self.assertIn('if (key === "q") return playRelativeTurn(-1);', app_js)
        self.assertIn('if (key === "e") return playRelativeTurn(1);', app_js)
        self.assertIn("return selectHoveredTurn();", app_js)
        self.assertIn("turnAtTime", app_js)
        self.assertIn("activePlaybackTurnIndex", app_js)
        self.assertIn("playRelativeTurn", app_js)
        self.assertIn('document.querySelector(".turn-row:hover")', app_js)
        self.assertIn("selectHoveredTurn", app_js)
        self.assertNotIn('ctx.fillStyle = speakerColor(turn.label || "Unknown")', app_js)
        self.assertNotIn("ctx.fillRect(x, bandY, w", app_js)
        self.assertIn("selectSingleWord", app_js)
        self.assertIn("clearWordSelection", app_js)
        self.assertNotIn("moveSelectedWordBoundary", app_js)
        self.assertIn("moveWordBoundaryToAdjacentTurn", app_js)
        self.assertIn("word_boundary_move", app_js)
        self.assertIn("splitTurnAtWordIndex", app_js)
        self.assertIn('if (key !== "a" && key !== "d" && key !== "s") return false;', app_js)
        self.assertIn('splitTurnAtWordIndex(ref.turn, ref.index);', app_js)
        self.assertIn("const focusText = options.focusText !== false", app_js)
        self.assertIn("state.pendingFocusTurnId = focusText ? newTurn.id : \"\"", app_js)
        self.assertIn("renderSplitTurnPatch(turn, newTurn, { focusText })", app_js)
        self.assertIn("}, { focusText: false });", app_js)
        self.assertIn('moveWordBoundaryToAdjacentTurn(ref.turn, ref.index, key === "a" ? "up" : "down")', app_js)
        self.assertIn("sourceWillBeRemoved ? 1 : 2", app_js)
        self.assertIn('if (event.key === "Tab") {', app_js)
        self.assertIn("element.blur();", app_js)
        self.assertNotIn("move_text_to_previous_turn", app_js)
        self.assertIn("textSplitAtLineCaret", app_js)
        self.assertIn("function cycleTurnSpeaker(turn, reverse = false, options = {})", app_js)
        self.assertIn("if (options.fromShortcut) endRoleMenuPlayback();", app_js)
        self.assertIn("focusText: options.focusText === true", app_js)
        self.assertIn("ROLE_LOCAL_BOUNDARY_GAP_SEC = 180", app_js)
        self.assertIn("ROLE_LOCAL_DECAY_SEC = 75", app_js)
        self.assertIn("ROLE_CYCLE_CONTEXT_SEC = ROLE_LOCAL_DECAY_SEC * 2", app_js)
        self.assertIn("ROLE_GLOBAL_WEIGHT = 0.35", app_js)
        self.assertIn("roleCandidates", app_js)
        self.assertIn("localConversationSpeakers", app_js)
        self.assertIn("Math.abs(turnCenterSec(state.turns[cursor]) - focusTime) > ROLE_CYCLE_CONTEXT_SEC", app_js)
        self.assertIn("usedSpeakerSet", app_js)
        self.assertIn("!DEFAULT_SPEAKERS.includes(speaker)", app_js)
        self.assertIn("globalSpeakerScores", app_js)
        self.assertIn("localSpeakerScores", app_js)
        self.assertIn("roleCycleOrder", app_js)
        self.assertIn("turnGapSec", app_js)
        self.assertIn("Math.exp(-distance / ROLE_LOCAL_DECAY_SEC)", app_js)
        self.assertIn("ROLE_LOCAL_BOUNDARY_GAP_SEC) break", app_js)
        self.assertIn("speakerCycle(turn.label, reverse, turn)", app_js)
        # A split recommends the most likely other speaker independently (no cycle drift).
        self.assertIn("label: recommendedSplitSpeaker(turn)", app_js)
        self.assertIn("function recommendedSplitSpeaker(turn)", app_js)
        self.assertIn("...state.speakers,\n    ...state.turns.map((turn) => turn.label)", app_js)
        self.assertNotIn('filter((speaker) => !["Clinician", "Patient"].includes(speaker))', app_js)
        self.assertIn("cycleTurnSpeaker(turn, event.shiftKey, { fromShortcut: true })", app_js)
        self.assertIn("WORD_RANGE_HOLD_MS = 90", app_js)
        self.assertIn("WORD_RANGE_MOVE_TOLERANCE = 10", app_js)
        self.assertIn("lastWordSelectionTurnId", app_js)
        self.assertIn("wordSelectionStripsForTurn", app_js)
        self.assertIn("clearWordSelectionClassesForTurn", app_js)
        self.assertIn("beginWordRangeSelection", app_js)
        self.assertIn("onWordRangePointerMove", app_js)
        self.assertIn("startedAt: performance.now()", app_js)
        self.assertIn("performance.now() - pending.startedAt < WORD_RANGE_HOLD_MS", app_js)
        self.assertIn("dropWordIndex", app_js)
        self.assertIn("timedWordGapPx", app_js)
        self.assertIn('classList.remove("selected")', app_js)
        self.assertNotIn("continues-left", app_js)
        self.assertNotIn("continues-right", app_js)
        self.assertIn("event.stopPropagation()", app_js)
        self.assertIn("focus({ preventScroll: true })", app_js)
        self.assertIn("restoreTurnListScroll", app_js)
        # Opening a transcript resets the list scroll; it must not inherit the
        # position left over from the previously reviewed recording.
        self.assertIn("resetTurnListScroll", app_js)
        self.assertIn("renderTurns();\n  resetTurnListScroll();", app_js)
        self.assertIn("scrollAnchorTurnId", app_js)
        self.assertIn("anchorOffsetTop", app_js)
        self.assertIn("timingReliable", app_js)
        self.assertIn("wordAtTime", app_js)
        self.assertIn("ctx.arc(playheadX", app_js)
        self.assertNotIn("cursor: ew-resize", css)
        self.assertIn("touch-action: none", css)
        self.assertNotIn("nearestTurnBoundary", app_js)
        self.assertNotIn("chooseTimelineBoundary", app_js)
        self.assertNotIn("drawSegments", app_js)
        self.assertNotIn("setLineDash", app_js)
        self.assertNotIn("playActiveLine", app_js)
        self.assertNotIn("updateTurnSpeedControl", app_js)
        self.assertNotIn(".bookmark-button", css)
        self.assertIn(".turn-flag", css)
        self.assertIn("#refreshSessions.refreshing", css)
        self.assertIn(".app-tabs", css)
        self.assertIn(".dashboard-view", css)
        self.assertIn(".recording-table", css)
        self.assertIn(".hidden-control", css)
        self.assertIn(".processing-grid", css)
        self.assertIn(".file-card", css)
        self.assertIn(".pipeline-lanes", css)
        self.assertIn(".backlog-item", css)
        self.assertIn(".status-badge", css)
        self.assertIn("flex-wrap: nowrap", css)
        self.assertIn("overflow-x: auto", css)
        self.assertNotIn(".bulk-selection-count", css)
        self.assertIn(".turn-select-checkbox", css)
        self.assertIn(".speed-control", css)
        self.assertIn(".turn-number", css)
        self.assertIn("grid-template-columns: 34px 68px 154px minmax(240px, 1fr);", css)
        self.assertIn(".turn-list.selection-mode .turn-row", css)
        self.assertIn("grid-template-columns: 34px 28px 68px 154px minmax(240px, 1fr);", css)
        self.assertIn(".turn-merge-actions", css)
        self.assertIn(".turn-merge-button", css)
        self.assertIn(".modal-field", css)
        self.assertIn(".modal-note", css)
        self.assertIn(".shortcut-list", css)
        self.assertIn(".turn-flag.delete-flag.pending", css)
        self.assertIn(".turn-list.delete-pending-mode .delete-flag .flag-label-pending", css)
        self.assertIn(".delete-preview", css)
        self.assertIn(".delete-preview-text", css)
        self.assertNotIn(".turn-all-drag", css)
        self.assertIn(".turn-line", css)
        self.assertIn("white-space: nowrap", css)
        self.assertIn(".word-strip.selecting", css)
        self.assertIn(".word-chip.drop-after", css)
        self.assertIn(".word-chip::after", css)
        self.assertIn(".word-chip:hover::after", css)
        self.assertIn("height: 6px", css)
        self.assertIn("box-shadow: 0 2px 8px", css)
        self.assertNotIn(".word-chip.selected.continues-left::after", css)
        self.assertNotIn(".word-chip.selected.continues-right::after", css)
        self.assertIn(".word-strip.selecting .word-chip::after", css)
        self.assertIn("transition: none", css)
        self.assertIn("touch-action: none", css)
        self.assertIn(".word-strip-content", css)
        self.assertIn("transform: translateX(var(--word-strip-offset, 0px));", css)
        self.assertRegex(css, r"\.word-chip \{[^}]*min-width: 0;")
        self.assertIn("margin-left: var(--word-gap, 0.25em);", css)
        self.assertIn("border: 0;", css)
        self.assertNotIn("min-width: 0.75em;", css)
        self.assertIn(".word-drag-active", css)
        self.assertNotIn("@keyframes wordBarPulse", css)
        self.assertIn(".modal-field-control", css)
        self.assertIn(".finished-marker", css)
        self.assertIn(".revision-panel", css)
        self.assertIn(".revision-actions", css)
        self.assertIn(".revision-compare", css)
        self.assertIn(".revision-sidebar", css)
        self.assertIn(".diff-row.added", css)
        self.assertIn(".native-audio-player", css)
        self.assertIn(".transport-card", css)
        self.assertIn(".transport-row", css)
        self.assertIn(".timeline-canvas", css)
        self.assertIn(".settings-grid", css)
        self.assertIn(".modal-backdrop", css)
        self.assertIn(".modal-confirm-danger", css)
        self.assertNotIn(".turn-boundary", css)
        self.assertNotIn(".section-controls", css)
        self.assertIn(".timeline-canvas", css)


class WebUIRefreshRobustnessTests(unittest.TestCase):
    """The dashboard listing endpoints must survive concurrent access and
    corrupt cache files instead of returning 500s until a lucky retry."""

    @staticmethod
    def _write_wav(path: Path, seconds: float = 0.25) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\0\0" * int(8000 * seconds))

    def test_write_json_replaces_atomically_without_temp_leftovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "payload.json"
            WEBUI.write_json(target, {"value": 1})
            WEBUI.write_json(target, {"value": 2})
            payload = json.loads(target.read_text(encoding="utf-8"))
            leftovers = [path.name for path in Path(tmpdir).iterdir() if path.name != "payload.json"]

        self.assertEqual(payload, {"value": 2})
        self.assertEqual(leftovers, [])

    def test_corrupt_editor_json_falls_back_to_debug_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_dir = root / "data" / "intermediate" / "visit"
            session_dir.mkdir(parents=True)
            (session_dir / "visit_editor.json").write_text('{"turns": [truncat', encoding="utf-8")
            (session_dir / "visit_debug.json").write_text(
                json.dumps({"merged_turns": [{"final_role": "Clinician", "start_sec": 0.0, "end_sec": 1.0, "text": "Hello."}]}),
                encoding="utf-8",
            )
            store = WEBUI.EditorStore(root)

            sessions = store.list_sessions()
            session = store.load_session("visit")

        self.assertEqual(sessions[0]["name"], "visit")
        self.assertFalse(sessions[0]["finished"])
        self.assertEqual(session["turns"][0]["text"], "Hello.")

    def test_audio_duration_caches_ffprobe_probes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio = Path(tmpdir) / "visit.mp3"
            audio.write_bytes(b"not-really-audio")
            calls: list[Any] = []

            def fake_run(*args: Any, **kwargs: Any) -> Any:
                calls.append(args)
                return types.SimpleNamespace(stdout="2.5\n")

            with mock.patch.object(WEBUI, "resolve_ffprobe", return_value="ffprobe"), mock.patch.object(
                WEBUI.subprocess, "run", side_effect=fake_run
            ):
                first = WEBUI.audio_duration_sec(audio)
                second = WEBUI.audio_duration_sec(audio)
                audio.write_bytes(b"different-audio-bytes")
                os.utime(audio, (1234567890, 1234567890))
                third = WEBUI.audio_duration_sec(audio)

        self.assertEqual((first, second, third), (2.5, 2.5, 2.5))
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
