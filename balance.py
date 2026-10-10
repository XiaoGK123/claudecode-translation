"""Read the provider's balance without logging credentials or response bodies."""
import json
import math
import re
import urllib.error
import urllib.request


def balance_label(config):
    if not config["show_balance"]:
        return None
    key = config.get("api_key")
    if not isinstance(key, str) or not key.strip():
        return "未配置 API Key"
    try:
        timeout = float(config["balance_timeout_seconds"])
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("invalid balance timeout")
        path = config["balance_path"]
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("invalid balance path")
        url = config["base_url"].strip().rstrip("/") + path
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + key, "Accept": "application/json"}, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        entries = data["balance_infos"]
        if not entries:
            return "暂无余额数据"
        amounts = []
        for entry in entries:
            currency = entry["currency"]
            amount = entry["total_balance"]
            if currency not in ("CNY", "USD") or not isinstance(amount, str) or not re.fullmatch(r"\d+(?:\.\d+)?", amount):
                raise ValueError("unexpected balance data")
            # Check the provider's numeric value before showing it in the terminal.
            number = float(amount)
            if not math.isfinite(number) or number < 0:
                raise ValueError("unexpected balance amount")
            amounts.append(f"{amount} {currency}")
        suffix = "（不可用于 API 调用）" if data.get("is_available") is False else ""
        return " / ".join(amounts) + suffix
    except urllib.error.HTTPError as error:
        return f"查询失败（HTTP {error.code}）"
    except Exception:
        return "查询失败"
