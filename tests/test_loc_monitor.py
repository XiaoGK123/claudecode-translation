import io
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import loc_monitor
import service


class LocMonitorTests(unittest.TestCase):
    def test_trace_request_and_parser(self):
        with patch("loc_monitor.urllib.request.urlopen", return_value=io.BytesIO(b"h=claude.ai\nloc=SG\n")) as request:
            self.assertEqual(loc_monitor.read_loc(), "SG")
        args, kwargs = request.call_args
        self.assertEqual(args[0].full_url, "https://claude.ai/cdn-cgi/trace")
        self.assertEqual(args[0].get_method(), "GET")
        self.assertEqual(kwargs["timeout"], 10)
        for body in (b"h=claude.ai\n", b"loc=\n", b"loc=SG\nloc=JP", b"loc=<script>", b"x" * 16385):
            with self.subTest(body=body[:30]), patch("loc_monitor.urllib.request.urlopen", return_value=io.BytesIO(body)):
                with self.assertRaises(loc_monitor.TraceError):
                    loc_monitor.read_loc()

    def test_default_region_and_live_configuration(self):
        with patch("loc_monitor.read_loc", return_value="SG"):
            self.assertIsNone(loc_monitor.check({}))
            self.assertIsNone(loc_monitor.check({"expected_loc": "sg"}))
            problem = loc_monitor.check({"expected_loc": "JP"})
            self.assertEqual(problem[1], "出口地区异常：当前 SG，预期 JP")
        with patch("loc_monitor.read_loc") as request:
            self.assertIsNone(loc_monitor.check({"loc_monitor_enabled": False}))
            self.assertEqual(loc_monitor.check({"expected_loc": "invalid"})[0], ("config",))
            request.assert_not_called()

    def test_failures_are_alerts_without_response_or_secret_details(self):
        errors = [TimeoutError("secret"), urllib.error.URLError("secret"),
                  urllib.error.HTTPError(loc_monitor.TRACE_URL, 503, "secret", {}, None),
                  loc_monitor.TraceError("响应缺少 loc 字段")]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch("loc_monitor.read_loc", side_effect=error):
                problem = loc_monitor.check({})
                self.assertIn("检查失败", problem[1])
                self.assertNotIn("secret", problem[1])
        with patch("loc_monitor.read_loc", side_effect=errors[-1]):
            self.assertIn("缺少 loc", loc_monitor.check({})[1])

    def run_sequence(self, problems, notify_error=None):
        stopped = Mock()
        stopped.is_set.return_value = False
        stopped.wait.side_effect = [False] * (len(problems) - 1) + [True]
        configuration = Mock(return_value={})
        log = Mock()
        with patch("loc_monitor.check", side_effect=problems) as check, \
                patch("loc_monitor.notify", side_effect=notify_error) as notify, \
                patch("loc_monitor.time.monotonic", return_value=0):
            loc_monitor.monitor(stopped, configuration, log)
        self.assertEqual(check.call_count, len(problems))
        self.assertEqual(configuration.call_count, len(problems))
        self.assertEqual(stopped.wait.call_args_list[0].args, (30,))
        return notify, log

    def test_every_unhealthy_check_notifies_including_repeated_regions(self):
        mismatch = (("mismatch", "JP", "SG"), "地区异常")
        failure = (("request", "TimeoutError"), "请求失败")
        notify, log = self.run_sequence([mismatch, mismatch, None, mismatch, failure, failure])
        expected = ["地区异常", "地区异常", "地区异常", "请求失败", "请求失败"]
        self.assertEqual([call.args[0] for call in notify.call_args_list], expected)
        self.assertEqual([call.args[0] for call in log.call_args_list], expected)

    def test_notification_failure_retries_next_check(self):
        problem = (("trace", "missing"), "缺少 loc")
        notify, log = self.run_sequence([problem, problem], OSError("secret"))
        self.assertEqual(notify.call_count, 2)
        self.assertTrue(any("通知发送失败" in call.args[0] for call in log.call_args_list))

    def test_configuration_failure_notifies(self):
        stopped = Mock()
        stopped.is_set.return_value = False
        stopped.wait.return_value = True
        with patch("loc_monitor.notify") as notify:
            loc_monitor.monitor(stopped, Mock(side_effect=ValueError("secret")), Mock())
            notify.assert_called_once_with("出口地区检查失败：无法读取配置")

    def test_stop_during_request_suppresses_notification(self):
        stopped = threading.Event()
        def check(config):
            stopped.set()
            return (("request",), "请求失败")
        with patch("loc_monitor.check", side_effect=check), patch("loc_monitor.notify") as notify:
            loc_monitor.monitor(stopped, lambda: {}, Mock())
            notify.assert_not_called()

    def test_notification_uses_fixed_script_and_argv(self):
        message = '当前地区 "JP"; do shell script "bad"'
        with patch("loc_monitor.subprocess.run") as run:
            loc_monitor.notify(message)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ["/usr/bin/osascript", "-e", loc_monitor.NOTIFICATION_SCRIPT])
        self.assertEqual(argv[3], message)
        self.assertNotIn(message, argv[2])
        self.assertEqual(run.call_args.kwargs["timeout"], 5)

    def test_background_start_platform_and_private_logging(self):
        with patch("loc_monitor.sys.platform", "linux"), patch("loc_monitor.threading.Thread") as thread:
            self.assertIsNone(loc_monitor.start(threading.Event(), lambda: {}, Path("unused")))
            thread.assert_not_called()
        with tempfile.TemporaryDirectory() as directory, \
                patch("loc_monitor.sys.platform", "darwin"), patch("loc_monitor.threading.Thread") as thread:
            path = Path(directory) / "monitor.log"
            loc_monitor.start(threading.Event(), lambda: {}, path)
            self.assertTrue(thread.call_args.kwargs["daemon"])
            thread.return_value.start.assert_called_once()
            log = thread.call_args.kwargs["args"][2]
            log("请求失败")
            self.assertIn("请求失败", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_service_shares_shutdown_event_with_monitor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            listener, client = Mock(), Mock()
            listener.accept.return_value = (client, None)
            client.recv.return_value = b"stop\n"
            config = {"settings_file": str(root / "settings.json"), "balance_refresh_seconds": 30,
                      "model": "test", "input_translation_enabled": False}
            with patch.multiple(service, RUNTIME=root, SOCKET=root / "control.sock", STATE=root / "state.json"), \
                    patch("service.configuration", return_value=config), patch("service.update"), \
                    patch("service.balance_label", return_value=None), patch("service.signal.signal"), \
                    patch("service.socket.socket", return_value=listener), patch("service.os.chmod"), \
                    patch("service.threading.Thread"), patch("service.loc_monitor.start") as start, \
                    patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(service.run(), 0)
            start.assert_called_once()
            self.assertTrue(start.call_args.args[0].is_set())
            self.assertEqual(start.call_args.args[2], root / "loc-monitor.log")
            listener.close.assert_called_once()
            self.assertFalse((root / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
