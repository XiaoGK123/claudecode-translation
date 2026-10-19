#!/usr/bin/env python3
"""Block Chinese submissions and offer an English translation for resubmission."""
import json
import sys

from input_protection import needs_translation
from input_translate import translate_input
from translate_hook import configuration


def blocked(reason):
    return {"decision": "block", "reason": reason,
            "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "suppressOriginalPrompt": True}}


def handle(event, config):
    if event.get("hook_event_name") != "UserPromptSubmit":
        raise ValueError("expected UserPromptSubmit")
    prompt = event.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("expected string prompt")
    if not config.get("prompt_translation_enabled", True) or not needs_translation(prompt):
        return {}
    if prompt.lstrip().startswith("/"):
        return blocked("已拦截含中文或中文标点的命令。请保留命令名，将非保护区的参数改为英文后重新提交。")
    translated = translate_input(prompt, config)
    if needs_translation(translated):
        return blocked("译文的非保护区仍含中文或中文标点，原文未提交。请重试或手动改为英文。")
    return blocked("已拦截中文或中文标点输入。请复制以下英文重新提交：\n\n" + translated)


def main():
    try:
        output = handle(json.load(sys.stdin), configuration())
    except Exception as error:
        # Never expose provider response bodies, source prompts, or credentials.
        output = blocked(f"输入检查或翻译失败（{type(error).__name__}），未提交。请重试或手动改为英文。")
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
