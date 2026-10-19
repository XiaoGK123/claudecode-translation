import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from input_protection import needs_translation
from input_translate import translate_input
from prompt_hook import handle, main


class PromptHookTests(unittest.TestCase):
    def event(self, prompt):
        return {"hook_event_name": "UserPromptSubmit", "prompt": prompt}

    def test_detection_outside_protection(self):
        for text in ("你好", "Hello，world", "，。！？；：、", "…", "—", "“”", "“你好”", "（！）", "［］", "\U00020000"):
            with self.subTest(text=text):
                self.assertTrue(needs_translation(text))
        for text in ("Hello, world!", "", "123", "ABC１２３", 'Click "确认！"',
                     '`！`', '```\n，。\n```', '【你好！】'):
            with self.subTest(text=text):
                self.assertFalse(needs_translation(text))

    def test_punctuation_only_calls_translation(self):
        with patch("input_translate.translate", return_value="!?") as request:
            self.assertEqual(translate_input("！？", {"input_translation_prompt": "English punctuation"}), "!?")
            request.assert_called_once()

    def test_english_and_disabled_skip_api(self):
        with patch("prompt_hook.translate_input") as request:
            self.assertEqual(handle(self.event('Click "确认"'), {}), {})
            self.assertEqual(handle(self.event("你好！"), {"prompt_translation_enabled": False}), {})
            request.assert_not_called()

    def test_block_offer_translation_and_resubmit(self):
        with patch("prompt_hook.translate_input", return_value='Click "确认"'):
            result = handle(self.event('请点击“确认”'), {})
        self.assertEqual(result["decision"], "block")
        self.assertIn('Click "确认"', result["reason"])
        self.assertNotIn("请点击", result["reason"])
        self.assertTrue(result["hookSpecificOutput"]["suppressOriginalPrompt"])
        self.assertNotIn("additionalContext", result["hookSpecificOutput"])
        self.assertEqual(handle(self.event('Click "确认"'), {}), {})

    def test_remaining_chinese_or_punctuation_is_not_offered(self):
        for reply in ("Hello！", "你好", "“你好”"):
            with self.subTest(reply=reply), patch("prompt_hook.translate_input", return_value=reply):
                result = handle(self.event("你好"), {})
                self.assertEqual(result["decision"], "block")
                self.assertIn("仍含中文或中文标点", result["reason"])

    def test_command_not_sent_to_translator(self):
        with patch("prompt_hook.translate_input") as request:
            self.assertEqual(handle(self.event("/review 中文"), {})["decision"], "block")
            self.assertEqual(handle(self.event("/review file.py"), {}), {})
            request.assert_not_called()

    def test_errors_block_without_leaking_error_bodies(self):
        for source in ('{"hook_event_name":"UserPromptSubmit","prompt":"你好"}', 'invalid json'):
            with self.subTest(source=source), patch("sys.stdin", io.StringIO(source)), \
                    patch("sys.stdout", new_callable=io.StringIO) as output, \
                    patch("prompt_hook.configuration", return_value={}), \
                    patch("prompt_hook.translate_input", side_effect=RuntimeError("secret-key source-text")):
                self.assertEqual(main(), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result["decision"], "block")
                self.assertNotIn("secret-key", output.getvalue())
                self.assertNotIn("source-text", output.getvalue())


if __name__ == "__main__":
    unittest.main()
