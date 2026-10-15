"""Chat Completions and Responses with configurable SDK extension fields."""
from .base import APIProvider


class OpenAICompatibleProvider(APIProvider):
    def request(self, text, config, instructions, timeout):
        _, body = self.build_request(text, config, instructions)
        extra_body = config.get("extra_body", {})
        if not isinstance(extra_body, dict):
            raise ValueError("extra_body must be a JSON object")
        # Load lazily so DeepSeek can run without the optional SDK dependency.
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("OpenAI compatible mode requires pip install -r requirements.txt") from None
        with OpenAI(api_key=config["api_key"],
                    base_url=config["base_url"].strip().rstrip("/"),
                    timeout=timeout, max_retries=0,
                    organization="", project="") as client:
            if config["api_format"] == "responses":
                response = client.responses.create(**body, extra_body=extra_body)
            else:
                response = client.chat.completions.create(**body, extra_body=extra_body)
        return self.parse_response(response.model_dump(), config)

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
