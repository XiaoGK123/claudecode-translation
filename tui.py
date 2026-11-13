#!/usr/bin/env python3
"""Plain terminal settings and translation log viewer; no third-party UI dependency."""
import curses
import fcntl
import json
import locale
import math
import os
import queue
import random
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from pathlib import Path

from translate_hook import ROOT, configuration
import translation_log

CONFIG = ROOT / 'config.json'
COMMON = [
    ('enabled', '回复翻译', 'bool'),
    ('display_mode', '显示模式', ('bilingual', 'chinese')),
    ('input_translation_enabled', '输入翻译 Option+A', 'bool'),
    ('han_ratio_threshold_enabled', '中文提交检查', 'bool'),
    ('han_ratio_threshold', '汉字比例阈值 (%)', 'ratio'),
    ('loc_monitor_enabled', '出口地区监测', 'bool'),
    ('expected_loc', '预期地区', 'region'),
]
API = [
    ('api_provider', '提供方', ('deepseek', 'openai_compatible', 'anthropic')),
    ('api_format', '接口格式', ('chat_completions', 'responses', 'messages')),
    ('base_url', 'API 地址', 'url'),
    ('model', '模型', 'text'),
    ('api_key', 'API Key', 'secret'),
    ('timeout_seconds', '请求超时 (秒)', 'timeout'),
]
LABELS = {'bilingual': '双语', 'chinese': '仅中文'}


def parse_value(kind, value, config):
    if kind in ('ratio', 'timeout'):
        number = float(value)
        maximum = 100 if kind == 'ratio' else float(config['hook_timeout_seconds'])
        if not math.isfinite(number) or number < 0 or number > maximum:
            raise ValueError('数值超出范围')
        if kind == 'timeout' and not 0 < number < maximum:
            raise ValueError('请求超时必须大于 0 且小于 Hook 超时')
        return number / 100 if kind == 'ratio' else number
    if kind == 'region':
        if len(value) != 2 or not value.isascii() or not value.isalpha():
            raise ValueError('地区代码应为两位英文字母')
        return value.upper()
    if kind == 'url':
        from urllib.parse import urlsplit
        parsed = urlsplit(value.strip())
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('请输入无用户名和密码的 HTTP(S) 地址')
    if kind != 'secret' and not value.strip():
        raise ValueError('此项不能为空')
    return value.strip()


