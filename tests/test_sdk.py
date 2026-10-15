import builtins
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI, APITimeoutError, RateLimitError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translate_hook import configuration, translate


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.config = configuration()
        self.config.update(api_provider="openai_compatible", api_key="test-key",
                           base_url="https://example.com/v1/", model="test-model",
                           timeout_seconds=2)
        self.requests = []
        self.clients = []
        self.status = 200
        self.failure = None
        self.response = {"choices": [{"finish_reason": "stop",
                                     "message": {"role": "assistant", "content": "译文"}}]}

    def client(self, **kwargs):
        self.assertEqual(kwargs["api_key"], "test-key")
        self.assertEqual(kwargs["base_url"], "https://example.com/v1")
        self.assertEqual(kwargs["timeout"], 2)
        self.assertEqual(kwargs["max_retries"], 0)
        client = OpenAI(**kwargs, http_client=httpx.Client(
            transport=httpx.MockTransport(self.respond)))
        self.clients.append(client)
        return client

    def respond(self, request):
        self.requests.append(request)
        if self.failure:
            raise self.failure
        return httpx.Response(self.status, json=self.response)

    def run_translation(self, text=" Hello\n"):
        with patch("openai.OpenAI", side_effect=self.client):
            return translate(text, self.config, "Translate")

    def test_sdk_requests_both_formats_and_closes_clients(self):
        for api_format in ("chat_completions", "responses"):
            self.config["api_format"] = api_format
            if api_format == "responses":
                self.response = {"status": "completed", "output": [
                    {"type": "message", "role": "assistant", "content": [
                        {"type": "output_text", "text": "译文"}]}]}
            with self.subTest(api_format=api_format):
                self.assertEqual(self.run_translation(), " 译文\n")
                request = self.requests[-1]
                self.assertEqual(request.headers["Authorization"], "Bearer test-key")
                body = json.loads(request.content)
                self.assertEqual(body["model"], "test-model")
                self.assertIs(body["enable_thinking"], False)
                self.assertNotIn("extra_body", body)
                self.assertNotIn("thinking", body)
                if api_format == "responses":
                    self.assertEqual(request.url.path, "/v1/responses")
                    self.assertEqual(body["input"], " Hello\n")
                    self.assertEqual(body["instructions"], "Translate")
                    self.assertFalse(body["store"])
                else:
                    self.assertEqual(request.url.path, "/v1/chat/completions")
                    self.assertEqual(body["messages"][1]["content"], " Hello\n")
                    self.assertFalse(body["stream"])
                self.assertTrue(self.clients[-1].is_closed())

    def test_extra_body_custom_and_empty_for_both_formats(self):
        for api_format in ("chat_completions", "responses"):
            self.config["api_format"] = api_format
            if api_format == "responses":
                self.response = {"status": "completed", "output": [
                    {"type": "message", "role": "assistant", "content": [
                        {"type": "output_text", "text": "译文"}]}]}
            for extra in ({"custom_option": {"enabled": True}}, {}):
                self.config["extra_body"] = extra
                original = json.loads(json.dumps(extra))
                with self.subTest(api_format=api_format, extra=extra):
                    self.assertEqual(self.run_translation(), " 译文\n")
                    body = json.loads(self.requests[-1].content)
                    self.assertNotIn("enable_thinking", body)
                    self.assertNotIn("extra_body", body)
                    if extra:
                        self.assertEqual(body["custom_option"], extra["custom_option"])
                    self.assertEqual(extra, original)

    def test_invalid_extra_body_rejected_before_sdk_client(self):
        for extra in (None, [], "invalid", False, 42):
            self.config["extra_body"] = extra
            with self.subTest(extra=extra), patch("openai.OpenAI") as client:
                with self.assertRaisesRegex(ValueError, "extra_body"):
                    translate("Hello", self.config, "Translate")
                client.assert_not_called()

    def test_legacy_config_inherits_extra_body_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            defaults = Path(__file__).resolve().parents[1] / "config.example.json"
            (root / "config.example.json").write_text(defaults.read_text())
            (root / "config.json").write_text('{"api_provider": "openai_compatible"}')
            with patch("translate_hook.ROOT", root):
                self.assertEqual(configuration()["extra_body"], {"enable_thinking": False})

    def test_sdk_status_error_does_not_retry_and_closes_client(self):
        self.status = 429
        self.response = {"error": {"message": "unavailable"}}
        with self.assertRaises(RateLimitError):
            self.run_translation()
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.clients[-1].is_closed())

    def test_sdk_timeout_does_not_retry_and_closes_client(self):
        self.failure = httpx.ReadTimeout("timeout")
        with self.assertRaises(APITimeoutError):
            self.run_translation()
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.clients[-1].is_closed())

    def test_incomplete_and_empty_sdk_responses_are_rejected(self):
        cases = [
            ("chat_completions", {"choices": [{"finish_reason": "length",
                                  "message": {"content": "partial"}}]}),
            ("chat_completions", {"choices": [{"finish_reason": "stop",
                                  "message": {"content": "   "}}]}),
            ("responses", {"status": "incomplete", "output": []}),
            ("responses", {"status": "completed", "output": []}),
        ]
        for api_format, response in cases:
            self.config["api_format"] = api_format
            self.response = response
            with self.subTest(api_format=api_format, response=response):
                with self.assertRaises(RuntimeError):
                    self.run_translation()
                self.assertTrue(self.clients[-1].is_closed())

    def test_sdk_error_falls_back_without_logging_response_or_credentials(self):
        import io
        from translate_hook import main
        self.status = 429
        self.response = {"error": {"message": "sensitive-original test-key"}}
        event = json.dumps({"hook_event_name": "MessageDisplay", "delta": "Hello"})
        with patch("openai.OpenAI", side_effect=self.client), \
                patch("translate_hook.configuration", return_value=self.config), \
                patch("sys.stdin", io.StringIO(event)), \
                patch("sys.stdout", new_callable=io.StringIO) as output, \
                patch("sys.stderr", new_callable=io.StringIO) as error:
            self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.getvalue()), {})
            self.assertIn("RateLimitError", error.getvalue())
            self.assertNotIn("sensitive-original", error.getvalue())
            self.assertNotIn("test-key", error.getvalue())
        self.assertEqual(len(self.requests), 1)

    def test_missing_sdk_does_not_affect_deepseek(self):
        original_import = builtins.__import__
        def no_sdk(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=no_sdk):
            with self.assertRaisesRegex(RuntimeError, "requirements.txt"):
                translate("Hello", self.config, "Translate")
            self.config["api_provider"] = "deepseek"
            from io import BytesIO
            response = BytesIO(json.dumps(self.response).encode())
            with patch("urllib.request.urlopen", return_value=response) as request:
                self.assertEqual(translate("Hello", self.config, "Translate"), "译文")
                self.assertNotIn("enable_thinking", json.loads(request.call_args.args[0].data))
                self.assertNotIn("extra_body", json.loads(request.call_args.args[0].data))


if __name__ == "__main__":
    unittest.main()
