# Claude Code 显示翻译 Hook / Claude Code Display Translation Hook

把 Claude Code 的英文回复批次交给配置的翻译 API（默认 DeepSeek），返回简体中文并只替换屏幕显示。
Claude 会话记录与模型上下文保留原始回复。脚本不读取、不写入 `transcript_path`。

---

> Send batches of Claude Code's English replies to the configured translation API (DeepSeek by default), receive Simplified Chinese, and replace only the on-screen display.
> Claude's conversation history and model context retain the original reply. The scripts neither read nor write `transcript_path`.

```text
Claude 英文回复 ───────────────→ Claude 会话记录（原文）
       │
       └→ MessageDisplay.delta → 翻译 API
                                   │
                             中文翻译 → displayContent → 屏幕
```

---

```text
Claude English reply ──────────→ Claude conversation history (original)
       │
       └→ MessageDisplay.delta → Translation API
                                      │
                        Chinese translation → displayContent → Screen
```

## 环境 / Requirements

- Python 3.9 或更新版本，无第三方依赖。

  > Python 3.9 or later; no third-party Python dependencies.

- 支持 `MessageDisplay` 事件的 Claude Code。本机检测版本：2.1.296。

  > Claude Code with support for the `MessageDisplay` event. Version checked locally: 2.1.296.

- DeepSeek API Key，或其他兼容服务的 API Key；可选择 Chat Completions 或 Responses 接口。

  > A DeepSeek API key or a key for another compatible provider. Both Chat Completions and Responses APIs are supported.

- 默认模型为 DeepSeek 官方当前的 `deepseek-flash`，可以修改。

  > The default model is DeepSeek’s current official `deepseek-flash`; you can change it.

## 持续运行服务（推荐） / Persistent Service (Recommended)

所有配置均在本目录的 config.json 中。缺少文件时，运行 python3 service.py 会自动从示例生成空密钥配置，输出“无config.json文件，目前已自动生成，文件位置：…，请配置api信息后重启”后直接退出；不会安装 Hook 或启动服务。填写 api_key、base_url、model 后，再次运行，保持 enabled 为 true。
默认 settings_file 为 ~/.claude/settings.json，启动服务会注册用户级 Hook，对所有 Claude 项目生效。
如果只希望用于一个项目，将 settings_file 改为该项目 .claude/settings.local.json 的绝对路径。

---

> All settings are stored in `config.json` in this directory. If it is missing, running `python3 service.py` creates it from the example with an empty API key, prints a message saying that the file has been created and API details must be configured before restarting, then exits without installing the Hook or starting the service. Fill in `api_key`, `base_url`, and `model`, keep `enabled` set to `true`, and run the command again.
> The default `settings_file` is `~/.claude/settings.json`. Starting the service registers a user-level Hook that applies to all Claude projects.
> To limit it to one project, set `settings_file` to the absolute path of that project's `.claude/settings.local.json`.

只需一条启动命令：

---

> Start the service with:

```bash
cd /Users/xiaomingwen/my-projects/ClaudeCodeTranslation
python3 service.py
```

程序在当前终端持续运行，启动时安装 Hook，只显示一行状态，并在原位置定时更新余额，其他状态不重复输出：

---

> The service runs in the current terminal and installs the Hook at startup. It displays a single status line and periodically updates the balance in place, without repeating other status messages:

```text
服务运行中 | Hook 已安装 | 模型 deepseek-flash | 余额 110.00 CNY | 按 Ctrl+C 关闭并删除 Hook
```

> English meaning of the status line above: “Service running | Hook installed | Model deepseek-flash | Balance 110.00 CNY | Press Ctrl+C to stop and remove the Hook”. The program displays this status in Chinese.

上面余额为展示示例，实际从 DeepSeek 的 GET /user/balance 查询。启动时查询余额，之后默认每 30 秒刷新一次，只在原状态行覆盖余额，不新增日志行。显示总可用余额（含赠金和充值余额）；查询失败或缺少密钥时显示提示，服务继续运行。余额请求在后台线程执行，不阻塞退出清理。重定向到文件时只输出启动状态，不写入重复余额日志。

