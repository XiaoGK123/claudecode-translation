"""Contract for API adapters, with a standard-library transport by default."""
import json
import urllib.request
from abc import ABC, abstractmethod


class APIProvider(ABC):
    @abstractmethod
    def build_request(self, text, config, instructions):
        """Return (endpoint suffix, JSON body)."""

    @abstractmethod
    def parse_response(self, data, config):
        """Return translated text or raise on incomplete/invalid output."""

    def request(self, text, config, instructions, timeout):
        """Send a request and return parsed translation text."""
        endpoint, body = self.build_request(text, config, instructions)
        base = config["base_url"].strip().rstrip("/")
        request = urllib.request.Request(
            base + endpoint, data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": "Bearer " + config["api_key"],
                     "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        return self.parse_response(data, config)

    def balance_label(self, config):
        """Return a balance label, or None when balance is unsupported."""
        return None
