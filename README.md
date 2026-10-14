# Claude Code Translation Helper

Translate Claude Code's English replies into Simplified Chinese through a `MessageDisplay` Hook. **Only the on-screen text is replaced**; conversation transcripts and model context retain the original replies. On macOS, the global **Option+A (⌥A)** shortcut also translates input into English.

Uses the Python standard library with no third-party dependencies. DeepSeek is the default provider; services compatible with Chat Completions or Responses are also supported.

## Requirements

- Python 3.9+.
- A Claude Code version that supports `MessageDisplay` (locally checked version: 2.1.296).
- An API key for your translation provider.
- The input shortcut requires macOS, Xcode Command Line Tools (`swiftc`), and Accessibility permission.

## Quick Start

Run from the project directory:

```bash
python3 service.py
```

On the first run, the service creates `config.json` with permissions `600` and exits. Fill in `api_key`, confirm `base_url` and `model`, then run it again.

The service stays in the current terminal, registers the Hook automatically, and refreshes the balance on the same status line. By default, it updates `~/.claude/settings.json`, applying to all Claude projects. To use it for a single project, set `settings_file` to the absolute path of that project's `.claude/settings.local.json`.

Run `claude` in your target project and use `/hooks` to confirm that `MessageDisplay` is registered. Try this prompt:

```text
Explain Python virtual environments. Answer in English.
```

If an existing Claude session does not recognize the new Hook, restart that session. The helper does not force Claude to reply in English; specify this in your prompt or `CLAUDE.md` if you want English transcripts.

**Press Ctrl+C to stop the service and remove its Hook.** Other settings and Hooks are preserved. Normal exit and SIGTERM, SIGINT, or SIGHUP also trigger cleanup. A forced termination or power loss may leave the Hook registered; restart the service or run:

```bash
python3 service.py stop
```

The legacy `start`, `status`, and `stop` commands remain available for compatibility. Running the service directly in the foreground is recommended.

## Configuration

Defaults are read from `config.example.json` and overridden by `config.json`. Environment variables do not override file configuration. `config.json` is included in `.gitignore`.

| Setting | Default | Description |
|---|---|---|
| `api_key` | Empty | Translation provider's API key |
| `base_url` | `https://api.deepseek.com` | API base URL, including any required prefix such as `/v1` |
| `api_format` | `chat_completions` | `chat_completions` or `responses` |
| `model` | `deepseek-flash` | A model supported by your provider |
| `thinking_type` | `disabled` | DeepSeek thinking mode; set to `null` to omit this parameter for other providers |
| `timeout_seconds` | `10` | Network timeout; must be positive and below the Hook timeout |
| `hook_timeout_seconds` | `30` | Claude Hook timeout |
| `max_output_tokens` | `393216` | Translation output token limit; incomplete output falls back to the original |
| `reply_translation_prompt` | Built-in translation instructions | System prompt for translating replies into Simplified Chinese |
| `input_translation_prompt` | Built-in translation instructions | System prompt for translating input into English |
| `enabled` | `true` | Enable reply translation |
| `display_mode` | `chinese` | `chinese` for translation only; `bilingual` for the Chinese translation followed by the English original in a blockquote |
| `settings_file` | `~/.claude/settings.json` | Settings file used to register the Hook |
| `show_balance` | `true` | Query and display the balance |
| `balance_path` | `/user/balance` | Balance endpoint path |
| `balance_timeout_seconds` | `3` | Balance query timeout |
| `balance_refresh_seconds` | `30` | Balance refresh interval, at least 0.2 seconds |
| `input_translation_enabled` | `true` | Enable Option+A input translation |

The script appends `/chat/completions` or `/responses` automatically. For OpenAI, use `https://api.openai.com/v1`, `responses`, a model available to your account, and the corresponding API key; set `thinking_type` to `null`. Responses requests use `store: false`. Each translation is an independent request.

Both translation prompts are read from configuration on each translation. Edit `reply_translation_prompt` and `input_translation_prompt` in `config.json`; no service restart is needed. Existing configuration files that omit these fields use the defaults from `config.example.json`. Prompts must be non-empty strings; invalid values cause reply translation to show the original and input translation to attempt original-text recovery. In JSON strings, use `\\n` for line breaks.

Changes to API settings, the model, network timeout, and `enabled` take effect on the next Hook call. Restart the service after changing `settings_file`, `hook_timeout_seconds`, or `input_translation_enabled`. The balance display shows the total available balance; query failures do not affect translation. The startup status does not confirm connectivity to the translation API.

## Option+A Input Translation

Place the cursor in an input field and press **⌥A**. The helper translates the selection, or attempts to select all text in the current field if nothing is selected. It inserts the translation in place **without submitting it**. On failure, it attempts to restore the original text.

On first launch, the service compiles the Swift helper and requests macOS Accessibility permission. Follow the prompts to allow the terminal running the service and the native helper. Grant Input Monitoring permission if requested, then restart the service. Reply translation remains available if shortcut permissions are missing.

- The prompt asks the model to preserve Chinese inside paired quotes, dashes, brackets, and similar delimiters. For example, `请点击“确认”` becomes `Click “确认”`. No placeholders or text splitting are used; preservation depends on the model.
- Switching apps or windows, clicking, scrolling, or typing during translation cancels automatic insertion. Recover the original text from the clipboard or undo the cut in the original field.
- The original clipboard is restored after normal completion. New content copied by the user during translation is preserved. Password fields and system secure input are not processed.
- Select-all and copy behavior varies by application and needs manual verification. Errors are written to `.runtime/hotkey.log`; input text and API keys are not logged.

## Display Behavior and Limitations

- Set `display_mode` to `bilingual` to show the Chinese translation first, followed by the English original in a Markdown blockquote. Each original line, including blank lines, is quoted to keep lists and code blocks inside the quote. Missing or unrecognized values use `chinese` mode. Translation failures display only the original text in either mode.
- In interactive mode, each `delta` batch is translated separately, adding network latency. In non-interactive mode, complete text is typically processed after an assistant message finishes.
- Only assistant reply text is translated. Blank content and text without English letters skip the API request. Tool results are not translated; user input is handled separately by Option+A.
- API errors, timeouts, missing keys, refusals, empty translations, and incomplete responses fall back to the original text without automatic retries.
- The prompt asks the model to preserve Markdown, code, paths, URLs, and identifiers, but exact preservation and consistency across batches are not guaranteed.
- Text to be translated is sent to the configured API provider. The script does not read or write `transcript_path`. Verbose mode displays the original text; Chinese display during history replay is not guaranteed.

## Manual Installation and Removal

You can manage the Hook manually without running the service. Do not mix manual and service management in the same settings file. Reinstall after changing the Hook timeout in manual mode.

```bash
python3 install.py --settings /absolute/path/to/project/.claude/settings.local.json
python3 install.py --settings /absolute/path/to/project/.claude/settings.local.json --remove
```

Installation and removal back up existing settings and modify only this helper's Hook. You may delete the project directory after stopping the service and confirming that the Hook has been removed.

## Tests

Tests use a local mock API, require no key, and incur no real API usage:

```bash
python3 -m unittest discover -s tests -v
```

Coverage includes translation requests, transcript preservation, error fallback, configuration, balance queries, installation and removal, and service shutdown cleanup. The macOS shortcut requires verification in actual applications.

## References

- [Claude MessageDisplay](https://code.claude.com/docs/en/hooks#messagedisplay)
- [DeepSeek API](https://api-docs.deepseek.com/)
- [OpenAI Text Generation](https://developers.openai.com/api/docs/guides/text)
