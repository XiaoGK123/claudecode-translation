# Claude Code 显示翻译 Hook

把 Claude Code 的英文回复批次交给配置的翻译 API（默认 DeepSeek），返回简体中文并只替换屏幕显示。
Claude 会话记录与模型上下文保留原始回复。脚本不读取、不写入 `transcript_path`。

```text
Claude 英文回复 ───────────────→ Claude 会话记录（原文）
       │
       └→ MessageDisplay.delta → 翻译 API
                                   │
                             中文翻译 → displayContent → 屏幕
```

## 环境

- Python 3.9 或更新版本，无第三方依赖。
- 支持 `MessageDisplay` 事件的 Claude Code。本机检测版本：2.1.296。
- DeepSeek API Key，或其他兼容服务的 API Key；可选择 Chat Completions 或 Responses 接口。
- 默认模型为 DeepSeek 官方当前的 `deepseek-flash`，可以修改。

## 持续运行服务（推荐）

所有配置均在本目录的 config.json 中。缺少文件时，运行 python3 service.py 会自动从示例生成空密钥配置，输出“无config.json文件，目前已自动生成，文件位置：…，请配置api信息后重启”后直接退出；不会安装 Hook 或启动服务。填写 api_key、base_url、model 后，再次运行，保持 enabled 为 true。
默认 settings_file 为 ~/.claude/settings.json，启动服务会注册用户级 Hook，对所有 Claude 项目生效。
如果只希望用于一个项目，将 settings_file 改为该项目 .claude/settings.local.json 的绝对路径。

只需一条启动命令：

```bash
cd /Users/xiaomingwen/my-projects/ClaudeCodeTranslation
python3 service.py
```

程序在当前终端持续运行，启动时安装 Hook，只显示一行状态，并在原位置定时更新余额，其他状态不重复输出：

```text
服务运行中 | Hook 已安装 | 模型 deepseek-flash | 余额 110.00 CNY | 按 Ctrl+C 关闭并删除 Hook
```

上面余额为展示示例，实际从 DeepSeek 的 GET /user/balance 查询。启动时查询余额，之后默认每 30 秒刷新一次，只在原状态行覆盖余额，不新增日志行。显示总可用余额（含赠金和充值余额）；查询失败或缺少密钥时显示提示，服务继续运行。余额请求在后台线程执行，不阻塞退出清理。重定向到文件时只输出启动状态，不写入重复余额日志。

**关闭：在这个终端按 Ctrl+C。** 程序会先删除自己注册的 Hook，再退出，显示“服务已关闭，Hook 已删除”。其他 Claude 设置和 Hook 保留。
关闭终端时如果进程收到 SIGHUP，也会执行清理；推荐 Ctrl+C，以便确认删除成功。服务不会自动转入后台，不需要单独执行 status 或 stop。

- 启动状态表示 Hook 已注册，不代表已验证真实 API 连通性。
- enabled 改为 false 可暂停翻译；下一个 Hook 调用会读取新值。
- 服务正常退出或收到 SIGTERM、SIGINT、SIGHUP 时会移除 Hook。
- SIGKILL、系统崩溃或断电无法执行退出清理，Hook 可能残留。下一次启动会清理残留；也保留 `python3 service.py stop` 用于单独清理。
- 修改 settings_file 或 hook_timeout_seconds 后，按 Ctrl+C，再重新运行 python3 service.py。
- 服务保持运行期间可以在另一个终端或 IDE 中使用 Claude。
- 重复运行会提示已有服务，不会再启动第二个实例。
- .runtime/state.json 仅记录 Hook 注册位置用于异常退出恢复，不包含密钥。
- 旧版 start/status/stop 命令保留兼容；如果此前运行过后台模式，可先执行一次 python3 service.py stop，再使用新的前台模式。

启动后，在目标项目运行 claude，用 /hooks 确认 MessageDisplay 已注册。
让 Claude 用英文回答测试，例如 `Explain Python virtual environments. Answer in English.`：屏幕显示中文，会话记录保留英文。
如果正在运行的 Claude 会话未识别新 Hook，请重新启动该会话。
本 Hook 不强制 Claude 用英文回复，需要英文记录时在提示词或 CLAUDE.md 中指定。

## 全局输入翻译：Option+A

服务开启后，固定快捷键 **Option+A（⌥A）**：

1. 输入框有文本选区：剪切该选区，翻译成英文，填回原位置。
2. 没有选区：执行 Cmd+A 全选当前输入框，再剪切、翻译、填回。
3. 不自动提交消息。翻译失败时尝试回填中文原文；若焦点已改变或你有其他操作，不会粘贴到其他输入框，可从剪贴板恢复或在原输入框撤销剪切。