---

> The balance above is an example. The actual balance is queried from DeepSeek's `GET /user/balance` endpoint at startup and refreshed every 30 seconds by default. Updates overwrite the balance on the existing status line without adding log lines. The total available balance includes both promotional and topped-up funds. A failed query or missing API key displays a notice while the service keeps running. Periodic balance requests run in a background thread and do not block shutdown cleanup. When output is redirected to a file, only the initial status is written; repeated balance updates are omitted.

**关闭：在这个终端按 Ctrl+C。** 程序会先删除自己注册的 Hook，再退出，显示“服务已关闭，Hook 已删除”。其他 Claude 设置和 Hook 保留。
关闭终端时如果进程收到 SIGHUP，也会执行清理；推荐 Ctrl+C，以便确认删除成功。服务不会自动转入后台，不需要单独执行 status 或 stop。

---

> **To stop: press Ctrl+C in this terminal.** The service removes its registered Hook before exiting and displays “Service stopped, Hook removed” in Chinese. Other Claude settings and Hooks are preserved.
> Closing the terminal also triggers cleanup if the process receives SIGHUP. Ctrl+C is recommended so you can confirm removal succeeded. The service does not automatically move to the background; separate `status` or `stop` commands are unnecessary.

- 启动状态表示 Hook 已注册，不代表已验证真实 API 连通性。

  > The startup status confirms Hook registration; it does not confirm connectivity to the real API.

- enabled 改为 false 可暂停翻译；下一个 Hook 调用会读取新值。

  > Set `enabled` to `false` to pause translation. The next Hook call reads the updated value.

- 服务正常退出或收到 SIGTERM、SIGINT、SIGHUP 时会移除 Hook。

  > The Hook is removed on normal exit or on SIGTERM, SIGINT, or SIGHUP.

- SIGKILL、系统崩溃或断电无法执行退出清理，Hook 可能残留。下一次启动会清理残留；也保留 `python3 service.py stop` 用于单独清理。

  > SIGKILL, a system crash, or power loss prevents cleanup and may leave the Hook installed. The next startup removes residual registration. You can also run `python3 service.py stop` to clean it up separately.

- 修改 settings_file 或 hook_timeout_seconds 后，按 Ctrl+C，再重新运行 python3 service.py。

  > After changing `settings_file` or `hook_timeout_seconds`, press Ctrl+C and run `python3 service.py` again.

- 服务保持运行期间可以在另一个终端或 IDE 中使用 Claude。

  > You can use Claude in another terminal or IDE while the service is running.

- 重复运行会提示已有服务，不会再启动第二个实例。

  > A duplicate startup reports that the service is already running instead of starting a second instance.

- .runtime/state.json 仅记录 Hook 注册位置用于异常退出恢复，不包含密钥。

  > `.runtime/state.json` stores only the Hook settings path for crash recovery and contains no API key.

- 旧版 start/status/stop 命令保留兼容；如果此前运行过后台模式，可先执行一次 python3 service.py stop，再使用新的前台模式。

  > Legacy `start`/`status`/`stop` commands remain available for compatibility. If you previously used background mode, run `python3 service.py stop` once before using foreground mode.

启动后，在目标项目运行 claude，用 /hooks 确认 MessageDisplay 已注册。
让 Claude 用英文回答测试，例如 `Explain Python virtual environments. Answer in English.`：屏幕显示中文，会话记录保留英文。
如果正在运行的 Claude 会话未识别新 Hook，请重新启动该会话。
本 Hook 不强制 Claude 用英文回复，需要英文记录时在提示词或 CLAUDE.md 中指定。

---

> After startup, run `claude` in the target project and use `/hooks` to confirm that MessageDisplay is registered.
> Test with an English reply, for example: `Explain Python virtual environments. Answer in English.` The screen shows Chinese while the conversation history retains English.
> If an existing Claude session does not recognize the new Hook, restart that session.
> This Hook does not force Claude to reply in English. Specify English in your prompt or `CLAUDE.md` if you need English conversation records.

