import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from input_translate import INSTRUCTIONS, translate_input


class InputTranslationTests(unittest.TestCase):
    def test_original_input_sent_and_mixed_language_response_returned_verbatim(self):
        original = '请点击“确认”按钮，然后打开—设置页面—'
        reply = 'Click the “确认” button, then open —设置页面—.'
        config = {"api_key": "test-only"}
        with patch("input_translate.translate", return_value=reply) as request:
            self.assertEqual(translate_input(original, config), reply)
            request.assert_called_once_with(original, config, INSTRUCTIONS)

    def test_api_failure_propagates_for_original_text_recovery(self):
        with patch("input_translate.translate", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                translate_input('请点击“确认”', {})


if __name__ == "__main__":
    unittest.main()
