"""Provider registry. Add an adapter here to extend supported API services."""
from urllib.parse import urlsplit

from .deepseek import DeepSeekProvider
from .openai_compatible import OpenAICompatibleProvider

PROVIDERS = {
    "deepseek": DeepSeekProvider(),
    "openai_compatible": OpenAICompatibleProvider(),
}


def legacy_provider(config):
    # Old configs did not distinguish provider from wire format.
    if (config.get("api_format") == "chat_completions"
            and urlsplit(config.get("base_url", "")).hostname == "api.deepseek.com"):
        return "deepseek"
    return "openai_compatible"


def get_provider(config):
    name = config["api_provider"] if "api_provider" in config else legacy_provider(config)
    if not isinstance(name, str) or name not in PROVIDERS:
        raise ValueError("unsupported api_provider")
    return PROVIDERS[name]
