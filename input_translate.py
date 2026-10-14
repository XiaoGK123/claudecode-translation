"""Translate input to English while preserving Chinese in paired delimiters."""
import re
import sys

from translate_hook import configuration, translate, translation_prompt

CJK = re.compile(r"[\u3400-\u9fff]")



def translate_input(text, config):
    if not CJK.search(text):
        return text
    return translate(text, config, translation_prompt(config, "input_translation_prompt"))


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