def save_field(key, value):
    """Merge one field into the latest overrides; preserve unknown settings."""
    runtime = ROOT / '.runtime'
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (runtime / 'config.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        overrides = json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {}
        if not isinstance(overrides, dict):
            raise ValueError('配置必须为 JSON 对象')
        overrides[key] = value
        if key == 'api_provider':
            # Select a valid wire format, without guessing credentials or endpoints.
            if value == 'anthropic':
                overrides['api_format'] = 'messages'
            elif value == 'deepseek' or overrides.get('api_format') == 'messages':
                overrides['api_format'] = 'chat_completions'
        fd, temporary = tempfile.mkstemp(prefix='.config-', dir=ROOT)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(overrides, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            os.replace(temporary, CONFIG)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def read_logs(now=None):
    """Hide expired records even between the service's minute cleanup passes."""
    now = time.time() if now is None else now
    records = []
    try:
        paths = list(translation_log.LOG_DIR.glob('*.json'))
    except OSError:
        return records
    for path in paths:
        if path.is_symlink():
            continue
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if 0 <= now - record['started_at'] < translation_log.RETENTION_SECONDS:
                if isinstance(record.get('request_id'), str):
                    records.append(record)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(records, key=lambda item: item['started_at'], reverse=True)


def clean(text):
    return ''.join(' ' if unicodedata.category(c).startswith('C') else c for c in str(text))


def cell_width(text):
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text)


def clip(text, width):
    result = ''
    for char in clean(text):
        if cell_width(result + char) > width:
            break
        result += char
    return result


def wrap(text, width):
    lines = []
    for line in str(text).splitlines() or ['']:
        current = ''
        for char in clean(line):
            if cell_width(current + char) > width:
                lines.append(current)
                current = ''
            current += char
        lines.append(current)
    return lines


class Starfield:
    """Animated ASCII night sky drawn behind the panel; pure function of time."""
    # Far stars barely move; near stars drift left for a little parallax.
    LAYERS = ((0.0, '..', 'dim'), (0.25, '.+', 'blue'), (0.6, '+*', 'bright'))
    DENSITY = 1 / 30
    METEOR_EVERY = (5.0, 11.0)
    METEOR_SPEED = 28.0

    def __init__(self, seed=None):
        self.random = random.Random(seed)
        self.size = None
        self.stars = []
        self.meteor = None
        self.next_meteor = None

    def resize(self, height, width):
        if self.size == (height, width):
            return
        self.size = (height, width)
        count = int(height * width * self.DENSITY)
        self.stars = []
        for _ in range(count):
            layer = self.random.choices((0, 1, 2), weights=(6, 3, 1))[0]
            self.stars.append((self.random.randrange(height), self.random.uniform(0, width),
                               layer, self.random.uniform(0, math.tau),
                               self.random.uniform(1.5, 5.0),
                               'warm' if layer and self.random.random() < .15 else None))

    def cells(self, now, height, width):
        """Yield (y, x, glyph, tone) for every visible cell at time `now`."""
        self.resize(height, width)
        for y, x, layer, phase, period, tone in self.stars:
            speed, glyphs, layer_tone = self.LAYERS[layer]
            light = (math.sin(now * math.tau / period + phase) + 1) / 2
            if layer == 0 and light < .3:
                continue  # Faint stars fade out completely between twinkles.
            glyph = glyphs[1] if light > .6 else glyphs[0]
            yield y, int(x - speed * now) % width, glyph, tone or layer_tone
        yield from self._meteor(now, height, width)

    def _meteor(self, now, height, width):
        if self.next_meteor is None:
            self.next_meteor = now + self.random.uniform(*self.METEOR_EVERY) / 3
        if self.meteor is None and now >= self.next_meteor:
            self.meteor = (now, self.random.uniform(width * .2, width),
                           self.random.uniform(0, height * .3),
                           self.random.uniform(.6, 1.1))
            self.next_meteor = now + self.random.uniform(*self.METEOR_EVERY)
        if self.meteor is None:
            return
        start, x0, y0, life = self.meteor
        age = now - start
        if age > life:
            self.meteor = None
            return
        # Travel down-left at a 2:1 slope so it reads as a diagonal in terminal cells.
        for i, glyph in enumerate('*=-.'):
            distance = max(0.0, age * self.METEOR_SPEED - i * 1.5)
            y, x = int(y0 + distance / 2), int(x0 - distance)
            if 0 <= y < height and 0 <= x < width:
                yield y, x, glyph, 'meteor' if i < 2 else 'blue'


class ServiceWorker:
    """Run the service for the lifetime of the terminal, including cleanup."""
    def __init__(self):
        self.results = queue.SimpleQueue()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.cleanup_ok = True

    def run(self):
        import service
        process = None
        attached = False
        try:
            attached = bool(service.active())
            if not attached and not self.stopped.is_set():
                if not CONFIG.exists():
                    save_field('han_ratio_threshold_enabled', True)
                runtime = ROOT / '.runtime'
                runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
                with (runtime / 'service.log').open('ab') as log:
                    process = subprocess.Popen(
                        [sys.executable, str(ROOT / 'service.py'), '_run'],
                        stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        start_new_session=True, close_fds=True)
            while not self.stopped.is_set():
                status = service.active()
                self.results.put(('status', status))
                if process is not None and process.poll() is not None:
                    self.results.put(('message', '服务启动失败，请检查配置及 .runtime/service.log'))
                    break
                if status:
                    self.results.put(('busy', False))
                if self.stopped.wait(1):
                    break
        except Exception as error:
            self.results.put(('message', '服务启动失败：' + type(error).__name__))
        finally:
            self.results.put(('busy', False))
            # Keep the worker alive until the UI exits, even after startup failure.
            self.stopped.wait()
            try:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                if process is not None or attached:
                    result = subprocess.run(
                        [sys.executable, str(ROOT / 'service.py'), 'stop'],
                        capture_output=True, text=True, timeout=10)
                    self.cleanup_ok = result.returncode == 0
            except Exception:
                self.cleanup_ok = False

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=35)
        return not self.thread.is_alive() and self.cleanup_ok


