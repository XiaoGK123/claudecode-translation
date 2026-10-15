# Claude Code Translation Helper

Translate Claude Code's English replies into Simplified Chinese through a `MessageDisplay` Hook. **Only the on-screen text is replaced**; conversation transcripts and model context retain the original replies. On macOS, the global **Option+A (⌥A)** shortcut also translates input into English.

DeepSeek is the default provider and uses the Python standard library. OpenAI compatible mode uses the official OpenAI Python SDK for Chat Completions and Responses.

## Requirements

- Python 3.9+.
- A Claude Code version that supports `MessageDisplay` (locally checked version: 2.1.296).
- An API key for your translation provider.
- The input shortcut requires macOS, Xcode Command Line Tools (`swiftc`), and Accessibility permission.

## Quick Start

Run from the project directory:

```bash
python3 -m pip install -r requirements.txt
python3 service.py
```

Install dependencies using the same Python interpreter that runs `service.py` and the Hook. The SDK is loaded only in `openai_compatible` mode; DeepSeek does not require it.

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
| `api_provider` | `deepseek` | `deepseek` or `openai_compatible`; selects the API adapter |
| `api_key` | Empty | Translation provider's API key |
| `base_url` | `https://api.deepseek.com` | API base URL, including any required prefix such as `/v1` |
| `api_format` | `chat_completions` | DeepSeek: `chat_completions` only; OpenAI compatible: `chat_completions` or `responses` |
| `model` | `deepseek-flash` | A model supported by your provider |
| `thinking_type` | `disabled` | DeepSeek only: `enabled`, `disabled`, or `null` to omit; ignored by OpenAI compatible |
| `extra_body` | `{"enable_thinking": false}` | OpenAI compatible only: JSON object passed to the SDK's `extra_body` for both API formats; use `{}` to send no extension fields |
| `timeout_seconds` | `10` | Network timeout; must be positive and below the Hook timeout |
| `hook_timeout_seconds` | `30` | Claude Hook timeout |
| `max_output_tokens` | `393216` | Translation output token limit; incomplete output falls back to the original |
| `reply_translation_prompt` | Built-in translation instructions | System prompt for translating replies into Simplified Chinese |
| `input_translation_prompt` | Built-in translation instructions | System prompt for translating input into English |
| `enabled` | `true` | Enable reply translation |
| `display_mode` | `bilingual` | `chinese` for translation only; `bilingual` for the Chinese translation followed by the English original in a blockquote |
| `settings_file` | `~/.claude/settings.json` | Settings file used to register the Hook |
| `show_balance` | `true` | Query and display the balance |
| `balance_path` | `/user/balance` | Balance endpoint path |
| `balance_timeout_seconds` | `3` | Balance query timeout |
| `balance_refresh_seconds` | `30` | Balance refresh interval, at least 0.2 seconds |
| `input_translation_enabled` | `true` | Enable Option+A input translation |

The selected adapter appends `/chat/completions` or `/responses` automatically. Responses requests use `store: false`. Each translation is an independent request.

### API providers

Both reply and input translation use the selected provider. Set `api_provider` explicitly when switching services.

- `deepseek`: Chat Completions with the DeepSeek `thinking` parameter and balance API.
- `openai_compatible`: Chat Completions or Responses through the SDK, with optional provider-specific fields from `extra_body`. The DeepSeek `thinking_type` setting is ignored. Balance queries are unsupported and skipped, even when `show_balance` is true. Model and token limits must match the target service.

DeepSeek configuration (merge these fields into `config.json`):

```json
{
  "api_provider": "deepseek",
  "base_url": "https://api.deepseek.com",
  "api_format": "chat_completions",
  "model": "deepseek-flash",
  "thinking_type": "disabled"
}
```

OpenAI-compatible service configuration:

```json
{
  "api_provider": "openai_compatible",
  "base_url": "https://your-provider.example/v1",
  "api_format": "chat_completions",
  "model": "your-model",
  "max_output_tokens": 4096,
  "extra_body": {"enable_thinking": false},
  "show_balance": false
}
```

For an OpenAI Responses service, use the corresponding base URL and change `api_format` to `responses`. Supply that service's API key.

`extra_body` is merged into the top level of the request JSON by the SDK; it is not sent as a nested `extra_body` field. Its default `enable_thinking: false` is a provider extension, so use `"extra_body": {}` for services that do not accept it (including the official OpenAI API). Existing config files that omit the setting inherit the default. Custom objects replace the entire default object. Non-object values cause translation to fail and follow the existing original-text recovery behavior. DeepSeek ignores `extra_body` and continues to use `thinking_type`.

