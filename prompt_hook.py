#!/usr/bin/env python3
"""Check submissions locally and block unprotected Chinese without translation."""
import json
import fcntl
import hashlib
import os
import sys
from pathlib import Path

from input_protection import DEFAULT_HAN_RATIO_THRESHOLD, needs_translation
from translate_hook import configuration

STATE_DIR = Path(__file__).resolve().parent / ".runtime" / "prompt-guard"


def consume_retry(session_id, prompt):
    """Remember only the last blocked digest; consume an exact retry once."""
    if not isinstance(session_id, str) or not session_id:
        return False
    session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    path = STATE_DIR / (session_key + ".state")
    if prompt is None and not path.exists():
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt is not None else ""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+", encoding="ascii") as state:
        # Hook invocations are separate processes; serialize each session.
        fcntl.flock(state, fcntl.LOCK_EX)
        previous = state.read()
        repeated = bool(digest) and previous == digest
        state.seek(0)
        state.write("" if repeated else digest)
        state.truncate()
    return repeated


def blocked():
    return {"decision": "block", "reason": "检测到未受保护的中文片段",
            "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "suppressOriginalPrompt": True}}


def handle(event, config):
    if event.get("hook_event_name") != "UserPromptSubmit":
        raise ValueError("expected UserPromptSubmit")
    prompt = event.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("expected string prompt")
    matches = config.get("prompt_guard_enabled", True) and needs_translation(
        prompt, config.get("han_ratio_threshold", DEFAULT_HAN_RATIO_THRESHOLD))
    repeated = consume_retry(event.get("session_id"), prompt if matches else None)
    if not matches or repeated:
        return {}
    return blocked()


def main():
    try:
        output = handle(json.load(sys.stdin), configuration())
    except Exception:
        # Only a successful rule match may block; errors must allow submission.
        # Do not expose source prompts, configuration, or error details.
        output = {}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
