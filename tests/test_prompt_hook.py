import io
import json
import subprocess
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
    def setUp(self):
        self.state_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.state_directory.cleanup)
        state_patch = patch("prompt_hook.STATE_DIR", Path(self.state_directory.name) / "state")
        state_patch.start()
        self.addCleanup(state_patch.stop)

    def event(self, prompt):
        return {"hook_event_name": "UserPromptSubmit", "prompt": prompt}

    def submit(self, prompt, session="test-session", config=None):
        return handle({**self.event(prompt), "session_id": session}, config or {})

    def test_exact_retry_allows_once(self):
        for prompt in ("你好", "/review 中文"):
            with self.subTest(prompt=prompt):
                self.assertEqual(self.submit(prompt)["decision"], "block")
                self.assertEqual(self.submit(prompt), {})
                self.assertEqual(self.submit(prompt)["decision"], "block")
                self.assertEqual(self.submit(prompt), {})

    def test_retry_requires_exact_text_and_consecutive_submission(self):
        for intervening in ("Hello", "你好 ", "你好\n", "您好", 'Click "确认"'):
            with self.subTest(intervening=intervening):
                self.assertEqual(self.submit("你好")["decision"], "block")
                self.submit(intervening)
                self.assertEqual(self.submit("你好")["decision"], "block")
                self.assertEqual(self.submit("你好"), {})

    def test_sessions_are_isolated(self):
        self.assertEqual(self.submit("你好", "first")["decision"], "block")
        self.assertEqual(self.submit("你好", "second")["decision"], "block")
        self.assertEqual(self.submit("你好", "first"), {})
        self.assertEqual(self.submit("你好", "second"), {})

    def test_missing_session_does_not_share_retries(self):
        for session in (None, "", 42):
            for _ in range(2):
                self.assertEqual(self.submit("你好", session)["decision"], "block")

    def test_disabling_guard_clears_pending_retry(self):
        self.assertEqual(self.submit("你好")["decision"], "block")
        self.assertEqual(self.submit("你好", config={"prompt_guard_enabled": False}), {})
        self.assertEqual(self.submit("你好")["decision"], "block")

    def test_retry_survives_separate_hook_processes_without_plaintext(self):
        state_dir = str(Path(self.state_directory.name) / "state")
        code = ("import sys; from pathlib import Path; import prompt_hook; "
                "prompt_hook.configuration = lambda: {'prompt_guard_enabled': True}; "
                "prompt_hook.STATE_DIR = Path(sys.argv[1]); prompt_hook.main()")
        event = {**self.event("你好\n完全相同"), "session_id": "private-session"}
        results = []
        for _ in range(3):
            run = subprocess.run([sys.executable, "-c", code, state_dir],
                                 input=json.dumps(event), text=True, capture_output=True,
                                 cwd=ROOT, check=True)
            results.append(json.loads(run.stdout))
        self.assertEqual(results[0]["decision"], "block")
        self.assertEqual(results[1], {})
        self.assertEqual(results[2]["decision"], "block")
        state_files = list(Path(state_dir).iterdir())
        self.assertEqual(len(state_files), 1)
        self.assertNotIn(event["session_id"], state_files[0].name)
        self.assertNotIn("你好", state_files[0].read_text())
        self.assertEqual(state_files[0].stat().st_mode & 0o777, 0o600)

    def test_state_error_allows(self):
        with patch("sys.stdin", io.StringIO(json.dumps({**self.event("你好"), "session_id": "s"}))), \
                patch("sys.stdout", new_callable=io.StringIO) as output, \
                patch("prompt_hook.configuration", return_value={}), \
                patch("prompt_hook.consume_retry", side_effect=OSError("secret")):
            self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.getvalue()), {})

    def test_detection_outside_protection(self):
        for text in ("你好", "帮我 fix bug", "\U00020000"):
            with self.subTest(text=text):
                self.assertTrue(needs_translation(text))
        for text in ("Hello, world!", "What about the two employee IDs 01458275 and 01448193?",
                     "", "123", "ABC１２３", "Hello，world", "，。！？；：、", "…", "—", "“”", "“你好”", "（！）", "［］", 'Click "确认！"',
                     '`！`', '```\n，。\n```', '【你好！】'):
            with self.subTest(text=text):
                self.assertFalse(needs_translation(text))

    def test_configurable_ratio_and_default_inheritance(self):
        self.assertEqual(handle(self.event('中abcd'), {})['decision'], 'block')
        self.assertEqual(handle(self.event('中abcde'), {}), {})
        self.assertEqual(handle(self.event('中abcd'), {'han_ratio_threshold': 0.5}), {})
        self.assertEqual(handle(self.event('中abcde'), {'han_ratio_threshold': 0.1})['decision'], 'block')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.example.json').write_text((ROOT / 'config.example.json').read_text())
            (root / 'config.json').write_text('{}')
            with patch('translate_hook.ROOT', root):
                self.assertEqual(configuration()['han_ratio_threshold'], 0.2)
            self.assertEqual((root / 'config.json').read_text(), '{}')

    def test_invalid_ratio_allows_submission(self):
        with patch('sys.stdin', io.StringIO(json.dumps(self.event('你好')))), \
                patch('sys.stdout', new_callable=io.StringIO) as output, \
                patch('prompt_hook.configuration', return_value={'han_ratio_threshold': 'bad'}):
            self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.getvalue()), {})

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
        for prompt in ("你好", '请点击“确认”', "/review 中文"):
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
