"""Contract for API adapters. Transport and whitespace handling stay in the caller."""
from abc import ABC, abstractmethod


class APIProvider(ABC):
    @abstractmethod
    def build_request(self, text, config, instructions):
        """Return (endpoint suffix, JSON body)."""

    @abstractmethod
    def parse_response(self, data, config):
        """Return translated text or raise on incomplete/invalid output."""

    def balance_label(self, config):
        """Return a balance label, or None when balance is unsupported."""
        return None
