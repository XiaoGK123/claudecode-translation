"""Build and run the macOS Option+A helper; no third-party Python dependencies."""
import subprocess
import select
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def launch():
    if sys.platform != "darwin":
        raise RuntimeError("global hotkey requires macOS")
    source = ROOT / "macos_hotkey.swift"
    binary = ROOT / ".runtime" / "input-hotkey"
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        result = subprocess.run(["/usr/bin/swiftc", str(source), "-o", str(binary)],
                                capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError("Swift compilation failed; install Xcode Command Line Tools")
    # Readiness is sent through stdout; ongoing errors go to the private service log.
    log = (ROOT / ".runtime" / "hotkey.log").open("ab")
    try:
        process = subprocess.Popen([str(binary), sys.executable, str(ROOT / "input_translate.py")],
                                   stdout=subprocess.PIPE, stderr=log, text=True)
    finally:
        log.close()
    if not select.select([process.stdout], [], [], 5)[0]:
        stop(process)
        raise RuntimeError("hotkey helper did not become ready")
    message = process.stdout.readline().strip()
    if message != "Option+A 已注册":
        stop(process)
        raise RuntimeError(message or "hotkey helper failed to start")
    return process


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
