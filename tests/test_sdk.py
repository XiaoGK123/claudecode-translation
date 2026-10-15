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
            with patch("urllib.request.urlopen", return_value=response):
                self.assertEqual(translate("Hello", self.config, "Translate"), "译文")


if __name__ == "__main__":
    unittest.main()
