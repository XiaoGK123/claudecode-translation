#!/usr/bin/env python3
"""Run in the foreground; register the Hook on launch and remove it on exit."""
import argparse
import fcntl
import json
import math
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

from install import update
from balance import balance_label
from translate_hook import configuration
import hotkey
import loc_monitor
from input_protection import DEFAULT_HAN_RATIO_THRESHOLD

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
SOCKET = RUNTIME / "control.sock"
STATE = RUNTIME / "state.json"


def settings_path():
    path = Path(configuration()["settings_file"]).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def prepare_runtime():
    RUNTIME.mkdir(mode=0o700, exist_ok=True)


def control(action):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(SOCKET))
        client.sendall((action + "\n").encode())
        chunks = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return json.loads(b"".join(chunks))


def active():
    try:
        return control("status")
    except (OSError, ValueError):
        return None


def refresh_interval(config):
    interval = float(config["balance_refresh_seconds"])
    if not math.isfinite(interval) or interval < 0.2:
        raise ValueError("balance_refresh_seconds must be at least 0.2")
    return interval


def feature_status(config):
    threshold = config.get("han_ratio_threshold", DEFAULT_HAN_RATIO_THRESHOLD)
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not 0 <= threshold <= 1):
        ratio = "配置无效"
    else:
        ratio = f"{threshold * 100:.10f}".rstrip("0").rstrip(".") + "%"
    region = "已开启" if config.get("loc_monitor_enabled", True) else "已关闭"
    return f"中文提交检查 已开启（汉字比例阈值 {ratio}） | 出口地区监测 {region}"


def fit_status_line(text, columns):
    """Wrap the complete status, leaving room before the terminal's right margin."""
    text = "".join(" " if unicodedata.category(char).startswith("C") else char
                   for char in text)
    limit = max(2, columns - 1)
    widths = [0 if unicodedata.combining(char) else
              2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
              for char in text]
    used = 0
    result = []
    for char, width in zip(text, widths):
        if used + width > limit:
            result.append("\n")
            used = 0
        result.append(char)
        used += width
    return "".join(result)


def refresh_balance(stopped, results, interval):
    while not stopped.wait(interval):
        try:
            config = configuration()
            interval = refresh_interval(config)
            label = balance_label(config)
        except Exception:
            label = "配置读取失败"
            interval = 30
        if not stopped.is_set():
            results.put(label)


