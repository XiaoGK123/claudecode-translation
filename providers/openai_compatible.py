"""Standard Chat Completions and Responses payloads, without vendor extensions."""
from .base import APIProvider


class OpenAICompatibleProvider(APIProvider):
    def build_request(self, text, config, instructions):
        api_format = config["api_format"]
        if api_format == "responses":
            return "/responses", {
                "model": config["model"], "instructions": instructions,
                "input": text, "store": False,
                "max_output_tokens": int(config["max_output_tokens"])}
        if api_format == "chat_completions":
            return "/chat/completions", {
                "model": config["model"], "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": text}],
                "stream": False, "max_tokens": int(config["max_output_tokens"])}
        raise ValueError("unsupported api_format")

    def parse_response(self, data, config):
        if config["api_format"] == "responses":
            if data.get("status") != "completed":
                raise RuntimeError("API response not completed")
            return "".join(
                part["text"] for item in data.get("output", [])
                if item.get("type") == "message" and item.get("role") == "assistant"
                for part in item.get("content", [])
                if part.get("type") == "output_text" and isinstance(part.get("text"), str))
        choice = data["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise RuntimeError("chat response not completed")
        translated = choice.get("message", {}).get("content")
        if not isinstance(translated, str):
            raise RuntimeError("chat response has no text")
        return translated
