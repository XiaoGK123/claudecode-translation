import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import translation_log as log


class TranslationLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "logs"
        self.patcher = patch.object(log, "LOG_DIR", self.directory)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def records(self):
        return [json.loads(p.read_text()) for p in self.directory.glob("*.json")]

    def test_success_and_permissions(self):
        result = log.logged_translation("input", "你好", {"api_key": "secret", "model": "test"}, lambda: "Hello")
        self.assertEqual(result, "Hello")
        record, = self.records()
        self.assertEqual(record["original"], "你好")
        self.assertEqual(record["translated"], "Hello")
        self.assertEqual(record["status"], "success")
        self.assertNotIn("secret", json.dumps(record))
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(next(self.directory.glob("*.json")).stat().st_mode & 0o777, 0o600)

    def test_failure_does_not_log_exception_message(self):
        def fail():
            raise ValueError("secret response")
        with self.assertRaises(ValueError):
            log.logged_translation("reply", "source", {}, fail)
        record, = self.records()
        self.assertEqual(record["error_type"], "ValueError")
        self.assertNotIn("secret response", json.dumps(record))

    def test_expiration_boundary(self):
        self.directory.mkdir()
        for name in ("1000_request.json", "1001_request.json", "999_request.tmp"):
            (self.directory / name).write_text("{}")
        log.cleanup(now=1300)
        self.assertEqual([p.name for p in self.directory.iterdir()], ["1001_request.json"])

    def test_write_failure_does_not_break_translation(self):
        with patch.object(Path, "mkdir", side_effect=OSError):
            self.assertEqual(log.logged_translation("reply", "source", {}, lambda: "result"), "result")

    def test_concurrent_requests(self):
        threads = [threading.Thread(target=log.logged_translation, args=("input", str(i), {}, lambda: "done")) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.records()), 12)
        self.assertTrue(all(r["status"] == "success" for r in self.records()))

    def test_cleanup_schedule(self):
        stopped = unittest.mock.Mock()
        stopped.wait.side_effect = [False, True]
        with patch.object(log, "cleanup") as cleanup:
            thread = log.start(stopped)
            thread.join(2)
            self.assertEqual(cleanup.call_count, 2)
            stopped.wait.assert_called_with(60)