## 全局输入翻译：Option+A / Global Input Translation: Option+A

服务开启后，固定快捷键 **Option+A（⌥A）**：

---

> While the service is running, use the fixed shortcut **Option+A (⌥A)**:

1. 输入框有文本选区：剪切该选区，翻译成英文，填回原位置。

   > If the input field has a selection, cut it, translate it into English, and insert the translation at the same position.

2. 没有选区：执行 Cmd+A 全选当前输入框，再剪切、翻译、填回。

   > If nothing is selected, use Cmd+A to select all text in the current input field, then cut, translate, and replace it.

3. 不自动提交消息。翻译失败时尝试回填中文原文；若焦点已改变或你有其他操作，不会粘贴到其他输入框，可从剪贴板恢复或在原输入框撤销剪切。

   > The message is not submitted automatically. If translation fails, the helper attempts to restore the original Chinese text. If focus changes or you interact with the application, it will not paste into another field. Recover the original from the clipboard or undo the cut in the original input field.

输入翻译采用标准复制/全选/剪切/粘贴快捷键，不限制具体应用，不再要求应用公开“可编辑”属性。优先利用辅助功能读取选区；如果应用未公开选区，则通过 Cmd+C 后剪贴板是否更新判断，有内容时处理选区，否则 Cmd+A 后复制全部内容。密码框及系统安全输入状态不会读取或剪切。请先将光标放入目标输入框；不能保证 Cmd+A 在所有应用里都代表输入框全选。部分编辑器在无选区时会复制当前行，在不能读取选区的情况下无法完全区分，需要手动验证应用行为。

---

> Input translation uses standard copy/select-all/cut/paste shortcuts, works across applications, and no longer requires the application to expose an “editable” attribute. It first tries to read the selection through Accessibility. If the application does not expose a selection, it checks whether Cmd+C updates the clipboard: if text is copied, it processes that selection; otherwise, it uses Cmd+A and copies all content. Password fields and system secure input are never read or cut. Put the cursor in the target input field first. Cmd+A is not guaranteed to select only the input field in every application. Some editors copy the current line when nothing is selected; if the selection cannot be read, this behavior cannot always be distinguished and must be checked manually.

首次运行需安装 Xcode Command Line Tools（已有 swiftc 可跳过）。程序把原生助手编译到 .runtime/input-hotkey。缺少辅助功能权限时，程序会通过 AXIsProcessTrustedWithOptions 的系统提示选项主动请求权限，由 macOS 显示授权提示。请在系统提示中打开设置，允许启动服务的终端及该原生助手；若提示输入监控权限也需要允许，然后重启服务。系统可能不重复弹出已拒绝的请求，此时按提示手动进入系统设置。权限未就绪会显示 Option+A 未启用；原有回复翻译 Hook 仍可工作。

---

> Install Xcode Command Line Tools before the first run (skip this if `swiftc` is already available). The program compiles the native helper to `.runtime/input-hotkey`. If Accessibility permission is missing, it requests permission using the system prompt option of `AXIsProcessTrustedWithOptions`, which lets macOS display an authorization prompt. Open Settings from that prompt and allow both the terminal running the service and the native helper. Also grant Input Monitoring permission if requested, then restart the service. macOS may not repeat a previously denied request; in that case, open System Settings manually as instructed. Until permissions are ready, the status shows that Option+A is unavailable; the reply translation Hook can still work.

- `input_translation_enabled`：true 启用，false 关闭；修改后重启服务。

  > `input_translation_enabled`: `true` enables input translation; `false` disables it. Restart the service after changing it.

- 固定 Option+A，不需要配置快捷键名称。该键在服务运行期间用于输入翻译。

  > Option+A is fixed; no shortcut name needs to be configured. It is used for input translation while the service runs.

- 运行过程中不记录键入内容；只在按下 Option+A 时读取当前可编辑选区。原生助手错误写入 .runtime/hotkey.log，不记录原文或 API Key。

  > Typing is not logged. The helper reads the current editable selection only when you press Option+A. Native helper errors go to `.runtime/hotkey.log`, without source text or API keys.

