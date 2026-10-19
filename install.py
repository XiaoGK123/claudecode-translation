#!/usr/bin/env python3
"""Merge/remove this hook only, backing up existing settings before changes."""
import argparse
import json
import os
import shlex
import shutil
import sys
import tempfile
import time
from pathlib import Path
from translate_hook import configuration

ROOT = Path(__file__).resolve().parent


def update(settings, remove=False):
    settings = settings.expanduser().resolve()
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    hooks = data.setdefault("hooks", {})
    if not remove:
        config = configuration()
        timeout = float(config["hook_timeout_seconds"])
        network_timeout = float(config["timeout_seconds"])
        if not 0 < network_timeout < timeout < float("inf"):
            raise ValueError("hook_timeout_seconds must exceed positive timeout_seconds")
    for event, filename in (("MessageDisplay", "translate_hook.py"),
                            ("UserPromptSubmit", "prompt_hook.py")):
        command = shlex.join([sys.executable, str(ROOT / filename)])
        # Match exact owned commands; preserve other hooks and group metadata.
        cleaned = []
        for group in hooks.get(event, []):
            remaining = [h for h in group.get("hooks", []) if h.get("command") != command]
            if remaining:
                cleaned.append({**group, "hooks": remaining})
        if not remove:
            entry = {"type": "command", "command": command, "timeout": timeout}
            if event == "UserPromptSubmit":
                entry["onFailure"] = "block"
            cleaned.append({"hooks": [entry]})
        if cleaned:
            hooks[event] = cleaned
        else:
            hooks.pop(event, None)
    if settings.exists() and data == json.loads(settings.read_text(encoding="utf-8")):
        return settings, None
    settings.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if settings.exists():
        backup = settings.with_name(settings.name + f".backup-{time.time_ns()}")
        shutil.copy2(settings, backup)
    fd, temporary = tempfile.mkstemp(prefix=".translator-", dir=settings.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(data, target, indent=2, ensure_ascii=False)
            target.write("\n")
        if settings.exists():
            shutil.copymode(settings, temporary)
        os.replace(temporary, settings)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return settings, backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True,
                        help="Claude settings JSON to update")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    try:
        settings, backup = update(args.settings, args.remove)
    except Exception as error:
        print(f"Cannot update settings: {error}", file=sys.stderr)
        return 1
    print(f"{'Removed' if args.remove else 'Installed'} display translator: {settings}")
    if backup:
        print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