def run():
    prepare_runtime()
    with (RUNTIME / "service.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("服务已经运行，请先关闭原服务窗口。", flush=True)
            return 0
        running = True
        listener = None
        stop_client = None
        hotkey_process = None
        stopped = threading.Event()
        results = queue.SimpleQueue()
        terminal_line = False
        settings = settings_path()

        def shutdown(signum, frame):
            nonlocal running
            running = False
            stopped.set()

        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, shutdown)
        try:
            # Recover an orphaned registration from an earlier crashed run.
            if STATE.exists():
                old = json.loads(STATE.read_text())
                update(Path(old["settings_file"]), remove=True)
            SOCKET.unlink(missing_ok=True)
            STATE.write_text(json.dumps({"settings_file": str(settings)}))
            update(settings)
            if not running:
                return 0
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(SOCKET))
            os.chmod(SOCKET, 0o600)
            listener.listen(5)
            listener.settimeout(0.25)
            config = configuration()
            interval = refresh_interval(config)
            balance = balance_label(config)
            if not running:
                return 0
            prefix = f"服务运行中 | Hook 已安装 | 模型 {config['model']}"
            if config.get("input_translation_enabled", False):
                try:
                    hotkey_process = hotkey.launch()
                    prefix += " | Option+A 已启用"
                except Exception as error:
                    prefix += f" | Option+A 未启用：{error}"
            terminal_line = sys.stdout.isatty()
            switches = feature_status(config)
            last_switch_check = time.monotonic()
            status_rows = 1

            def render(label, initial=False):
                nonlocal status_rows
                balance_status = f" | 余额 {label}" if label is not None else ""
                line = prefix + " | " + switches + balance_status + " | 按 Ctrl+C 关闭并删除 Hook"
                if terminal_line:
                    try:
                        columns = os.get_terminal_size(sys.stdout.fileno()).columns
                    except (AttributeError, OSError, ValueError):
                        columns = shutil.get_terminal_size().columns
                    line = fit_status_line(line, columns)
                    # Clear from the last status row upwards, then redraw the block.
                    clear = "\r\033[2K" + "\033[1A\r\033[2K" * (status_rows - 1)
                    print(clear + line.replace("\n", "\r\n"), end="", flush=True)
                    status_rows = line.count("\n") + 1
                elif initial:
                    print(line, flush=True)

            render(balance, initial=True)
            loc_monitor.start(stopped, configuration, RUNTIME / "loc-monitor.log")
            threading.Thread(target=refresh_balance, args=(stopped, results, interval),
                             daemon=True).start()
            while running:
                if time.monotonic() - last_switch_check >= 1:
                    last_switch_check = time.monotonic()
                    try:
                        refreshed_switches = feature_status(configuration())
                    except Exception:
                        refreshed_switches = "功能开关 配置读取失败"
                    if refreshed_switches != switches:
                        switches = refreshed_switches
                        render(balance)
                if hotkey_process is not None and hotkey_process.poll() is not None:
                    prefix = prefix.replace("Option+A 已启用", "Option+A 已停止，请重启服务")
                    hotkey_process = None
                    render(balance)
                try:
                    refreshed = results.get_nowait()
                except queue.Empty:
                    pass
                else:
                    balance = refreshed
                    render(refreshed)
                try:
                    client, _ = listener.accept()
                except socket.timeout:
                    continue
                try:
                    client.settimeout(1)
                    action = client.recv(64).decode().strip()
                    if action == "stop":
                        stop_client = client
                        running = False
                    else:
                        reply = {"running": True, "pid": os.getpid(),
                                 "settings_file": str(settings)}
                        client.sendall(json.dumps(reply).encode())
                finally:
                    if client is not stop_client:
                        client.close()
        finally:
            stopped.set()
            hotkey.stop(hotkey_process)
            if terminal_line:
                print(flush=True)
            cleanup_error = None
            try:
                if STATE.exists():
                    saved = json.loads(STATE.read_text())
                    update(Path(saved["settings_file"]), remove=True)
                    STATE.unlink()
            except Exception as error:
                cleanup_error = type(error).__name__
                print(f"Hook cleanup failed: {cleanup_error}; run service.py stop again", flush=True)
            finally:
                if listener:
                    listener.close()
                SOCKET.unlink(missing_ok=True)
                if stop_client:
                    try:
                        stop_client.sendall(json.dumps({"running": False,
                                                      "cleanup_error": cleanup_error}).encode())
                    except OSError:
                        pass
                    stop_client.close()
            print("服务已关闭，Hook 已删除。" if not cleanup_error else "服务已关闭，但 Hook 删除失败。", flush=True)
            if cleanup_error:
                return 1
    return 0


def start():
    info = active()
    if info:
        print(f"Already running (PID {info['pid']}), hook: {info['settings_file']}")
        return 0
    prepare_runtime()
    # Validate settings before dispatch so configuration errors are actionable.
    settings_path()
    with (RUNTIME / "service.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, str(ROOT / "service.py"), "_run"],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True, close_fds=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        info = active()
        if info:
            print(f"Started (PID {info['pid']}), hook: {info['settings_file']}")
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.1)
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
    print(f"Start failed; check {RUNTIME / 'service.log'}", file=sys.stderr)
    return 1


def stop():
    try:
        result = control("stop")
        if result.get("cleanup_error"):
            print("Service stopped but hook cleanup failed; check service.log", file=sys.stderr)
            return 1
        print("Stopped; translation hook removed")
        return 0
    except (OSError, ValueError):
        pass
    # No PID signalling: use the lock to safely clean orphaned registrations.
    prepare_runtime()
    with (RUNTIME / "service.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Service is starting or stopping; retry shortly", file=sys.stderr)
            return 1
        if STATE.exists():
            old = json.loads(STATE.read_text())
            update(Path(old["settings_file"]), remove=True)
            STATE.unlink()
        SOCKET.unlink(missing_ok=True)
    print("Stopped; any service-owned residual hook removed")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="run",
                        choices=("run", "start", "stop", "status", "_run"))
    args = parser.parse_args()
    try:
        if args.action in ("run", "start", "_run"):
            config_path = ROOT / "config.json"
            if not config_path.exists():
                template = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
                template["api_key"] = ""
                try:
                    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(fd, "w", encoding="utf-8") as target:
                        json.dump(template, target, ensure_ascii=False, indent=2)
                        target.write("\n")
                    print(f"无config.json文件，目前已自动生成，文件位置：{config_path}，请配置api信息后重启", flush=True)
                    return 0
        if args.action == "start":
            return start()
        if args.action == "stop":
            return stop()
        if args.action in ("run", "_run"):
            return run()
        info = active()
        if info:
            print(f"Running (PID {info['pid']}), hook: {info['settings_file']}")
        else:
            print("Stopped" + ("; residual hook may remain, run service.py stop" if STATE.exists() else ""))
        return 0
    except Exception as error:
        print(f"Service failed: {type(error).__name__}; check configuration and service.log", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