class Terminal:
    def __init__(self, screen, worker):
        self.screen, self.worker = screen, worker
        self.page, self.index, self.scroll = 0, 0, 0
        self.config, self.status, self.records = {}, None, []
        self.message = '修改后自动保存；退出时停止服务并清理 Hook'
        self.editing = None
        self.detail = None
        self.busy = True
        self.last_refresh = 0
        self.valid_config = False
        self.sky = Starfield()
        self.palette = {}

    def colors(self):
        """Map star tones to curses attributes; falls back to plain dim/bold."""
        base = {'dim': curses.A_DIM, 'blue': curses.A_NORMAL, 'bright': curses.A_BOLD,
                'warm': curses.A_BOLD, 'meteor': curses.A_BOLD, 'frame': curses.A_DIM}
        try:
            if not curses.has_colors():
                return base
            curses.start_color()
            rich = curses.COLORS >= 256
            # Always paint on true black, whatever the terminal theme's background is.
            # Colour 16 is #000000 in the 256-colour cube; slot 0 may be themed grey.
            background = 16 if rich else curses.COLOR_BLACK
            spec = {'text': (252 if rich else curses.COLOR_WHITE, curses.A_NORMAL),
                    'dim': (240 if rich else curses.COLOR_WHITE, curses.A_DIM),
                    'blue': (111 if rich else curses.COLOR_BLUE, curses.A_NORMAL),
                    'bright': (231 if rich else curses.COLOR_WHITE, curses.A_BOLD),
                    'warm': (222 if rich else curses.COLOR_YELLOW, curses.A_NORMAL),
                    'meteor': (159 if rich else curses.COLOR_CYAN, curses.A_BOLD),
                    'frame': (61 if rich else curses.COLOR_BLUE, curses.A_NORMAL)}
            for number, (tone, (color, attr)) in enumerate(spec.items(), 1):
                curses.init_pair(number, color, background)
                base[tone] = curses.color_pair(number) | attr
            # Every cell, including panel text and blanks, inherits the black background.
            self.screen.bkgd(' ', base['text'])
        except curses.error:
            pass
        return base

    def draw_sky(self, height, width, now=None):
        """Paint stars outside the panel, then a thin frame around it."""
        palette = self.palette  # Filled by run() once curses is initialised.
        top, bottom = self.top - 1, self.top + self.block_height - 1
        left, right = self.left - 2, self.left + self.content_width + 1
        now = time.monotonic() if now is None else now
        for y, x, glyph, tone in self.sky.cells(now, height, width):
            if y >= height - 1 or x >= width - 1 or (top <= y <= bottom and left <= x <= right):
                continue
            try:
                self.screen.addstr(y, x, glyph, palette.get(tone, curses.A_NORMAL))
            except curses.error:
                pass
        if top < 0 or left < 0 or bottom >= height - 1 or right >= width - 1:
            return
        frame = palette.get('frame', curses.A_DIM)
        acs = lambda name, fallback: getattr(curses, name, ord(fallback))
        try:
            for x in range(left + 1, right):
                self.screen.addch(top, x, acs('ACS_HLINE', '-'), frame)
                self.screen.addch(bottom, x, acs('ACS_HLINE', '-'), frame)
            for y in range(top + 1, bottom):
                self.screen.addch(y, left, acs('ACS_VLINE', '|'), frame)
                self.screen.addch(y, right, acs('ACS_VLINE', '|'), frame)
            for y, x, name in ((top, left, 'ACS_ULCORNER'), (top, right, 'ACS_URCORNER'),
                               (bottom, left, 'ACS_LLCORNER'), (bottom, right, 'ACS_LRCORNER')):
                self.screen.addch(y, x, acs(name, '+'), frame)
        except curses.error:
            pass

    def put(self, y, text, selected=False):
        height, width = self.screen.getmaxyx()
        x = getattr(self, 'left', 0)
        y += getattr(self, 'top', 0)
        content_width = getattr(self, 'content_width', width - 1)
        if 0 <= y < height - 1:
            try:
                shown = clip(text, max(0, content_width))
                if selected:
                    shown += ' ' * max(0, content_width - cell_width(shown))
                self.screen.addstr(y, x, shown,
                                   curses.A_REVERSE if selected else curses.A_NORMAL)
            except curses.error:
                pass

    def refresh(self):
        if time.monotonic() - self.last_refresh >= 1:
            self.last_refresh = time.monotonic()
            try:
                self.config = configuration()
                self.valid_config = True
            except Exception:
                self.valid_config = False
                self.message = '配置读取失败；请修复 config.json 后继续'
            self.records = read_logs()
            if self.detail:
                self.detail = next((r for r in self.records if r['request_id'] == self.detail['request_id']), None)
                if self.detail is None:
                    self.message = '该日志已过期'
        while True:
            try:
                name, value = self.worker.results.get_nowait()
            except queue.Empty:
                break
            setattr(self, name, value)

    def fields(self):
        return COMMON if self.page == 0 else API

    def value(self, key, kind):
        value = self.config.get(key, True if kind == 'bool' else '')
        if kind == 'bool':
            return '开启' if value else '关闭'
        if kind == 'secret':
            return '********' if value else '未设置'
        if kind == 'ratio':
            return f'{value * 100:g}'
        return LABELS.get(value, str(value)) if isinstance(value, str) else str(value)

    def render(self):
        self.screen.erase()
        height, terminal_width = self.screen.getmaxyx()
        self.content_width = min(68, max(1, terminal_width - 4))
        self.left = max(0, (terminal_width - self.content_width) // 2)
        block_height = min(height - 2, 25)
        self.top = max(0, (height - block_height) // 2)
        self.block_height = block_height
        width = self.content_width
        if height < 12 or terminal_width < 40:
            self.put(0, '请将终端调整到至少 40 列 × 12 行')
            self.put(1, 'q 退出')
            self.screen.refresh()
            return
        self.draw_sky(height, terminal_width)
        status = '运行中' if self.status else ('正在启动' if self.busy else '未运行')
        self.put(0, '翻译助手 / ' + status)
        balance = self.status.get('balance') if self.status else None
        shortcut = '已启用' if self.status and self.status.get('hotkey_running') else '未运行'
        self.put(1, f"{self.config.get('model', '')} · 余额 {balance or '—'} · ⌥A {shortcut}")
        self.put(3, '[1 常用设置]  [2 API 设置]  [3 日志]')
        row_step = 2 if block_height >= 23 and self.page < 2 and not self.detail else 1
        available = max(1, (block_height - 9) // row_step)
        if self.detail:
            r = self.detail
            lines = ['原文'] + wrap(r.get('original', ''), width - 2)
            lines += ['', '译文'] + wrap(r.get('translated', '无译文'), width - 2)
            lines += ['', f"状态 {r.get('status')} · {r.get('duration_ms', '—')} ms",
                      f"错误 {r.get('error_type', '—')} · HTTP {r.get('http_status', '—')}"]
            self.scroll = min(self.scroll, max(0, len(lines) - available))
            for i, line in enumerate(lines[self.scroll:self.scroll + available]):
                self.put(5 + i, line)
        elif self.page < 2:
            fields = self.fields()
            self.index = min(self.index, len(fields) - 1)
            offset = max(0, self.index - available + 1)
            for i, (key, label, kind) in enumerate(fields[offset:offset + available]):
                selected = offset + i == self.index
                if self.editing is not None and selected:
                    shown = '*' * len(self.editing) if kind == 'secret' else self.editing
                    room = max(1, width - cell_width(label) - 8)
                    while shown and cell_width(shown) > room:
                        shown = shown[1:]
                    line = label + ': ' + shown + ' ▏'
                else:
                    line = label + ' ' * max(2, min(26, width // 2) - cell_width(label)) + self.value(key, kind)
                self.put(5 + i * row_step, ('> ' if selected else '  ') + line, selected)
        else:
            self.put(4, '日志保留 5 分钟，每分钟清理')
            self.index = min(self.index, max(0, len(self.records) - 1))
            offset = max(0, self.index - available + 1)
            if not self.records:
                self.put(5, '暂无未过期的翻译日志')
            for i, r in enumerate(self.records[offset:offset + available]):
                stamp = time.strftime('%H:%M:%S', time.localtime(r['started_at']))
                kind = '回复' if r.get('kind') == 'reply' else '输入'
                state = {'started': '处理中', 'success': '成功', 'error': '失败'}.get(r.get('status'), '未知')
                self.put(5 + i, f"{stamp}  {kind}  {state}  {r.get('duration_ms', '—')} ms", offset + i == self.index)
        self.put(block_height - 3, self.message)
        if self.editing is not None:
            hint = 'Enter 保存  Esc 取消  Backspace 删除'
        elif self.detail:
            hint = '↑↓ 滚动  Esc 返回'
        else:
            hint = 'q 退出并停止  1/2/3 换页  ↑↓ 选择  Enter 修改'
        self.put(block_height - 2, hint)
        self.screen.refresh()

    def save(self, key, value):
        try:
            save_field(key, value)
            self.config = configuration()
            self.message = '已保存；下一次请求生效，快捷键开关约 1 秒内同步'
            return True
        except Exception as error:
            self.message = '保存失败：' + type(error).__name__
            return False

    def key(self, key):
        if self.editing is not None:
            if key == '\x1b':
                self.editing = None
            elif key in ('\n', '\r', curses.KEY_ENTER):
                name, _, kind = self.fields()[self.index]
                try:
                    value = parse_value(kind, self.editing, self.config)
                    if self.save(name, value):
                        self.editing = None
                except ValueError:
                    self.message = '输入无效：检查范围、地区代码或 API 地址'
            elif key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
                self.editing = self.editing[:-1]
            elif isinstance(key, str) and key.isprintable():
                self.editing += key
            return True
        if self.detail:
            if key in ('\x1b', 'q'):
                self.detail, self.scroll = None, 0
            elif key in (curses.KEY_DOWN, curses.KEY_NPAGE):
                self.scroll += 1
            elif key in (curses.KEY_UP, curses.KEY_PPAGE):
                self.scroll = max(0, self.scroll - 1)
            return True
        if key in ('q', '\x1b'):
            return False
        if key in ('1', '2', '3'):
            self.page, self.index = int(key) - 1, 0
        elif key in (curses.KEY_DOWN, '\t'):
            count = len(self.fields()) if self.page < 2 else len(self.records)
            self.index = (self.index + 1) % max(1, count)
        elif key in (curses.KEY_UP, curses.KEY_BTAB):
            count = len(self.fields()) if self.page < 2 else len(self.records)
            self.index = (self.index - 1) % max(1, count)
        elif key in (' ', '\n', '\r', curses.KEY_ENTER):
            if self.page == 2:
                if self.records:
                    self.detail = self.records[self.index]
                    self.scroll = 0
                return True
            if not self.valid_config:
                return True
            name, _, kind = self.fields()[self.index]
            if kind == 'bool':
                self.save(name, not self.config.get(name, True))
            elif isinstance(kind, tuple):
                options = kind
                if name == 'api_format':
                    options = ('messages',) if self.config.get('api_provider') == 'anthropic' else (
                        ('chat_completions',) if self.config.get('api_provider') == 'deepseek' else
                        ('chat_completions', 'responses'))
                current = self.config.get(name)
                self.save(name, options[(options.index(current) + 1) % len(options)] if current in options else options[0])
            else:
                # Empty replacement buffer avoids exposing or accidentally appending to secrets.
                self.editing = ''
                self.message = '输入新值（替换当前值）；Esc 取消'
        return True


def run(screen, worker):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.keypad(True)
    screen.timeout(100)  # Also the starfield frame rate: about 10 frames per second.
    terminal = Terminal(screen, worker)
    terminal.palette = terminal.colors()
    while True:
        terminal.refresh()
        terminal.render()
        try:
            key = screen.get_wch()
        except curses.error:
            continue
        if not terminal.key(key):
            break


def main():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('TUI 需要交互终端。请在终端运行 python3 service.py tui。', file=sys.stderr)
        return 1
    locale.setlocale(locale.LC_ALL, '')
    worker = ServiceWorker()
    worker.thread.start()
    previous_signals = {}
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    for signum in (signal.SIGTERM, signal.SIGHUP):
        previous_signals[signum] = signal.signal(signum, interrupted)
    try:
        curses.wrapper(run, worker)
    except KeyboardInterrupt:
        pass
    finally:
        # Finish Hook cleanup even if another interrupt arrives during shutdown.
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous_signals.setdefault(signum, signal.getsignal(signum))
            signal.signal(signum, signal.SIG_IGN)
        cleaned = worker.close()
        for signum, handler in previous_signals.items():
            signal.signal(signum, handler)
    if cleaned:
        print('已退出界面，服务已停止，Hook 已清理。')
    else:
        print('已退出界面，但清理失败；请运行 python3 service.py stop。', file=sys.stderr)
    return 0 if cleaned else 1


if __name__ == '__main__':
    sys.exit(main())
