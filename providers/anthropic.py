"""Anthropic-compatible, non-streaming Messages API using the standard library."""
from urllib.parse import urlsplit

from .base import APIProvider


class AnthropicProvider(APIProvider):
    def request_headers(self, config):
        return {"x-api-key": config["api_key"],
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"}

    def build_request(self, text, config, instructions):
        if config["api_format"] != "messages":
            raise ValueError("Anthropic requires messages")
        # Match Messages clients that accept either a gateway root or its /v1 root.
        path = urlsplit(config["base_url"].strip()).path.rstrip("/")
        endpoint = "/messages" if path.endswith("/v1") else "/v1/messages"
        return endpoint, {
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