- 退出服务会注销快捷键。翻译期间切换应用/窗口、点击鼠标、滚动或继续键入时取消自动回填；自己生成的复制/剪切/粘贴事件不会被误判为用户操作。原文可通过剪贴板或撤销剪切恢复。

  > Exiting the service unregisters the shortcut. Switching applications or windows, clicking, scrolling, or typing during translation cancels automatic replacement. Generated copy/cut/paste events are not mistaken for user input. Recover the original through the clipboard or by undoing the cut.

- 剪贴板会在操作期间临时承载原文/译文，正常完成后恢复操作前的剪贴板；用户操作期间复制了其他内容时，保留新剪贴板。

  > The clipboard temporarily holds the source text and translation. On successful completion, its previous contents are restored. If you copy other content during the operation, the new clipboard contents are preserved.

### 不翻译的中文 / Chinese Text to Preserve

翻译提示词要求成对符号包裹的中文逐字保留（符号也保留）：

---

> The translation prompt asks the model to preserve Chinese enclosed in paired delimiters exactly, including the delimiters:

- 引号：双引号、单引号、中文弯引号、“「」”、“『』”。

  > Quotes: double quotes, single quotes, Chinese curly quotes, 「」, and 『』.

- 破折号：—中文—、——中文——、–中文–、--中文--、-中文-。

  > Dashes: —中文—, ——中文——, –中文–, --中文--, and -中文-.

- 括号等：（中文）、(中文)、【中文】、[中文]、《中文》、〈中文〉、{中文}、反引号包裹的中文。

  > Brackets and similar delimiters: （中文）, (中文), 【中文】, [中文], 《中文》, 〈中文〉, {中文}, and Chinese enclosed in backticks.

例：`请点击“确认”按钮，然后打开—设置页面—` → `Click the “确认” button, then open —设置页面—`（实际英文措辞由模型决定）。
程序直接把完整原文发送给 AI，仅通过提示词要求保留这些中文，不替换占位符、不进行局部拆分或还原，也不按中文是否残留拒绝译文。提示词明确要求只翻译外围文字，嵌套或多行区域同样保留。没有配对闭合的符号不构成保留区域。此规则仅用于输入的中译英，不影响原有英文回复的中文显示。

---

> Example: `请点击“确认”按钮，然后打开—设置页面—` → `Click the “确认” button, then open —设置页面—` (the model determines the exact English wording).
> The program sends the complete original text directly to the AI and relies only on the prompt to preserve this Chinese text. It does not replace text with placeholders, split and reconstruct protected regions, or reject translations because Chinese remains. The prompt explicitly asks the model to translate only the surrounding text and preserve nested or multiline regions as well. Unmatched delimiters do not define a protected region. This rule applies only to Chinese-to-English input translation and does not affect the Chinese display of English replies.

## 手动安装（可选） / Manual Installation (Optional)

不使用服务时仍可手动安装/卸载；不要把手动管理和服务管理混在同一设置文件里。

---

> You can still install or uninstall the Hook manually without using the service. Do not mix manual management and service management in the same settings file.

```bash
python3 install.py --settings /绝对路径/你的项目/.claude/settings.local.json
python3 install.py --settings /绝对路径/你的项目/.claude/settings.local.json --remove
```

> Replace `/绝对路径/你的项目` in the commands above with the absolute path to your project.

## 配置 / Configuration

首次启动会自动生成缺失的 config.json（权限 600），保留 config.example.json 的默认值且 API Key 为空。已有 config.json 不会被覆盖。配置示例：

---

> On the first run, a missing `config.json` is automatically created with permissions `600`, using the defaults from `config.example.json` and an empty API key. An existing `config.json` is never overwritten. Example configuration:

