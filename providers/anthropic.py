"""Anthropic-compatible, non-streaming Messages API using the standard library."""
from .base import APIProvider


class AnthropicProvider(APIProvider):
    def request_headers(self, config):
        return {"x-api-key": config["api_key"],
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"}

    def build_request(self, text, config, instructions):
        if config["api_format"] != "messages":
            raise ValueError("Anthropic requires messages")
        return "/messages", {
            "model": config["model"], "system": instructions,
            "messages": [{"role": "user", "content": text}],
            "stream": False, "max_tokens": int(config["max_output_tokens"])}

    def parse_response(self, data, config):
        if (not isinstance(data, dict) or data.get("type") != "message" or data.get("role") != "assistant"
                or data.get("stop_reason") != "end_turn"):
            raise RuntimeError("Anthropic response not completed")
        content = data.get("content")
        if not isinstance(content, list):
            raise RuntimeError("Anthropic response has no content blocks")
        parts = []
        for part in content:
            if not isinstance(part, dict):
                raise RuntimeError("invalid Anthropic content block")
            if part.get("type") == "text":
                if not isinstance(part.get("text"), str):
                    raise RuntimeError("Anthropic text block has no text")
                parts.append(part["text"])
            elif part.get("type") not in ("thinking", "redacted_thinking"):
                raise RuntimeError("unexpected Anthropic content block")
        text = "".join(parts)
        if not text.strip():
            raise RuntimeError("Anthropic response has no text")
        return text
