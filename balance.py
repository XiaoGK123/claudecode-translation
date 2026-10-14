"""Read a supported provider's balance without exposing credentials."""
from providers import get_provider


def balance_label(config):
    if not config["show_balance"]:
        return None
    try:
        return get_provider(config).balance_label(config)
    except Exception:
        return "查询失败"
