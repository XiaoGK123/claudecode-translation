import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from input_translate import translate_input
from translate_hook import configuration


class InputTranslationTests(unittest.TestCase):
    def test_original_input_sent_and_mixed_language_response_returned_verbatim(self):
        original = '请点击“确认”按钮，然后打开—设置页面—'
        reply = 'Click the “确认” button, then open —设置页面—.'
        config = configuration()
        config["api_key"] = "test-only"
        with patch("input_translate.translate", return_value=reply) as request:
            self.assertEqual(translate_input(original, config), reply)
            request.assert_called_once_with(original, config, config["input_translation_prompt"])

    def test_custom_input_prompt(self):
        config = {"input_translation_prompt": "Custom input instructions"}
        with patch("input_translate.translate", return_value="Hello") as request:
            self.assertEqual(translate_input("你好", config), "Hello")
            request.assert_called_once_with("你好", config, "Custom input instructions")

    def test_invalid_input_prompt(self):
        for prompt in ("", "   ", None, 42):
            with self.subTest(prompt=prompt), patch("input_translate.translate") as request:
                with self.assertRaises(ValueError):
                    translate_input("你好", {"input_translation_prompt": prompt})
                request.assert_not_called()

    def test_api_failure_propagates_for_original_text_recovery(self):
        with patch("input_translate.translate", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                translate_input('请点击“确认”', configuration())


if __name__ == "__main__":
    unittest.main()
