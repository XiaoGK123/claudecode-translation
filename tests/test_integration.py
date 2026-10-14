import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "providers", self.root / "providers")
        shutil.copy2(ROOT / "translate_hook.py", self.root)
        shutil.copy2(ROOT / "config.example.json", self.root)
        self.requests = []
        self.response = {"status": "completed", "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "测试通过。"}]}]}
        self.http_status = 200
        self.delay = 0
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                case.requests.append((self.path, body, self.headers.get("Authorization")))
                time.sleep(case.delay)
                self.send_response(case.http_status)
                self.end_headers()
                try:
                    self.wfile.write(json.dumps(case.response).encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = json.loads((self.root / "config.example.json").read_text())
        self.config.update(api_key="test-only-key", base_url=f"http://127.0.0.1:{self.server.server_port}/v1/",
                           model="configured-test-model", api_format="responses", api_provider="openai_compatible")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def hook(self, delta="Tests passed.\n", key="test-only-key", **fields):
        # Conflicting environment values must never override file configuration.
        env = {**os.environ, "OPENAI_BASE_URL": "http://127.0.0.1:1/wrong",
               "OPENAI_API_KEY": "ignored-environment-key", "OPENAI_MODEL": "ignored-model"}
        self.config["api_key"] = key
        (self.root / "config.json").write_text(json.dumps(self.config))
        event = {"hook_event_name": "MessageDisplay", "delta": delta,
                 "message_id": "message-1", "index": 0, "final": True, **fields}
        run = subprocess.run([sys.executable, str(self.root / "translate_hook.py")],
                             input=json.dumps(event), capture_output=True, text=True,
                             env=env, timeout=5)
        self.assertEqual(run.returncode, 0)
        self.assertNotIn("test-only-key", run.stderr)
        self.assertNotIn("ignored-environment-key", run.stderr)
        return json.loads(run.stdout)

    def test_translation_and_transcript_unchanged(self):
        transcript = self.root / "transcript.jsonl"
        original = b'{"text":"Tests passed."}\n'
        transcript.write_bytes(original)
        reply = self.hook(transcript_path=str(transcript))
        self.assertEqual(reply["hookSpecificOutput"]["displayContent"], "测试通过。\n")
        self.assertEqual(transcript.read_bytes(), original)
        path, body, auth = self.requests[0]
        self.assertEqual(path, "/v1/responses")
        self.assertEqual(auth, "Bearer test-only-key")
        self.assertEqual(body["model"], "configured-test-model")
        self.assertEqual(body["input"], "Tests passed.\n")
        self.assertFalse(body["store"])
        self.assertNotIn("transcript_path", body)

    def test_custom_reply_prompt_for_both_api_formats(self):
        for api_format in ("responses", "chat_completions"):
            with self.subTest(api_format=api_format):
                self.config["api_format"] = api_format
                self.config["reply_translation_prompt"] = "Custom reply instructions"
                if api_format == "chat_completions":
                    self.response = {"choices": [{"finish_reason": "stop",
                                                 "message": {"content": "测试通过。"}}]}
                self.hook()
                body = self.requests[-1][1]
                actual = (body["instructions"] if api_format == "responses"
                          else body["messages"][0]["content"])
                self.assertEqual(actual, "Custom reply instructions")

    def test_old_config_uses_default_reply_prompt(self):
        self.config.pop("reply_translation_prompt")
        self.hook()
        defaults = json.loads((self.root / "config.example.json").read_text())
        self.assertEqual(self.requests[0][1]["instructions"],
                         defaults["reply_translation_prompt"])

    def test_invalid_reply_prompt_falls_back_without_request(self):
        for prompt in ("", "   ", None, 42):
            with self.subTest(prompt=prompt):
                self.config["reply_translation_prompt"] = prompt
                self.assertEqual(self.hook(), {})
        self.assertEqual(self.requests, [])

    def test_bilingual_display_and_transcript_unchanged(self):
        self.config["display_mode"] = "bilingual"
        transcript = self.root / "transcript.jsonl"
        original = b'{"text":"Tests passed."}\n'
        transcript.write_bytes(original)
        reply = self.hook(transcript_path=str(transcript))
        self.assertEqual(reply["hookSpecificOutput"]["displayContent"],
                         "测试通过。\n\n> Tests passed.\n")
        self.assertEqual(transcript.read_bytes(), original)
        self.assertEqual(len(self.requests), 1)

    def test_bilingual_multiline_markdown_in_quote(self):
        self.config["display_mode"] = "bilingual"
        translation = "步骤：\n\n- 运行命令\n\n```python\n    print('ok')\n```"
        self.response["output"][1]["content"][0]["text"] = translation
        original = "Steps:\n\n- Run command\n\n```python\n    print('ok')\n```\n"
        reply = self.hook(delta=original)
        self.assertEqual(reply["hookSpecificOutput"]["displayContent"],
                         translation + "\n\n> Steps:\n> \n> - Run command\n> \n"
                         "> ```python\n>     print('ok')\n> ```\n")

    def test_bilingual_failure_falls_back(self):
        self.config["display_mode"] = "bilingual"
        self.http_status = 429
        self.assertEqual(self.hook(), {})

    def test_unknown_display_mode_uses_chinese(self):
        self.config["display_mode"] = "unknown"
        reply = self.hook()
        self.assertEqual(reply["hookSpecificOutput"]["displayContent"], "测试通过。\n")

    def test_missing_key_falls_back(self):
        self.assertEqual(self.hook(key=None), {})
        self.assertEqual(self.requests, [])

    def test_deepseek_chat_translation_and_transcript_unchanged(self):
        self.config["api_format"] = "chat_completions"
        self.config["api_provider"] = "deepseek"
        self.config["model"] = "deepseek-flash"
        self.response = {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "测试通过。", "reasoning_content": "hidden"}}]}
        transcript = self.root / "transcript.jsonl"
        transcript.write_text('English transcript\n')
        reply = self.hook(transcript_path=str(transcript))
        self.assertEqual(reply["hookSpecificOutput"]["displayContent"], "测试通过。\n")
        self.assertEqual(transcript.read_text(), 'English transcript\n')
        path, body, auth = self.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["messages"][1]["content"], "Tests passed.\n")
        self.assertFalse(body["stream"])
        self.assertEqual(body["max_tokens"], 393216)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertNotIn("store", body)
        self.assertNotIn("hidden", str(reply))

    def test_chat_truncated_response_falls_back(self):
        self.config["api_format"] = "chat_completions"
        self.response = {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}
        self.assertEqual(self.hook(), {})

    def test_http_error_falls_back(self):
        self.http_status = 429
        self.assertEqual(self.hook(), {})

    def test_incomplete_response_falls_back(self):
        self.response["status"] = "incomplete"
        self.assertEqual(self.hook(), {})

    def test_refusal_falls_back(self):
        self.response["output"][1]["content"] = [{"type": "refusal", "refusal": "No"}]
        self.assertEqual(self.hook(), {})

    def test_timeout_falls_back(self):
        self.config["timeout_seconds"] = 0.05
        self.delay = 0.2
        self.assertEqual(self.hook(), {})

    def test_empty_final_and_chinese_do_not_call_api(self):
        self.assertEqual(self.hook(delta=""), {})
        self.assertEqual(self.hook(delta="\n"), {})
        self.assertEqual(self.hook(delta="已经完成。"), {})
        self.assertEqual(self.requests, [])

    def test_disabled_skips_api(self):
        self.config["enabled"] = False
        self.assertEqual(self.hook(), {})
        self.assertEqual(self.requests, [])

    def test_other_event_does_not_call_api(self):
        self.assertEqual(self.hook(hook_event_name="Stop"), {})
        self.assertEqual(self.requests, [])

    def test_invalid_timeout_falls_back_before_request(self):
        self.config["timeout_seconds"] = self.config["hook_timeout_seconds"]
        self.assertEqual(self.hook(), {})
        self.assertEqual(self.requests, [])


