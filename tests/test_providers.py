import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from providers import get_provider, PROVIDERS
from providers.base import APIProvider
from balance import balance_label
from translate_hook import configuration, translate


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = configuration()
        self.config["api_key"] = "test-key"

    def test_deepseek_extension_and_format_validation(self):
        provider = get_provider(self.config)
        for thinking in ("disabled", "enabled", None):
            self.config["thinking_type"] = thinking
            endpoint, body = provider.build_request("Hello", self.config, "Translate")
            self.assertEqual(endpoint, "/chat/completions")
            if thinking is None:
                self.assertNotIn("thinking", body)
            else:
                self.assertEqual(body["thinking"], {"type": thinking})
        self.config["thinking_type"] = "invalid"
        with self.assertRaises(ValueError):
            provider.build_request("Hello", self.config, "Translate")
        self.config["api_format"] = "responses"
        with self.assertRaises(ValueError):
            provider.build_request("Hello", self.config, "Translate")

    def test_openai_never_sends_deepseek_extension(self):
        self.config["api_provider"] = "openai_compatible"
        provider = get_provider(self.config)
        for api_format in ("chat_completions", "responses"):
            self.config["api_format"] = api_format
            endpoint, body = provider.build_request("Hello", self.config, "Translate")
            self.assertNotIn("thinking", body)
            self.assertEqual(endpoint, "/" + ("responses" if api_format == "responses"
                                              else "chat/completions"))
        self.config["api_format"] = "unknown"
        with self.assertRaises(ValueError):
            provider.build_request("Hello", self.config, "Translate")

    def test_openai_balance_skips_network(self):
        self.config["api_provider"] = "openai_compatible"
        with patch("urllib.request.urlopen") as request:
            self.assertIsNone(balance_label(self.config))
            request.assert_not_called()

    def test_unknown_provider_fails_before_network(self):
        for name in ("unknown", None, []):
            self.config["api_provider"] = name
            with self.subTest(name=name), patch("urllib.request.urlopen") as request:
                with self.assertRaises(ValueError):
                    translate("Hello", self.config)
                request.assert_not_called()

    def test_old_config_migration_and_explicit_selection(self):
        defaults = configuration()
        cases = [
            ({"base_url": "https://api.deepseek.com/v1",
              "api_format": "chat_completions"}, "deepseek"),
            ({"base_url": "https://example.com/v1",
              "api_format": "chat_completions"}, "openai_compatible"),
            ({"api_format": "responses"}, "openai_compatible"),
            ({"api_format": "messages"}, "anthropic"),
            ({"api_provider": "anthropic", "api_format": "messages"}, "anthropic"),
            ({"api_provider": "openai_compatible"}, "openai_compatible"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.example.json").write_text(json.dumps(defaults))
            for overrides, expected in cases:
                with self.subTest(overrides=overrides):
                    (root / "config.json").write_text(json.dumps(overrides))
                    with patch("translate_hook.ROOT", root):
                        self.assertEqual(configuration()["api_provider"], expected)

    def test_registered_adapter_uses_shared_transport(self):
        class CustomProvider(APIProvider):
            def build_request(self, text, config, instructions):
                return "/custom", {"text": text, "prompt": instructions}

            def parse_response(self, data, config):
                return data["translation"]

        self.config.update(api_provider="custom", base_url="https://example.com/v1")
        response = io.BytesIO(b'{"translation": "Translated"}')
        with patch.dict(PROVIDERS, custom=CustomProvider()), patch(
                "urllib.request.urlopen", return_value=response) as request:
            self.assertEqual(translate(" Hello\n", self.config, "Custom prompt"),
                             " Translated\n")
            sent = request.call_args.args[0]
            self.assertEqual(sent.full_url, "https://example.com/v1/custom")
            self.assertEqual(json.loads(sent.data),
                             {"text": " Hello\n", "prompt": "Custom prompt"})
            self.assertEqual(sent.get_header("Authorization"), "Bearer test-key")


class AnthropicProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((Path(__file__).resolve().parents[1] / "config.example.json").read_text())
        self.config.update(api_provider="anthropic", api_format="messages", api_key="test-key",
                           model="test-model", max_output_tokens=4096,
                           base_url="https://gateway.example/prefix/v1/")
        self.provider = get_provider(self.config)

    def response(self, **fields):
        return {"type": "message", "role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Translated"}], **fields}

    def test_request_auth_body_timeout_and_whitespace(self):
        response = io.BytesIO(json.dumps(self.response()).encode())
        with patch("urllib.request.urlopen", return_value=response) as request:
            self.assertEqual(translate(" Hello\n", self.config, "Translate exactly"), " Translated\n")
        sent = request.call_args.args[0]
        headers = {key.lower(): value for key, value in sent.header_items()}
        self.assertEqual(sent.full_url, "https://gateway.example/prefix/v1/messages")
        self.assertEqual(headers, {"x-api-key": "test-key", "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"})
        self.assertEqual(request.call_args.kwargs["timeout"], self.config["timeout_seconds"])
        self.assertEqual(json.loads(sent.data), {
            "model": "test-model", "system": "Translate exactly", "stream": False,
            "max_tokens": 4096, "messages": [{"role": "user", "content": " Hello\n"}]})

    def test_text_blocks_join_without_thinking(self):
        response = self.response(content=[{"type": "thinking", "thinking": "private"},
                                          {"type": "text", "text": "First"},
                                          {"type": "redacted_thinking", "data": "private"},
                                          {"type": "text", "text": " second"}])
        self.assertEqual(self.provider.parse_response(response, self.config), "First second")

    def test_incomplete_error_and_malformed_responses_rejected(self):
        responses = [self.response(stop_reason=reason) for reason in
                     ("max_tokens", "tool_use", "pause_turn", "refusal", "stop_sequence", None)]
        responses += [None, [], {"type": "error", "error": {"message": "secret"}},
                      self.response(role="user"), self.response(content=None)]
        responses += [self.response(content=content) for content in
                      ([], [None], [{"type": "text"}], [{"type": "text", "text": 42}],
                       [{"type": "text", "text": " "}], [{"type": "thinking"}],
                       [{"type": "tool_use"}])]
        for response in responses:
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                self.provider.parse_response(response, self.config)

    def test_incompatible_formats_fail_before_network(self):
        for api_format in ("chat_completions", "responses", "unknown"):
            self.config["api_format"] = api_format
            with self.subTest(api_format=api_format), patch("urllib.request.urlopen") as request:
                with self.assertRaises(ValueError):
                    translate("Hello", self.config)
                request.assert_not_called()

    def test_balance_skips_network(self):
        with patch("urllib.request.urlopen") as request:
            self.assertIsNone(balance_label(self.config))
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
