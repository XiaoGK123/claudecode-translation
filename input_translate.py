"""Translate input to English while preserving Chinese in paired delimiters."""
import sys

from input_protection import DEFAULT_HAN_RATIO_THRESHOLD, needs_translation, protect, restore
from translate_hook import configuration, translate, translation_prompt



def translate_input(text, config):
    if not needs_translation(text, config.get("han_ratio_threshold", DEFAULT_HAN_RATIO_THRESHOLD)):
        return text
    masked, replacements, prefix = protect(text)
    prompt = translation_prompt(config, "input_translation_prompt")
    if replacements:
        prompt += "\nKeep each __KEEP_ placeholder exactly once, unchanged. Add none."
    result = translate(masked, config, prompt)
    return restore(result, replacements, prefix)


def main():
    try:
        text = sys.stdin.read()
        result = translate_input(text, configuration())
    except Exception as error:
        print(f"输入翻译失败：{type(error).__name__}", file=sys.stderr)
        return 1
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
