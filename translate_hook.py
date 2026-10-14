#!/usr/bin/env python3
"""Translate MessageDisplay deltas; never read or write Claude transcripts."""
import json
import math
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent



def configuration():
    result = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    path = ROOT / "config.json"
    if path.exists():
        result.update(json.loads(path.read_text(encoding="utf-8")))
    return result


def translation_prompt(config, key):
    prompt = config[key]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return prompt


def translate(text, config, instructions=None):
    if instructions is None:
        instructions = translation_prompt(config, "reply_translation_prompt")
    key = config.get("api_key")
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError("missing api_key in config.json")
    timeout = float(config["timeout_seconds"])
    hook_timeout = float(config["hook_timeout_seconds"])
    if not math.isfinite(timeout) or not math.isfinite(hook_timeout) or not 0 < timeout < hook_timeout:
        raise RuntimeError("timeout_seconds must be positive and below hook_timeout_seconds")
    base = config["base_url"].strip().rstrip("/")
    api_format = config["api_format"]
    if api_format == "responses":
        endpoint = "/responses"
        body = {"model": config["model"], "instructions": instructions,
                "input": text, "store": False,
                "max_output_tokens": int(config["max_output_tokens"])}
    elif api_format == "chat_completions":
        endpoint = "/chat/completions"
        body = {"model": config["model"], "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": text}], "stream": False,
            "max_tokens": int(config["max_output_tokens"])}
        thinking = config.get("thinking_type")
        if thinking is not None:
            if thinking not in ("enabled", "disabled"):
                raise RuntimeError("invalid thinking_type")
            body["thinking"] = {"type": thinking}
    else:
        raise RuntimeError("unsupported api_format")
    request = urllib.request.Request(
        base + endpoint, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    if api_format == "responses":
        if data.get("status") != "completed":
            raise RuntimeError("API response not completed")
        chunks = [part["text"] for item in data.get("output", [])
                  if item.get("type") == "message" and item.get("role") == "assistant"
                  for part in item.get("content", [])
                  if part.get("type") == "output_text" and isinstance(part.get("text"), str)]
        translated = "".join(chunks)
    else:
        choice = data["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise RuntimeError("chat response not completed")
        translated = choice.get("message", {}).get("content")
        if not isinstance(translated, str):
            raise RuntimeError("chat response has no text")
    if not translated.strip():
        raise RuntimeError("API returned no translated text")
    # Preserve the exact boundary whitespace so adjacent display batches don't join.
    leading = re.match(r"^\s*", text).group()
    trailing = re.search(r"\s*$", text).group()
    return leading + translated.strip() + trailing


def main():
    output = {}
    try:
        event = json.load(sys.stdin)
        text = event.get("delta")
        if event.get("hook_event_name") != "MessageDisplay" or not isinstance(text, str):
            raise RuntimeError("expected MessageDisplay input with string delta")
        config = configuration()
        if config.get("enabled", True) and text.strip() and re.search(r"[A-Za-z]", text):
            translated = translate(text, config)
            if config.get("display_mode", "chinese") == "bilingual":
                quoted = "".join("> " + line for line in text.lstrip("\r\n").splitlines(keepends=True))
                display = translated.rstrip() + "\n\n" + quoted
            else:
                display = translated
            output = {"hookSpecificOutput": {"hookEventName": "MessageDisplay",
                                             "displayContent": display}}
    except urllib.error.HTTPError as error:
        # Never log API bodies: they may contain original text or credentials.
        print(f"display-translator: API HTTP {error.code}; showing original", file=sys.stderr)
    except Exception as error:
        print(f"display-translator: {type(error).__name__}; showing original", file=sys.stderr)
    print(json.dumps(output, ensure_ascii=False))
    # Empty JSON means no replacement; Claude displays the original delta.
    return 0


if __name__ == "__main__":
    sys.exit(main())
