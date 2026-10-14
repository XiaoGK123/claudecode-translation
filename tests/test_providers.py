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


if __name__ == "__main__":
    unittest.main()