```json
{
  "api_key": "填写你的 API Key",
  "base_url": "https://api.deepseek.com",
  "api_format": "chat_completions",
  "thinking_type": "disabled",
  "model": "deepseek-flash",
  "timeout_seconds": 10,
  "hook_timeout_seconds": 30,
  "max_output_tokens": 393216,
  "enabled": true,
  "display_mode": "chinese",
  "settings_file": "~/.claude/settings.json",
  "show_balance": true,
  "balance_path": "/user/balance",
  "balance_timeout_seconds": 3,
  "balance_refresh_seconds": 30,
  "input_translation_enabled": true
}
```

运行时会读取 config.example.json 的默认值，再用 config.json 覆盖。配置项如下：

---

> At runtime, defaults are read from `config.example.json` and overridden by `config.json`. Configuration options:

| 配置 / Setting | 默认值 / Default | 中文说明 | English description |
|---|---|---|---|
| `api_key` | 空字符串 / Empty string | API Key，填写到 config.json | API key; enter it in config.json. |
| `base_url` | `https://api.deepseek.com` | API 基础地址，不包含具体接口路径 | API base URL, without the endpoint path. |
| `api_format` | `chat_completions` | 可选 chat_completions 或 responses | Either chat_completions or responses. |
| `thinking_type` | `disabled` | DeepSeek 思考模式；disabled 关闭以减少翻译等待，通用服务可设为 null 不发送该参数 | DeepSeek thinking mode; disabled reduces translation latency. Set to null for other providers to omit this parameter. |
| `model` | `deepseek-flash` | 服务支持的文本模型名称 | Name of a text model supported by the provider. |
| `timeout_seconds` | `10` | 单次网络等待超时，必须大于 0 且小于 Hook 超时 | Network wait timeout per request; must be positive and shorter than the Hook timeout. |
| `hook_timeout_seconds` | `30` | Claude Hook 超时，必须大于网络超时 | Claude Hook timeout; must exceed the network timeout. |
| `max_output_tokens` | `393216` | 译文输出 token 上限，超限回退原文 | Translation output token limit; falls back to the original on truncation. |
| `enabled` | `true` | 设为 false，临时停止翻译 | Set to false to pause translation. |
| `display_mode` | `chinese` | chinese 仅显示中文；bilingual 同时显示英文原文和中文译文 | chinese displays only Chinese; bilingual displays both the original English and the Chinese translation. |
| `settings_file` | `~/.claude/settings.json` | 服务管理的 Claude 设置文件；默认对所有项目生效 | Claude settings file managed by the service; applies to all projects by default. |
| `show_balance` | `true` | 启动状态行显示余额；false 则不查询 | Show balance in the startup status line; false skips balance queries. |
| `balance_path` | `/user/balance` | 余额接口路径，自动接在 base_url 后 | Balance endpoint path, appended to base_url. |
| `balance_timeout_seconds` | `3` | 单次余额查询的网络等待超时 | Network wait timeout per balance query. |
| `balance_refresh_seconds` | `30` | 余额刷新间隔（秒），最小 0.2，下一次查询读取新配置 | Balance refresh interval in seconds; minimum 0.2. The next query reads updated configuration. |
| `input_translation_enabled` | `true` | 启用固定 Option+A 输入翻译，需 macOS 原生助手权限 | Enable the fixed Option+A input translation shortcut; requires permissions for the native macOS helper. |

`base_url` 必须包含服务要求的前缀（例如 `/v1`），脚本按 api_format 自动追加 `/chat/completions` 或 `/responses`，末尾斜杠会自动移除。默认 DeepSeek 使用 chat_completions 格式。
所有项目配置均从文件读取，`OPENAI_API_KEY`、`OPENAI_MODEL` 和 `OPENAI_BASE_URL` 等环境变量不会覆盖文件配置。密钥不写入日志，config.json 已列入 .gitignore。
Responses 模式使用 `store: false`；Chat Completions 模式不发送 Responses 专用参数。每个翻译请求独立，不建立多轮会话。

---

> `base_url` must include any prefix required by the provider (such as `/v1`). Based on `api_format`, the script appends `/chat/completions` or `/responses` and removes trailing slashes. DeepSeek uses `chat_completions` by default.
> All project settings are read from files. Environment variables such as `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_BASE_URL` do not override them. Keys are not logged, and `config.json` is included in `.gitignore`.
> Responses requests use `store: false`; Chat Completions requests omit parameters specific to Responses. Each translation request is independent and does not create a multi-turn conversation.

