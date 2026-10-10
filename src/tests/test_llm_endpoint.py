"""LLM endpoint authentication, request compatibility, and error handling."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mediscribe_v2 import common
from WebUI import server as webui


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.api_key = "test-key"
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, payload):
                owner.requests.append((self.command, self.path, self.headers.get("Authorization"), payload))
                expected = f"Bearer {owner.api_key}" if owner.api_key else None
                if self.headers.get("Authorization") != expected:
                    self.send_error(401)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

            def do_GET(self):
                self.respond(None)

            def do_POST(self):
                self.respond(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.http.server_port}/gateway/v1"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def test_authenticated_endpoint_receives_key_on_checks_and_requests(self):
        reply = common.call_llm("hello", base_url=self.base_url + "/", model="test-model",
                                api_key=self.api_key, timeout_sec=2)
        self.assertEqual(reply, "{}")
        self.assertEqual([(method, path, key) for method, path, key, _ in self.requests], [
            ("GET", "/gateway/v1/models", "Bearer test-key"),
            ("POST", "/gateway/v1/chat/completions", "Bearer test-key"),
        ])
        payload = self.requests[-1][3]
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
        self.assertNotIn("chat_template_kwargs", payload)

    def test_endpoint_without_authentication_receives_no_bearer_placeholder(self):
        self.api_key = ""
        common.call_llm("hello", base_url=self.base_url, model="test-model", api_key="", timeout_sec=2)
        self.assertTrue(all(key is None for _, _, key, _ in self.requests))

    def test_authentication_failure_is_immediate(self):
        with mock.patch.object(common.time, "sleep") as sleep:
            with self.assertRaisesRegex(common.LLMUnavailableError, "HTTP 401"):
                common.call_llm("hello", base_url=self.base_url, model="test-model", api_key="wrong", timeout_sec=2)
        sleep.assert_not_called()
        self.assertEqual(len(self.requests), 1)

    def test_webui_checks_the_configured_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = webui.PipelineRunner(webui.EditorStore(Path(directory)),
                                         llm_base_url=self.base_url, llm_model="test-model")
            with mock.patch.object(webui, "LLM_API_KEY_DEFAULT", self.api_key), mock.patch.object(runner, "_append_log"):
                self.assertTrue(runner._ensure_llm_ready(object()))
        self.assertEqual(self.requests[0][1], "/gateway/v1/models")
        self.assertEqual(self.requests[0][2], "Bearer test-key")

    def test_webui_fails_before_starting_a_worker_if_endpoint_is_unconfigured(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = webui.PipelineRunner(webui.EditorStore(Path(directory)), llm_base_url="", llm_model="")
            with mock.patch.object(runner, "_append_log"), mock.patch.object(runner, "_fail_job_files") as fail, \
                    mock.patch.object(runner, "_ensure_worker") as worker:
                runner._launch_job(object())
        fail.assert_called_once()
        worker.assert_not_called()
        self.assertEqual(self.requests, [])

    def test_https_url_and_custom_base_path_are_preserved(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"{}"}}]}'
        with mock.patch.object(common, "_urlopen", return_value=response) as opened:
            common.call_llm("hello", base_url="https://api.example.com/custom/v2", model="test-model",
                            api_key="key", timeout_sec=2)
        self.assertEqual([call.args[0].full_url for call in opened.call_args_list], [
            "https://api.example.com/custom/v2/models",
            "https://api.example.com/custom/v2/chat/completions",
        ])

    def test_invalid_configuration_is_rejected(self):
        for url, model in [("", "m"), ("file:///tmp/api", "m"), ("https://api.example.com/v1?key=x", "m"),
                           ("https://user:secret@api.example.com/v1", "m"), ("https://:secret@api.example.com/v1", "m"),
                           ("http://host:bad/v1", "m"), ("http://[invalid/v1", "m"), (self.base_url, "")]:
            with self.subTest(url=url, model=model), self.assertRaises(common.LLMUnavailableError):
                common.validate_llm_config(base_url=url, model=model)

    def test_remote_endpoints_use_configured_proxy_settings(self):
        request = common.urllib.request.Request("https://api.example.com/v1/models")
        with mock.patch.object(common.urllib.request, "build_opener") as build:
            common._urlopen(request, timeout=2)
        build.assert_called_once_with()

    def test_loopback_endpoints_bypass_proxy_settings(self):
        request = common.urllib.request.Request(self.base_url + "/models")
        with mock.patch.object(common.urllib.request, "build_opener") as build:
            common._urlopen(request, timeout=2)
        self.assertEqual(build.call_args.args[0].proxies, {})

    def test_permanent_generation_error_is_not_retried(self):
        error = urllib.error.HTTPError(self.base_url, 400, "bad request", {}, io.BytesIO(b"invalid model"))
        with mock.patch.object(common, "wait_for_llm"), mock.patch.object(common, "_urlopen", side_effect=error) as opened, \
                mock.patch.object(common.time, "sleep") as sleep:
            with self.assertRaises(common.LLMUnavailableError):
                common.call_llm("hello", base_url=self.base_url, model="bad-model", timeout_sec=2)
        self.assertEqual(opened.call_count, 1)
        sleep.assert_not_called()

    def test_reasoning_text_is_excluded_from_the_answer(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"reasoning":"draft"}}]}'
        with mock.patch.object(common, "_urlopen", return_value=response):
            self.assertEqual(common.call_llm("hello", base_url=self.base_url, model="m", timeout_sec=2), "")


if __name__ == "__main__":
    unittest.main()
