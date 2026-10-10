#!/usr/bin/env python3
"""Run in the foreground; register the Hook on launch and remove it on exit."""
import argparse
import fcntl
import json
import math
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from install import update
from balance import balance_label
from translate_hook import configuration

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
            terminal_line = sys.stdout.isatty()

            def render(label, initial=False):
                balance_status = f" | 余额 {label}" if label is not None else ""
                line = prefix + balance_status + " | 按 Ctrl+C 关闭并删除 Hook"
                if terminal_line:
                    print("\r\033[2K" + line, end="", flush=True)
                elif initial:
                    print(line, flush=True)

            render(balance, initial=True)
            threading.Thread(target=refresh_balance, args=(stopped, results, interval),
                             daemon=True).start()
            while running:
                try:
                    refreshed = results.get_nowait()
                except queue.Empty:
                    pass
                else:
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