若切回 OpenAI，可设置 base_url 为 https://api.openai.com/v1，api_format 为 responses，model 为账号支持的 OpenAI 模型，并替换相应 api_key。DeepSeek 配置必须填写 DeepSeek API Key。

---

> To switch to OpenAI, set `base_url` to `https://api.openai.com/v1`, `api_format` to `responses`, and `model` to an OpenAI model supported by your account, then replace `api_key` accordingly. DeepSeek configuration requires a DeepSeek API key.

修改 api_key、base_url、model、网络超时或 enabled 后，下一个 Hook 调用就会读取新值。服务模式修改 hook_timeout_seconds 或 settings_file 后，按 Ctrl+C，再重新运行 python3 service.py。手动模式修改 Hook 超时后需重新安装。

---

> Changes to `api_key`, `base_url`, `model`, network timeouts, or `enabled` take effect on the next Hook call. In service mode, changes to `hook_timeout_seconds` or `settings_file` require pressing Ctrl+C and running `python3 service.py` again. In manual mode, reinstall the Hook after changing its timeout.

## 显示行为与限制 / Display Behavior and Limitations

- 将 config.json 中的 `display_mode` 设为 `bilingual`，下一个 Hook 调用即生效。每个 `delta` 批次先显示英文原文，再换行显示中文译文，例如：

  > Set `display_mode` to `bilingual` in `config.json`; it takes effect on the next Hook call. Each `delta` batch displays the original English first, then a newline and the Chinese translation, for example:

  ```text
  All tests passed.
  所有测试均已通过。
  ```

  缺少该配置或填写其他值时沿用 `chinese` 模式；双语模式仍保留原始会话记录，翻译失败时仅显示原文。

  ---

  > If this option is missing or has any other value, `chinese` mode is used. Bilingual mode still preserves the original conversation history and displays only the original text if translation fails.

- 交互模式：每个 `delta` 批次单独翻译，不等待整个回复。因此显示有网络/翻译延迟，不是 token 级中文流式输出。

  > Interactive mode: each `delta` batch is translated independently without waiting for the entire reply. Display therefore includes network and translation latency; Chinese output is not streamed token by token.

- `claude -p` 等非交互模式：依据 Claude 文档，每个助手消息完成后会收到一次完整文本。

  > Non-interactive mode, such as `claude -p`: according to Claude’s documentation, one complete text event is received after each assistant message finishes.

- 仅处理助手回复文字，工具结果和用户输入不翻译。

  > Only assistant reply text is processed. Tool results and user input are not translated by this display Hook.

- 空批次、纯空白、没有英文字母的文本跳过 API；全中文最终批次不重复请求。

  > Empty batches, whitespace-only text, and text without English letters skip the API. A final batch containing only Chinese does not trigger another request.

- 输出给 Claude 的 stdout 只有 Hook JSON；错误只向 stderr 输出不含原文或密钥的简短错误类型。

  > Stdout sent to Claude contains only Hook JSON. Errors are reported to stderr as brief error types without source text or API keys.

- API 错误、缺少密钥、超时、拒绝回复、空译文或不完整响应时，返回 `{}`，显示英文原文。没有自动重试，以免增加屏幕等待。

  > API errors, missing keys, timeouts, refusals, empty translations, or incomplete responses return `{}`, so the original English is displayed. Requests are not automatically retried, to avoid additional display delays.

- Hook 注册超时为 30 秒，网络等待默认为 10 秒；外层 Hook 超时仍由 Claude 处理并回退原文。

  > The registered Hook timeout is 30 seconds; the default network timeout is 10 seconds. Claude handles the outer Hook timeout and falls back to the original text.

