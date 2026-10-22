"""Mask paired Chinese passages and Markdown code before input translation."""
import re
import math
import unicodedata
import uuid

DEFAULT_HAN_RATIO_THRESHOLD = 0.2
PAIRS = dict(zip('“‘「『（【〔《〈([{', '”’」』）】〕》〉)]}'))
CLOSERS = set(PAIRS.values())


class PlaceholderError(ValueError):
    """The translated response did not preserve the protected placeholders."""


def is_han(char):
    """Recognize assigned unified/compatibility ideographs in Python's Unicode data."""
    return unicodedata.name(char, "").startswith(
        ("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-"))


def has_chinese(text):
    """Detect Han ideographs only, excluding punctuation."""
    return any(is_han(char) for char in text)


def needs_translation(text, threshold=DEFAULT_HAN_RATIO_THRESHOLD):
    """Compare unprotected Han / all letters against the inclusive threshold."""
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or not 0 <= threshold <= 1):
        raise ValueError("han_ratio_threshold must be a finite number between 0 and 1")
    han = letters = previous = 0
    # Count original text only: placeholder letters must not dilute the ratio.
    for start, end in protected_spans(text) + [(len(text), len(text))]:
        for char in text[previous:start]:
            if is_han(char):
                han += 1
                letters += 1
            elif char.isalpha():
                letters += 1
        previous = end
    return han > 0 and han / letters >= threshold


def _escaped(text, index):
    start = index
    while start and text[start - 1] == "\\":
        start -= 1
    return (index - start) % 2 == 1


def _code_spans(text):
    spans = []
    index = 0
    while index < len(text):
        if text[index] != "`" or _escaped(text, index):
            index += 1
            continue
        run = re.match(r"`+", text[index:]).group()
        line_start = text.rfind("\n", 0, index) + 1
        indent = text[line_start:index]
        if len(run) >= 3 and re.fullmatch(r" {0,3}", indent):
            # Fences close on a separate line with at least as many backticks.
            opening_end = text.find("\n", index)
            closing = None if opening_end < 0 else re.search(
                r"^ {0,3}`{" + str(len(run)) + r",}[ \t]*\r?$",
                text[opening_end + 1:], re.MULTILINE)
            end = len(text) if closing is None else opening_end + 1 + closing.end()
        else:
            # Inline code uses a closing run of exactly the same length.
            closing = re.search(r"(?<!`)" + run + r"(?!`)", text[index + len(run):])
            if closing is None:
                index += len(run)
                continue
            end = index + len(run) + closing.end()
        spans.append((index, end))
        index = end
    return spans


def protected_spans(text):
    code = _code_spans(text)
    spans = list(code)
    code_index = 0
    stack = []
    index = 0
    while index < len(text):
        if code_index < len(code) and index == code[code_index][0]:
            index = code[code_index][1]
            code_index += 1
            continue
        char = text[index]
        if (char in PAIRS or char in CLOSERS or char == '"') and not _escaped(text, index):
            if char == '"':
                if stack and stack[-1][0] == '"':
                    _, start = stack.pop()
                    if has_chinese(text[start:index + 1]):
                        spans.append((start, index + 1))
                else:
                    stack.append(('"', index))
            elif char in PAIRS:
                stack.append((PAIRS[char], index))
            elif char in CLOSERS:
                if stack and stack[-1][0] == char:
                    _, start = stack.pop()
                    if has_chinese(text[start:index + 1]):
                        # Chinese double quotes remain visible to the translator
                        # so it can normalize them to English punctuation.
                        spans.append((start + 1, index) if text[start] == '“'
                                     else (start, index + 1))
                else:
                    # A malformed nesting must not create a false outer match.
                    stack.clear()
        index += 1
    # Keep the outermost protected interval; nested content is preserved with it.
    result = []
    for start, end in sorted(spans, key=lambda span: (span[0], -span[1])):
        if not result or start >= result[-1][1]:
            result.append((start, end))
    return result


def protect(text):
    spans = protected_spans(text)
    prefix = "__KEEP_" + uuid.uuid4().hex + "_"
    while prefix in text:
        prefix = "__KEEP_" + uuid.uuid4().hex + "_"
    replacements = {}
    parts = []
    previous = 0
    for index, (start, end) in enumerate(spans):
        token = f"{prefix}{index}__"
        replacements[token] = text[start:end]
        parts.extend((text[previous:start], token))
        previous = end
    parts.append(text[previous:])
    return "".join(parts), replacements, prefix


def restore(text, replacements, prefix):
    for token in replacements:
        if text.count(token) != 1:
            raise PlaceholderError("protected placeholder missing or duplicated")
    # Reject invented tokens as well as damaged tokens containing our nonce.
    remainder = text
    for token in replacements:
        remainder = remainder.replace(token, "")
    if prefix[7:-1] in remainder:
        raise PlaceholderError("unexpected protected placeholder")
    pattern = re.compile("|".join(re.escape(token) for token in replacements))
    return pattern.sub(lambda match: replacements[match.group()], text) if replacements else text
