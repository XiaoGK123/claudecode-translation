#!/usr/bin/env python3
"""Check submissions locally and block unprotected Chinese without translation."""
import json
import sys

from input_protection import needs_translation
from translate_hook import configuration


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
    if not config.get("prompt_guard_enabled", True) or not needs_translation(prompt):
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