- 提示词要求保留 Markdown、代码、URL、路径、命令与标识符，但模型翻译不保证逐字符保留。不同批次独立翻译，跨批次代码块或术语一致性也可能受影响。

  > The prompt asks the model to preserve Markdown, code, URLs, paths, commands, and identifiers, but exact character preservation is not guaranteed. Independent batch translation may affect code blocks spanning batches or terminology consistency.

- 翻译文本会发送给 base_url 配置的服务；不会上传整份 transcript。Claude verbose 模式显示原文。

  > Translated text is sent to the provider configured in `base_url`; the complete transcript is not uploaded. Claude’s verbose mode displays the original text.

- 此工具仅改变本次渲染文本，不把中文译文写回 Claude 记录；不承诺历史重放界面始终显示中文。

  > This tool changes only the current rendering and does not write Chinese translations back to Claude’s records. It does not guarantee Chinese display when historical conversations are replayed.

## 关闭与卸载 / Shutdown and Uninstallation

在服务终端按 Ctrl+C，即关闭服务并移除 Hook。确认关闭成功后，可以删除项目目录。
临时暂停翻译可将 config.json 的 enabled 改为 false，服务依然运行。

---

> Press Ctrl+C in the service terminal to stop the service and remove the Hook. Once shutdown succeeds, you can delete the project directory.
> To pause translation temporarily, set `enabled` to `false` in `config.json`; the service keeps running.

## 独立测试 / Standalone Tests

不需要密钥，不会向真实翻译服务发送请求：

---

> No API key is required, and no requests are sent to a real translation service:

```bash
python3 -m unittest discover -s tests -v
```

测试启动本地模拟 HTTP 服务，验证真实子进程的请求、中文 Hook 返回、原文记录未改变、错误回退、超时、空批次以及安装/卸载对其他设置的保留。服务测试仅操作临时设置文件，验证前台原位置刷新余额、不新增状态行、Ctrl+C/终端关闭信号清理、后台兼容模式启停、重复启动、信号退出、强制终止后的残留清理和关闭时保留其他设置。

---

> Tests start a local mock HTTP server to verify requests from actual subprocesses, Chinese Hook output, unchanged original conversation records, error fallback, timeouts, empty batches, and preservation of other settings during installation and removal. Service tests use only temporary settings files and verify in-place foreground balance updates, no extra status lines, Ctrl+C and terminal-close signal cleanup, compatibility with background start/stop commands, duplicate startup handling, signal-based shutdown, recovery after forced termination, and preservation of other settings on shutdown.

用真实 API 单独检查（需要密钥，会产生 API 用量）：

---

> To check a real API separately (requires an API key and incurs API usage):

```bash
printf '%s' '{"hook_event_name":"MessageDisplay","delta":"All tests passed.\n","message_id":"demo","index":0,"final":true}' | python3 translate_hook.py
```

预期返回：

---

> Expected response in the default `chinese` mode:

```json
{"hookSpecificOutput":{"hookEventName":"MessageDisplay","displayContent":"所有测试均已通过。\n"}}
```

具体译文由模型决定。如果返回 `{}`，检查 stderr、config.json、账号模型权限及 API 网络连通性。

---

> The model determines the exact translation. If the output is `{}`, check stderr, `config.json`, account access to the configured model, and API connectivity.

## 官方参考 / Official References

- [Claude MessageDisplay：只替换显示，会话记录保留原文](https://code.claude.com/docs/en/hooks#messagedisplay)

  > [Claude MessageDisplay: replace only the display and preserve original conversation records](https://code.claude.com/docs/en/hooks#messagedisplay)

- [OpenAI 文本生成与 Responses API](https://developers.openai.com/api/docs/guides/text)

  > [OpenAI text generation and Responses API](https://developers.openai.com/api/docs/guides/text)

- [DeepSeek 官方首次调用说明与模型名称](https://api-docs.deepseek.com/)

  > [DeepSeek official first API call guide and model names](https://api-docs.deepseek.com/)

- [DeepSeek 官方查询余额接口](https://api-docs.deepseek.com/api/get-user-balance/)

  > [DeepSeek official balance query API](https://api-docs.deepseek.com/api/get-user-balance/)
