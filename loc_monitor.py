"""Check the Claude web egress region in the background and notify on macOS."""
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

TRACE_URL = "https://claude.ai/cdn-cgi/trace"
INTERVAL_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 10
NOTIFICATION_TITLE = "Claude Code 出口地区监测"
NOTIFICATION_SCRIPT = """on run argv
    display notification (item 1 of argv) with title (item 2 of argv)
end run"""


class TraceError(ValueError):
    pass


def read_loc():
    request = urllib.request.Request(TRACE_URL, headers={"Accept": "text/plain"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        # A trace is small. Bound memory usage and reject HTML/error documents.
        data = response.read(16385)
    if len(data) > 16384:
        raise TraceError("响应过大")
    values = [line.split("=", 1)[1].strip() for line in data.decode("utf-8").splitlines()
              if line.startswith("loc=")]
    if not values:
        raise TraceError("响应缺少 loc 字段")
    if len(values) != 1 or not re.fullmatch(r"[A-Z]{2}", values[0]):
        raise TraceError("响应的 loc 字段无效")
    return values[0]


def check(config):
    """Return (deduplication key, notification text), or None when healthy/off."""
    if not config.get("loc_monitor_enabled", True):
        return None
    expected = config.get("expected_loc", "SG")
    if not isinstance(expected, str) or not re.fullmatch(r"[A-Za-z]{2}", expected):
        return ("config",), "出口地区检查失败：expected_loc 必须为两位地区代码"
    expected = expected.upper()
    try:
        actual = read_loc()
    except TraceError as error:
        return ("trace", str(error)), "出口地区检查失败：" + str(error)
    except urllib.error.HTTPError as error:
        return ("http", error.code), f"出口地区检查失败：请求失败（HTTP {error.code}）"
    except Exception as error:
        name = type(error).__name__
        return ("request", name), f"出口地区检查失败：请求失败（{name}）"
    if actual != expected:
        return ("mismatch", actual, expected), f"出口地区异常：当前 {actual}，预期 {expected}"
    return None


def notify(message):
    # Pass text as argv, never interpolate network/configuration data into code.
    subprocess.run(["/usr/bin/osascript", "-e", NOTIFICATION_SCRIPT,
                    message, NOTIFICATION_TITLE], check=True,
                   capture_output=True, timeout=5)


def monitor(stopped, configuration, log):
    last_alert = None
    while not stopped.is_set():
        started = time.monotonic()
        try:
            problem = check(configuration())
        except Exception:
            problem = (("config",), "出口地区检查失败：无法读取配置")
        if stopped.is_set():
            return
        if problem is None:
            last_alert = None
        else:
            key, message = problem
            if key != last_alert:
                log(message)
                try:
                    notify(message)
                except Exception as error:
                    # Leave the incident unacknowledged; retry on the next check.
                    log(f"系统通知发送失败（{type(error).__name__}）")
                else:
                    last_alert = key
        if stopped.wait(max(0, INTERVAL_SECONDS - (time.monotonic() - started))):
            return


def start(stopped, configuration, log_path):
    if sys.platform != "darwin":
        return None

    def log(message):
        # Do not log the trace body (which contains IP/user-agent) or credentials.
        try:
            fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as target:
                target.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
        except OSError:
            pass

    thread = threading.Thread(target=monitor, args=(stopped, configuration, log),
                              name="loc-monitor", daemon=True)
    thread.start()
    return thread