Old `config.json` files without `api_provider` are migrated in memory: Chat Completions at hostname `api.deepseek.com` selects DeepSeek; other URLs or Responses select OpenAI compatible. For DeepSeek proxies, explicitly set `api_provider: "deepseek"` to retain its thinking and balance behavior. Config files are not rewritten. Unknown providers or unsupported formats follow the existing translation failure recovery behavior.

### Adding a provider

Create an adapter under `providers/` implementing `APIProvider` from `providers/base.py`. Implement `build_request(text, config, instructions)` to return an endpoint suffix and JSON body, and `parse_response(data, config)` to return translated text or reject incomplete results. Optionally override `balance_label(config)`; the default skips balance queries.

Import and register the adapter instance in `PROVIDERS` in `providers/__init__.py`, then select its name with `api_provider`. The default adapter `request` method handles Bearer authentication and JSON POST transport using `urllib`; adapters can override it for another transport. `openai_compatible` uses `OpenAI.chat.completions.create` or `OpenAI.responses.create`, with explicit configuration values for the key, base URL, and timeout. SDK retries are disabled (`max_retries=0`). Clients are closed after each request. The shared translation caller validates timeouts, rejects empty output, and preserves boundary whitespace. Add adapter tests for request format and response validation.

Both translation prompts are read from configuration on each translation. Edit `reply_translation_prompt` and `input_translation_prompt` in `config.json`; no service restart is needed. Existing configuration files that omit these fields use the defaults from `config.example.json`. Prompts must be non-empty strings; invalid values cause reply translation to show the original and input translation to attempt original-text recovery. In JSON strings, use `\\n` for line breaks.

Changes to API settings, the model, network timeout, and `enabled` take effect on the next Hook call. Restart the service after changing `settings_file`, `hook_timeout_seconds`, or `input_translation_enabled`. The balance display shows the total available balance; query failures do not affect translation. The startup status does not confirm connectivity to the translation API.

## Option+A Input Translation

Place the cursor in an input field and press **⌥A**. The helper translates the selection, or attempts to select all text in the current field if nothing is selected. It inserts the translation in place **without submitting it**. On failure, it attempts to restore the original text.

Input translation protects Chinese inside `“…”`, `‘…’`, `「…」`, `『…』`, `（…）`, `【…】`, `〔…〕`, `《…》`, `〈…〉`, `(...)`, `[...]`, `{...}`, and `"..."` locally before calling the API. The entire passage, including delimiters, is replaced with a unique placeholder and restored verbatim after translation. Nested and multiline passages are supported; the outermost matching passage is protected. Ordinary unclosed or mismatched delimiters do not protect an outer passage, but valid inner passages can still be protected. Backslash-escaped delimiters are treated as literal text. English single quotes and paired dashes are not protected.

Backtick inline code (including multiple-backtick delimiters) and backtick fenced code blocks are always protected, even without Chinese. An unclosed fenced block is protected through the end of the input; an unclosed inline backtick is treated as ordinary text. If all Chinese is already protected, the original input is returned without an API call. Otherwise, the configured input prompt is supplemented with instructions to preserve placeholders. Missing, modified, duplicated, or invented placeholders fail translation with `PlaceholderError`, allowing the shortcut helper to attempt original-text recovery. Protected contents are never sent to the translation API.

On first launch, the service compiles the Swift helper and requests macOS Accessibility permission. Follow the prompts to allow the terminal running the service and the native helper. Grant Input Monitoring permission if requested, then restart the service. Reply translation remains available if shortcut permissions are missing.

- For example, `请点击“确认”` can become `Click “确认”`: the local helper masks `“确认”` before the API call and restores it verbatim afterward. Preservation of protected passages is enforced by placeholder validation; English single quotes and paired dashes do not trigger protection.
- Switching apps or windows, clicking, scrolling, or typing during translation cancels automatic insertion. Recover the original text from the clipboard or undo the cut in the original field.
- The original clipboard is restored after normal completion. New content copied by the user during translation is preserved. Password fields and system secure input are not processed.
- Select-all and copy behavior varies by application and needs manual verification. Errors are written to `.runtime/hotkey.log`; input text and API keys are not logged.

## Display Behavior and Limitations

- The default `display_mode` is `bilingual`: the Chinese translation appears first, followed by the English original in a Markdown blockquote. Each original line, including blank lines, is quoted to keep lists and code blocks inside the quote. Missing values use `bilingual` mode. Set `display_mode` to `chinese` for translation only; unrecognized values also use `chinese` mode. Translation failures display only the original text in either mode.
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
