import curses
import json
import queue
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import tui
from service import feature_status, apply_input_translation


class Screen:
    def __init__(self):
        self.lines = []

    def getmaxyx(self):
        return 24, 80

    def erase(self):
        self.lines = []

    def addstr(self, y, x, text, attr):
        self.lines.append(text)

    def refresh(self):
        pass


class TUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in [('ROOT', self.root), ('CONFIG', self.root / 'config.json')]:
            patcher = patch.object(tui, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def terminal(self):
        worker = SimpleNamespace(results=queue.SimpleQueue(), commands=queue.Queue())
        terminal = tui.Terminal(Screen(), worker)
        terminal.config = {'enabled': True, 'han_ratio_threshold_enabled': True,
                           'han_ratio_threshold': .2, 'hook_timeout_seconds': 30,
                           'api_key': 'private-test-value', 'api_provider': 'deepseek'}
        terminal.valid_config = True
        return terminal

    def test_atomic_merge_and_private_permissions(self):
        tui.CONFIG.write_text(json.dumps({'api_key': 'private', 'custom': {'a': 1}}))
        tui.save_field('han_ratio_threshold_enabled', False)
        saved = json.loads(tui.CONFIG.read_text())
        self.assertFalse(saved['han_ratio_threshold_enabled'])
        self.assertEqual(saved['api_key'], 'private')
        self.assertEqual(saved['custom'], {'a': 1})
        self.assertEqual(tui.CONFIG.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.root.glob('.config-*')), [])

    def test_external_changes_preserved_and_corrupt_config_not_overwritten(self):
        tui.save_field('enabled', False)
        saved = json.loads(tui.CONFIG.read_text())
        saved['external'] = 'new'
        tui.CONFIG.write_text(json.dumps(saved))
        tui.save_field('display_mode', 'chinese')
        self.assertEqual(json.loads(tui.CONFIG.read_text())['external'], 'new')
        tui.CONFIG.write_text('{broken')
        with self.assertRaises(ValueError):
            tui.save_field('enabled', True)
        self.assertEqual(tui.CONFIG.read_text(), '{broken')

    def test_provider_format_transitions(self):
        tui.save_field('api_provider', 'anthropic')
        self.assertEqual(json.loads(tui.CONFIG.read_text())['api_format'], 'messages')
        tui.save_field('api_provider', 'openai_compatible')
        self.assertEqual(json.loads(tui.CONFIG.read_text())['api_format'], 'chat_completions')
        tui.save_field('api_format', 'responses')
        tui.save_field('api_provider', 'deepseek')
        self.assertEqual(json.loads(tui.CONFIG.read_text())['api_format'], 'chat_completions')

    def test_validation_and_percentage_conversion(self):
        self.assertEqual(tui.parse_value('ratio', '35', {}), .35)
        self.assertEqual(tui.parse_value('region', 'sg', {}), 'SG')
        for kind, value in [('ratio', '-1'), ('ratio', '101'), ('ratio', 'nan'),
                            ('timeout', '30'), ('timeout', '0'), ('region', '中国'),
                            ('url', 'file:///tmp'), ('url', 'https://key:secret@example.com')]:
            with self.subTest(kind=kind, value=value), self.assertRaises(ValueError):
                tui.parse_value(kind, value, {'hook_timeout_seconds': 30})

    def test_terminal_toggle_and_edit_cancel(self):
        terminal = self.terminal()
        with patch.object(tui, 'configuration', return_value=terminal.config):
            terminal.index = 3
            terminal.key(' ')
            self.assertFalse(json.loads(tui.CONFIG.read_text())['han_ratio_threshold_enabled'])
            terminal.index = 4
            terminal.key('\n')
            terminal.key('5')
            terminal.key('0')
            terminal.key('\x1b')
            self.assertNotIn('han_ratio_threshold', json.loads(tui.CONFIG.read_text()))
            terminal.key('\n')
            terminal.key('3')
            terminal.key('5')
            terminal.key('\n')
            self.assertEqual(json.loads(tui.CONFIG.read_text())['han_ratio_threshold'], .35)

    def test_secret_masking_in_view_and_editor(self):
        terminal = self.terminal()
        terminal.page, terminal.index = 1, 4
        terminal.render()
        self.assertNotIn('private-test-value', ''.join(terminal.screen.lines))
        terminal.key('\n')
        for c in 'replacement-key':
            terminal.key(c)
        terminal.render()
        self.assertNotIn('replacement-key', ''.join(terminal.screen.lines))
        self.assertIn('********', ''.join(terminal.screen.lines))

    def test_worker_actions_queued_and_quit_does_not_stop_service(self):
        terminal = self.terminal()
        terminal.status = {'running': True}
        terminal.key('s')
        self.assertEqual(terminal.worker.commands.get_nowait(), 'stop')
        self.assertFalse(terminal.key('q'))
        self.assertTrue(terminal.worker.commands.empty())

    def test_log_filtering_and_expiration(self):
        directory = self.root / 'logs'
        directory.mkdir()
        for name, started in [('old', 700), ('new', 701)]:
            (directory / (name + '.json')).write_text(json.dumps(
                {'request_id': name, 'started_at': started, 'kind': 'input'}))
        (directory / 'broken.json').write_text('{')
        with patch.object(tui.translation_log, 'LOG_DIR', directory):
            self.assertEqual([r['request_id'] for r in tui.read_logs(now=1000)], ['new'])

    def test_expired_open_detail_closes(self):
        terminal = self.terminal()
        terminal.detail = {'request_id': 'expired'}
        with patch.object(tui, 'configuration', return_value=terminal.config), \
                patch.object(tui, 'read_logs', return_value=[]):
            terminal.refresh()
        self.assertIsNone(terminal.detail)
        self.assertIn('过期', terminal.message)

    def test_unicode_width_and_control_characters(self):
        self.assertEqual(tui.clip('中文abc', 5), '中文a')
        self.assertEqual(tui.wrap('中文abc', 4), ['中文', 'abc'])
        self.assertNotIn('\x1b', tui.clean('\x1b[31m'))

    def test_service_status_respects_guard_switch(self):
        self.assertIn('中文提交检查 已关闭', feature_status({'han_ratio_threshold_enabled': False}))
        self.assertIn('中文提交检查 已开启', feature_status({}))


class LiveInputSwitchTests(unittest.TestCase):
    def test_turning_off_stops_helper_without_launching(self):
        process = object()
        with patch('service.hotkey.stop') as stop, patch('service.hotkey.launch') as launch:
            result, label = apply_input_translation(process, False)
        stop.assert_called_once_with(process)
        launch.assert_not_called()
        self.assertIsNone(result)
        self.assertIn('已关闭', label)

    def test_turning_on_launches_helper_and_reports_unavailable(self):
        with patch('service.hotkey.stop'), patch('service.hotkey.launch', return_value='helper'):
            self.assertEqual(apply_input_translation(None, True)[0], 'helper')
        with patch('service.hotkey.stop'), patch('service.hotkey.launch', side_effect=RuntimeError('macOS required')):
            process, label = apply_input_translation(None, True)
            self.assertIsNone(process)
            self.assertIn('macOS required', label)
