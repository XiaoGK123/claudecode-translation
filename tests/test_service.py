import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="translation-")
        self.root = Path(self.temp.name)
        for name in ("service.py", "hotkey.py", "loc_monitor.py", "balance.py", "translate_hook.py", "install.py", "config.example.json"):
            shutil.copy2(ROOT / name, self.root)
        shutil.copytree(ROOT / "providers", self.root / "providers")
        self.settings = self.root / "claude-settings.json"
        self.original = {"permissions": {"allow": ["Read"]}, "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}]}}
        self.settings.write_text(json.dumps(self.original))
        (self.root / "config.json").write_text(json.dumps({"settings_file": str(self.settings), "input_translation_enabled": False, "loc_monitor_enabled": False}))

    def command(self, action):
        return subprocess.run([sys.executable, str(self.root / "service.py"), action],
                              text=True, capture_output=True, timeout=15, check=True).stdout

    def tearDown(self):
        try:
            self.command("stop")
        finally:
            self.temp.cleanup()

    def installed(self):
        hooks = json.loads(self.settings.read_text())["hooks"]
        self.assertEqual("MessageDisplay" in hooks, "UserPromptSubmit" in hooks)
        return "MessageDisplay" in hooks

    def pid(self):
        return int(re.search(r"PID (\d+)", self.command("status")).group(1))

    def wait_removed(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not self.installed():
                return
            time.sleep(0.05)
        self.fail("Hook remained after shutdown")

    def test_start_stop_idempotent_and_preserve_other_settings(self):
        self.assertIn("Started", self.command("start"))
        self.assertTrue(self.installed())
        first_pid = self.pid()
        self.assertIn("Already running", self.command("start"))
        self.assertEqual(first_pid, self.pid())
        data = json.loads(self.settings.read_text())
        data["theme"] = "dark"
        self.settings.write_text(json.dumps(data))
        self.assertIn("removed", self.command("stop"))
        self.assertFalse(self.installed())
        self.assertEqual(json.loads(self.settings.read_text()), {**self.original, "theme": "dark"})
        self.command("stop")
        self.assertIn("Stopped", self.command("status"))

    def test_missing_config_generated_without_starting_or_installing_hook(self):
        for action in ([], ["start"], ["_run"]):
            with self.subTest(action=action):
                config = self.root / "config.json"
                config.unlink()
                result = subprocess.run([sys.executable, str(self.root / "service.py"), *action],
                                        text=True, capture_output=True, timeout=5, check=True)
                self.assertEqual(result.stdout.strip(),
                                 f"无config.json文件，目前已自动生成，文件位置：{config.resolve()}，请配置api信息后重启")
                self.assertEqual(result.stderr, "")
                self.assertEqual(json.loads(config.read_text())["api_key"], "")
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(self.settings.read_text()), self.original)
                self.assertFalse((self.root / ".runtime").exists())

    def test_sigterm_cleans_hook(self):
        self.command("start")
        os.kill(self.pid(), signal.SIGTERM)
        self.wait_removed()

    def test_forced_kill_then_stop_recovers_orphan(self):
        self.command("start")
        os.kill(self.pid(), signal.SIGKILL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if "Stopped" in self.command("status"):
                break
            time.sleep(0.05)
        self.assertTrue(self.installed())
        self.command("stop")
        self.assertFalse(self.installed())

    def test_changed_config_does_not_change_shutdown_target(self):
        self.command("start")
        other = self.root / "other.json"
        (self.root / "config.json").write_text(json.dumps({"settings_file": str(other)}))
        self.command("stop")
        self.assertFalse(self.installed())
        self.assertFalse(other.exists())

    def test_foreground_single_status_line_and_exit_cleanup(self):
        for sig in (signal.SIGINT, signal.SIGHUP):
            with self.subTest(signal=sig):
                config = {"settings_file": str(self.settings), "input_translation_enabled": False,
                          "loc_monitor_enabled": False}
                (self.root / "config.json").write_text(json.dumps(config))
                output = self.root / "foreground.log"
                with output.open("w") as log:
                    process = subprocess.Popen([sys.executable, str(self.root / "service.py")],
                                               stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if "服务运行中" in output.read_text():
                            break
                        if process.poll() is not None:
                            self.fail(output.read_text())
                        time.sleep(0.05)
                    self.assertIsNone(process.poll())
                    self.assertTrue(self.installed())
                    before = output.read_text()
                    time.sleep(0.6)
                    self.assertEqual(output.read_text(), before)
                    self.assertEqual(len(before.splitlines()), 1)
                    self.assertIn("余额 未配置 API Key", before)
                    self.assertIn("中文提交检查 已开启", before)
                    self.assertIn("出口地区监测 已关闭", before)
                    process.send_signal(sig)
                    self.assertEqual(process.wait(timeout=5), 0)
                    self.assertFalse(self.installed())
                    self.assertIn("Hook 已删除", output.read_text())
                    self.assertEqual(json.loads(self.settings.read_text()), self.original)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=5)

    def test_balance_and_switches_refresh_in_same_terminal_line(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                amount = f"{11 - len(requests)}.00"
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"is_available": True, "balance_infos": [
                    {"currency": "CNY", "total_balance": amount}]}).encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        config = {"settings_file": str(self.settings), "api_provider": "deepseek",
                  "api_key": "service-test-key", "input_translation_enabled": False,
                  "loc_monitor_enabled": False,
                  "base_url": f"http://127.0.0.1:{server.server_port}",
                  "balance_refresh_seconds": 0.2, "balance_timeout_seconds": 0.5}
        (self.root / "config.json").write_text(json.dumps(config))
        master, slave = pty.openpty()
        process = subprocess.Popen([sys.executable, str(self.root / "service.py")],
                                   stdout=slave, stderr=slave)
        os.close(slave)
        output = b""
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    output += os.read(master, 65536)
                if "余额 9.00 CNY" in output.decode():
                    break
            text = output.decode()
            self.assertIn("余额 10.00 CNY", text)
            self.assertIn("余额 9.00 CNY", text)
            self.assertIn("\r\033[2K", text)
            self.assertNotIn("\n", text)
            self.assertNotIn("service-test-key", text)
            self.assertGreaterEqual(len(requests), 2)
            self.assertTrue(all(path == "/user/balance" for path in requests))
            self.assertIn("中文提交检查 已开启", text)
            self.assertIn("出口地区监测 已关闭", text)
            config["prompt_translation_enabled"] = False
            (self.root / "config.json").write_text(json.dumps(config))
            changed = b""
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    changed += os.read(master, 65536)
                if "中文提交检查 已关闭" in changed.decode():
                    break
            self.assertIn("中文提交检查 已关闭", changed.decode())
            self.assertIn("出口地区监测 已关闭", changed.decode())
            self.assertNotIn("\n", changed.decode())
            process.send_signal(signal.SIGINT)
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertFalse(self.installed())
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            os.close(master)
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