输入翻译采用标准复制/全选/剪切/粘贴快捷键，不限制具体应用，不再要求应用公开“可编辑”属性。优先利用辅助功能读取选区；如果应用未公开选区，则通过 Cmd+C 后剪贴板是否更新判断，有内容时处理选区，否则 Cmd+A 后复制全部内容。密码框及系统安全输入状态不会读取或剪切。请先将光标放入目标输入框；不能保证 Cmd+A 在所有应用里都代表输入框全选。部分编辑器在无选区时会复制当前行，在不能读取选区的情况下无法完全区分，需要手动验证应用行为。

首次运行需安装 Xcode Command Line Tools（已有 swiftc 可跳过）。程序把原生助手编译到 .runtime/input-hotkey。缺少辅助功能权限时，程序会通过 AXIsProcessTrustedWithOptions 的系统提示选项主动请求权限，由 macOS 显示授权提示。请在系统提示中打开设置，允许启动服务的终端及该原生助手；若提示输入监控权限也需要允许，然后重启服务。系统可能不重复弹出已拒绝的请求，此时按提示手动进入系统设置。权限未就绪会显示 Option+A 未启用；原有回复翻译 Hook 仍可工作。

- `input_translation_enabled`：true 启用，false 关闭；修改后重启服务。
- 固定 Option+A，不需要配置快捷键名称。该键在服务运行期间用于输入翻译。
- 运行过程中不记录键入内容；只在按下 Option+A 时读取当前可编辑选区。原生助手错误写入 .runtime/hotkey.log，不记录原文或 API Key。
- 退出服务会注销快捷键。翻译期间切换应用/窗口、点击鼠标、滚动或继续键入时取消自动回填；自己生成的复制/剪切/粘贴事件不会被误判为用户操作。原文可通过剪贴板或撤销剪切恢复。
- 剪贴板会在操作期间临时承载原文/译文，正常完成后恢复操作前的剪贴板；用户操作期间复制了其他内容时，保留新剪贴板。

### 不翻译的中文

翻译提示词要求成对符号包裹的中文逐字保留（符号也保留）：

- 引号：双引号、单引号、中文弯引号、“「」”、“『』”。
- 破折号：—中文—、——中文——、–中文–、--中文--、-中文-。
- 括号等：（中文）、(中文)、【中文】、[中文]、《中文》、〈中文〉、{中文}、反引号包裹的中文。

例：`请点击“确认”按钮，然后打开—设置页面—` → `Click the “确认” button, then open —设置页面—`（实际英文措辞由模型决定）。
程序直接把完整原文发送给 AI，仅通过提示词要求保留这些中文，不替换占位符、不进行局部拆分或还原，也不按中文是否残留拒绝译文。提示词明确要求只翻译外围文字，嵌套或多行区域同样保留。没有配对闭合的符号不构成保留区域。此规则仅用于输入的中译英，不影响原有英文回复的中文显示。

## 手动安装（可选）

不使用服务时仍可手动安装/卸载；不要把手动管理和服务管理混在同一设置文件里。

```bash
python3 install.py --settings /绝对路径/你的项目/.claude/settings.local.json
python3 install.py --settings /绝对路径/你的项目/.claude/settings.local.json --remove
```

## 配置

首次启动会自动生成缺失的 config.json（权限 600），保留 config.example.json 的默认值且 API Key 为空。已有 config.json 不会被覆盖。配置示例：

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

| 配置 | 默认值 | 说明 |
|---|---|---|
| `api_key` | 空字符串 | API Key，填写到 config.json |
| `base_url` | `https://api.deepseek.com` | API 基础地址，不包含具体接口路径 |
| `api_format` | `chat_completions` | 可选 chat_completions 或 responses |
| `thinking_type` | `disabled` | DeepSeek 思考模式；disabled 关闭以减少翻译等待，通用服务可设为 null 不发送该参数 |
| `model` | `deepseek-flash` | 服务支持的文本模型名称 |
| `timeout_seconds` | `10` | 单次网络等待超时，必须大于 0 且小于 Hook 超时 |
| `hook_timeout_seconds` | `30` | Claude Hook 超时，必须大于网络超时 |
| `max_output_tokens` | `393216` | 译文输出 token 上限，超限回退原文 |
| `enabled` | `true` | 设为 false，临时停止翻译 |
| `display_mode` | `chinese` | chinese 仅显示中文；bilingual 同时显示英文原文和中文译文 |
| `settings_file` | `~/.claude/settings.json` | 服务管理的 Claude 设置文件；默认对所有项目生效 |
| `show_balance` | `true` | 启动状态行显示余额；false 则不查询 |
| `balance_path` | `/user/balance` | 余额接口路径，自动接在 base_url 后 |
| `balance_timeout_seconds` | `3` | 单次余额查询的网络等待超时 |
| `balance_refresh_seconds` | `30` | 余额刷新间隔（秒），最小 0.2，下一次查询读取新配置 |
| `input_translation_enabled` | `true` | 启用固定 Option+A 输入翻译，需 macOS 原生助手权限 |

