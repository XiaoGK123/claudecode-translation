import sys
import re
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from input_translate import translate_input
from input_protection import PAIRS, protect, protected_spans, restore
from translate_hook import configuration


class InputTranslationTests(unittest.TestCase):
    def test_protected_input_is_masked_and_restored(self):
        original = '请点击“确认”按钮，然后打开—设置页面—'
        reply = 'Click the “确认” button, then open —settings page—.'
        config = configuration()
        config["api_key"] = "test-only"
        def response(text, config, prompt):
            self.assertNotIn('确认', text)
            self.assertIn('—设置页面—', text)
            self.assertIn('Keep each __KEEP_', prompt)
            token = text.split('请点击', 1)[1].split('按钮', 1)[0]
            return f'Click the {token} button, then open —settings page—.'
        with patch("input_translate.translate", side_effect=response) as request:
            self.assertEqual(translate_input(original, config), reply)
            request.assert_called_once()

    def test_custom_input_prompt(self):
        config = {"input_translation_prompt": "Custom input instructions"}
        with patch("input_translate.translate", return_value="Hello") as request:
            self.assertEqual(translate_input("你好", config), "Hello")
            request.assert_called_once_with("你好", config, "Custom input instructions")

    def test_invalid_input_prompt(self):
        for prompt in ("", "   ", None, 42):
            with self.subTest(prompt=prompt), patch("input_translate.translate") as request:
                with self.assertRaises(ValueError):
                    translate_input("你好", {"input_translation_prompt": prompt})
                request.assert_not_called()

    def test_api_failure_propagates_for_original_text_recovery(self):
        with patch("input_translate.translate", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                translate_input('请点击“确认”', configuration())

    def test_only_protected_chinese_skips_api(self):
        for text in ('“确认”', 'Click 【设置】', '`中文`', '```python\n中文\n```'):
            with self.subTest(text=text), patch('input_translate.translate') as request:
                self.assertEqual(translate_input(text, {}), text)
                request.assert_not_called()

    def test_invalid_placeholders_fail_without_stdout(self):
        import io
        from input_translate import main
        for damage in ('missing', 'duplicate', 'changed', 'unknown'):
            def response(text, config, prompt):
                token = text[len('请点击'):]
                return {'missing': 'Click', 'duplicate': token + token,
                        'changed': token.lower(),
                        'unknown': token + token.replace('_0__', '_99__')}[damage]
            with self.subTest(damage=damage), patch('input_translate.translate', side_effect=response), \
                    patch('input_translate.configuration', return_value=configuration()), \
                    patch('sys.stdin', io.StringIO('请点击“确认”')), \
                    patch('sys.stdout', new_callable=io.StringIO) as output, \
                    patch('sys.stderr', new_callable=io.StringIO) as error:
                self.assertEqual(main(), 1)
                self.assertEqual(output.getvalue(), '')
                self.assertIn('PlaceholderError', error.getvalue())

    def test_protected_roundtrip_through_both_api_formats(self):
        import json
        import httpx
        from openai import OpenAI
        for api_format in ('chat_completions', 'responses'):
            config = configuration()
            config.update(api_key='test-only', api_provider='openai_compatible',
                          api_format=api_format)
            def api(request):
                body = json.loads(request.content)
                payload = json.dumps(body, ensure_ascii=False)
                self.assertNotIn('确认', payload)
                token = re.search(r'__KEEP_[a-f0-9]+_0__', payload).group()
                reply = 'Click ' + token
                if api_format == 'chat_completions':
                    data = {'choices': [{'message': {'content': reply}, 'finish_reason': 'stop'}]}
                else:
                    data = {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                            'content': [{'type': 'output_text', 'text': reply}]}]}
                return httpx.Response(200, json=data)
            def client(**kwargs):
                return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(api)))
            with self.subTest(api_format=api_format), \
                    patch('openai.OpenAI', side_effect=client):
                self.assertEqual(translate_input('请点击“确认”', config), 'Click “确认”')


class InputProtectionTests(unittest.TestCase):
    def assert_spans(self, text, expected):
        self.assertEqual([text[start:end] for start, end in protected_spans(text)], expected)

    def test_all_supported_pairs(self):
        for opening, closing in {**PAIRS, '"': '"'}.items():
            with self.subTest(opening=opening):
                passage = opening + '中文\n内容' + closing
                self.assert_spans('翻译' + passage + '文字', [passage])
                self.assert_spans(opening + 'English' + closing, [])

    def test_outermost_nested_and_multiline(self):
        self.assert_spans('请看【设置（“确认”）\n页面】然后「帮助」',
                          ['【设置（“确认”）\n页面】', '「帮助」'])
        self.assert_spans('【未闭合 “确认”', ['“确认”'])

    def test_unclosed_and_malformed_pairs(self):
        for text in ('“中文', '(中文]', '【中文）】', '中文”', "'中文'", '—中文—'):
            with self.subTest(text=text):
                self.assert_spans(text, [])

    def test_escaped_quotes_and_backslash_parity(self):
        self.assert_spans(r'请说"中文\"内容"', ['"中文\\"内容"'])
        self.assert_spans(r'\"中文\"', [])
        self.assert_spans(r'\\"中文"', ['"中文"'])

    def test_code_is_opaque_and_always_protected(self):
        self.assert_spans('执行 `print("hello")` 然后 ``a`b``',
                          ['`print("hello")`', '``a`b``'])
        self.assert_spans('请看【中文 `)]}` 内容】', ['【中文 `)]}` 内容】'])
        self.assert_spans('请看\n````python\n```\n"中文\n````\n结束',
                          ['````python\n```\n"中文\n````'])
        self.assert_spans('请看\n```python\n中文', ['```python\n中文'])
        self.assert_spans('请看 `未闭合', [])

    def test_roundtrip_repeated_passages_and_no_recursive_substitution(self):
        text = '请点击“确认” 和 “确认” `__KEEP_old_0__`'
        masked, replacements, prefix = protect(text)
        self.assertEqual(len(replacements), 3)
        self.assertNotIn('确认', masked)
        self.assertEqual(restore(masked, replacements, prefix), text)

    def test_supplementary_han_characters(self):
        self.assert_spans('点击【𠀀】', ['【𠀀】'])


if __name__ == "__main__":
    unittest.main()
