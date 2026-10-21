import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from input_protection import needs_translation
from prompt_hook import handle, main
from translate_hook import configuration, ROOT


class PromptHookTests(unittest.TestCase):
    def event(self, prompt):
        return {"hook_event_name": "UserPromptSubmit", "prompt": prompt}

    def test_detection_outside_protection(self):
        for text in ("你好", "Hello，world", "，。！？；：、", "…", "—", "“”", "“你好”", "（！）", "［］", "\U00020000"):
            with self.subTest(text=text):
                self.assertTrue(needs_translation(text))
        for text in ("Hello, world!", "What about the two employee IDs 01458275 and 01448193?",
                     "", "123", "ABC１２３", 'Click "确认！"',
                     '`！`', '```\n，。\n```', '【你好！】'):
            with self.subTest(text=text):
                self.assertFalse(needs_translation(text))

    def test_english_and_disabled_skip_api(self):
        with patch("urllib.request.urlopen") as request:
            self.assertEqual(handle(self.event('Click "确认"'), {}), {})
            self.assertEqual(handle(self.event("你好！"), {"prompt_guard_enabled": False}), {})
            request.assert_not_called()

    def test_only_guard_key_controls_check(self):
        cases = [({}, True), ({"prompt_translation_enabled": False}, True),
                 ({"prompt_translation_enabled": True}, True),
                 ({"prompt_guard_enabled": False}, False),
                 ({"prompt_guard_enabled": True, "prompt_translation_enabled": False}, True),
                 ({"prompt_guard_enabled": False, "prompt_translation_enabled": True}, False)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.example.json").write_text((ROOT / "config.example.json").read_text())
            for overrides, expected in cases:
                with self.subTest(overrides=overrides), patch("translate_hook.ROOT", root):
                    source = json.dumps(overrides)
                    (root / "config.json").write_text(source)
                    config = configuration()
                    self.assertIs(config["prompt_guard_enabled"], expected)
                    result = handle(self.event("你好"), config)
                    self.assertEqual(result.get("decision") == "block", expected)
                    self.assertEqual((root / "config.json").read_text(), source)

    def test_all_blocked_prompts_use_exact_message_without_api(self):
        for prompt in ("你好", "！？", '请点击“确认”', "/review 中文", "/review ，"):
            with self.subTest(prompt=prompt), patch("translate_hook.translate") as translate, \
                    patch("urllib.request.urlopen") as request:
                result = handle(self.event(prompt), {})
                self.assertEqual(result["decision"], "block")
                self.assertEqual(result["reason"], "检测到未受保护的中文片段")
                self.assertTrue(result["hookSpecificOutput"]["suppressOriginalPrompt"])
                self.assertNotIn("additionalContext", result["hookSpecificOutput"])
                translate.assert_not_called()
                request.assert_not_called()
        self.assertEqual(handle(self.event("/review file.py"), {}), {})

    def test_errors_allow_without_leaking_details(self):
        cases = [("invalid json", {}), ("", {}), ("null", {}), ("[]", {}),
                 ('{}', {}),
                 ('{"hook_event_name":"Stop","prompt":"你好"}', {}),
                 ('{"hook_event_name":"UserPromptSubmit"}', {}),
                 ('{"hook_event_name":"UserPromptSubmit","prompt":42}', {}),
                 ('{"hook_event_name":"UserPromptSubmit","prompt":null}', {}),
                 ('{"hook_event_name":"UserPromptSubmit","prompt":"你好"}',
                  RuntimeError("secret-key source-text"))]
        for source, config in cases:
            kwargs = {"side_effect": config} if isinstance(config, Exception) else {"return_value": config}
            with self.subTest(source=source), patch("sys.stdin", io.StringIO(source)), \
                    patch("sys.stdout", new_callable=io.StringIO) as output, \
                    patch("prompt_hook.configuration", **kwargs):
                self.assertEqual(main(), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result, {})
                self.assertNotIn("secret-key", output.getvalue())
                self.assertNotIn("source-text", output.getvalue())

    def test_detection_error_allows(self):
        with patch("sys.stdin", io.StringIO(json.dumps(self.event("你好")))), \
                patch("sys.stdout", new_callable=io.StringIO) as output, \
                patch("prompt_hook.configuration", return_value={}), \
                patch("prompt_hook.needs_translation", side_effect=RuntimeError("secret")):
            self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.getvalue()), {})


if __name__ == "__main__":
    unittest.main()