`base_url` 必须包含服务要求的前缀（例如 `/v1`），脚本按 api_format 自动追加 `/chat/completions` 或 `/responses`，末尾斜杠会自动移除。默认 DeepSeek 使用 chat_completions 格式。
所有项目配置均从文件读取，`OPENAI_API_KEY`、`OPENAI_MODEL` 和 `OPENAI_BASE_URL` 等环境变量不会覆盖文件配置。密钥不写入日志，config.json 已列入 .gitignore。
Responses 模式使用 `store: false`；Chat Completions 模式不发送 Responses 专用参数。每个翻译请求独立，不建立多轮会话。

若切回 OpenAI，可设置 base_url 为 https://api.openai.com/v1，api_format 为 responses，model 为账号支持的 OpenAI 模型，并替换相应 api_key。DeepSeek 配置必须填写 DeepSeek API Key。

修改 api_key、base_url、model、网络超时或 enabled 后，下一个 Hook 调用就会读取新值。服务模式修改 hook_timeout_seconds 或 settings_file 后，按 Ctrl+C，再重新运行 python3 service.py。手动模式修改 Hook 超时后需重新安装。

## 显示行为与限制

- 将 config.json 中的 `display_mode` 设为 `bilingual`，下一个 Hook 调用即生效。每个 `delta` 批次先显示英文原文，再换行显示中文译文，例如：

  ```text
  All tests passed.
  所有测试均已通过。
  ```

  缺少该配置或填写其他值时沿用 `chinese` 模式；双语模式仍保留原始会话记录，翻译失败时仅显示原文。

- 交互模式：每个 `delta` 批次单独翻译，不等待整个回复。因此显示有网络/翻译延迟，不是 token 级中文流式输出。
- `claude -p` 等非交互模式：依据 Claude 文档，每个助手消息完成后会收到一次完整文本。
- 仅处理助手回复文字，工具结果和用户输入不翻译。
- 空批次、纯空白、没有英文字母的文本跳过 API；全中文最终批次不重复请求。
- 输出给 Claude 的 stdout 只有 Hook JSON；错误只向 stderr 输出不含原文或密钥的简短错误类型。
- API 错误、缺少密钥、超时、拒绝回复、空译文或不完整响应时，返回 `{}`，显示英文原文。没有自动重试，以免增加屏幕等待。
- Hook 注册超时为 30 秒，网络等待默认为 10 秒；外层 Hook 超时仍由 Claude 处理并回退原文。
- 提示词要求保留 Markdown、代码、URL、路径、命令与标识符，但模型翻译不保证逐字符保留。不同批次独立翻译，跨批次代码块或术语一致性也可能受影响。
- 翻译文本会发送给 base_url 配置的服务；不会上传整份 transcript。Claude verbose 模式显示原文。
- 此工具仅改变本次渲染文本，不把中文译文写回 Claude 记录；不承诺历史重放界面始终显示中文。

## 关闭与卸载

在服务终端按 Ctrl+C，即关闭服务并移除 Hook。确认关闭成功后，可以删除项目目录。
临时暂停翻译可将 config.json 的 enabled 改为 false，服务依然运行。

## 独立测试

不需要密钥，不会向真实翻译服务发送请求：

```bash
python3 -m unittest discover -s tests -v
```

测试启动本地模拟 HTTP 服务，验证真实子进程的请求、中文 Hook 返回、原文记录未改变、错误回退、超时、空批次以及安装/卸载对其他设置的保留。服务测试仅操作临时设置文件，验证前台原位置刷新余额、不新增状态行、Ctrl+C/终端关闭信号清理、后台兼容模式启停、重复启动、信号退出、强制终止后的残留清理和关闭时保留其他设置。

用真实 API 单独检查（需要密钥，会产生 API 用量）：

```bash
printf '%s' '{"hook_event_name":"MessageDisplay","delta":"All tests passed.\n","message_id":"demo","index":0,"final":true}' | python3 translate_hook.py
```

预期返回：

```json
{"hookSpecificOutput":{"hookEventName":"MessageDisplay","displayContent":"所有测试均已通过。\n"}}
```

具体译文由模型决定。如果返回 `{}`，检查 stderr、config.json、账号模型权限及 API 网络连通性。

## 官方参考

- [Claude MessageDisplay：只替换显示，会话记录保留原文](https://code.claude.com/docs/en/hooks#messagedisplay)
- [OpenAI 文本生成与 Responses API](https://developers.openai.com/api/docs/guides/text)
- [DeepSeek 官方首次调用说明与模型名称](https://api-docs.deepseek.com/)

- [DeepSeek 官方查询余额接口](https://api-docs.deepseek.com/api/get-user-balance/)