class InstallerTests(unittest.TestCase):
    def test_hook_timeout_read_from_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("install.py", "translate_hook.py", "config.example.json"):
                shutil.copy2(ROOT / name, root)
            shutil.copytree(ROOT / "providers", root / "providers")
            (root / "config.json").write_text('{"timeout_seconds": 35, "hook_timeout_seconds": 45}')
            settings = root / "settings.json"
            subprocess.run([sys.executable, str(root / "install.py"), "--settings", str(settings)],
                           check=True, capture_output=True)
            installed = json.loads(settings.read_text())
            self.assertEqual(installed["hooks"]["MessageDisplay"][0]["hooks"][0]["timeout"], 45)

    def test_merge_repeat_remove_and_backup(self):
        with tempfile.TemporaryDirectory(prefix="translator space ") as directory:
            path = Path(directory) / "settings.json"
            original = {"permissions": {"allow": ["Read"]}, "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
                "MessageDisplay": [{"hooks": [{"type": "command", "command": "echo other"}]}]}}
            path.write_text(json.dumps(original))

            def install(*args):
                subprocess.run([sys.executable, str(ROOT / "install.py"),
                                "--settings", str(path), *args], check=True, capture_output=True)
                return json.loads(path.read_text())

            first = install()
            self.assertEqual(first["permissions"], original["permissions"])
            self.assertEqual(first["hooks"]["Stop"], original["hooks"]["Stop"])
            self.assertEqual(len(first["hooks"]["MessageDisplay"]), 2)
            self.assertEqual(install(), first)
            self.assertEqual(len(list(Path(directory).glob("*.backup-*"))), 1)
            self.assertEqual(install("--remove"), original)
            backups = list(Path(directory).glob("*.backup-*"))
            self.assertTrue(any(json.loads(p.read_text()) == original for p in backups))

    def test_invalid_settings_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("invalid json")
            run = subprocess.run([sys.executable, str(ROOT / "install.py"),
                                  "--settings", str(path)], capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(path.read_text(), "invalid json")


if __name__ == "__main__":
    unittest.main()
