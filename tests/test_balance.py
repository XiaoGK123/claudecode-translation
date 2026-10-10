import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from balance import balance_label


class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.status = 200
        self.data = {"is_available": True, "balance_infos": [
            {"currency": "CNY", "total_balance": "110.00",
             "granted_balance": "10.00", "topped_up_balance": "100.00"}]}
        self.requests = []
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                case.requests.append((self.path, self.headers.get("Authorization")))
                self.send_response(case.status)
                self.end_headers()
                self.wfile.write(json.dumps(case.data).encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.config = {"show_balance": True, "api_key": "test-key",
                       "base_url": f"http://127.0.0.1:{self.server.server_port}/",
                       "balance_path": "/user/balance", "balance_timeout_seconds": 0.5}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_get_total_balance_with_auth(self):
        self.assertEqual(balance_label(self.config), "110.00 CNY")
        self.assertEqual(self.requests, [("/user/balance", "Bearer test-key")])

    def test_multiple_currencies_and_unavailable(self):
        self.data["balance_infos"].append({"currency": "USD", "total_balance": "2.00"})
        self.data["is_available"] = False
        self.assertEqual(balance_label(self.config), "110.00 CNY / 2.00 USD（不可用于 API 调用）")

    def test_error_does_not_raise_or_expose_key(self):
        self.status = 401
        self.assertEqual(balance_label(self.config), "查询失败（HTTP 401）")

    def test_disabled_or_missing_key_skips_request(self):
        self.config["show_balance"] = False
        self.assertIsNone(balance_label(self.config))
        self.config.update(show_balance=True, api_key="")
        self.assertEqual(balance_label(self.config), "未配置 API Key")
        self.assertEqual(self.requests, [])

    def test_bad_response_fails_safely(self):
        self.data = {"balance_infos": [{"currency": "CNY", "total_balance": "not a number"}]}
        self.assertEqual(balance_label(self.config), "查询失败")


if __name__ == "__main__":
    unittest.main()
