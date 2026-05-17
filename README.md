# Kero Agent

Kero 是一个基于 Python CLI 的智能陪伴机器人原型。它参考 Hermes Agent 的工程思路，但刻意把范围收窄到陪伴系统最重要的两条主线：

- Memory：稳定、可控、可召回的长期记忆。
- Evolution：在对话过程中反思，并逐步更新用户画像和陪伴策略。

Kero 不包含 Tools、MCP、技能系统、多平台网关、子代理、浏览器或文件操作工具。它的第一屏就是 CLI 对话。

## Quick Start

```bash
cd kero-agent
python -m kero
```

首次运行如果没有配置 LLM，Kero 会进入本地规则 fallback 模式，方便先验证 CLI 和 memory 链路。

在对话中输入 `/speak` 可以把最后一次 LLM 回复转换为语音并播放；启动时加 `--speak` 可自动播放每次回答。

## Setup

交互式配置：

```bash
python -m kero setup
```

仅配置 Copilot（直接进入 Copilot device code flow）：

```bash
python -m kero setup --only-copilot
```

非交互写入默认配置：

```bash
python -m kero setup --non-interactive
```

配置文件默认写入：

```text
kero-agent/data/config.yaml
kero-agent/data/.env
```

项目根目录提供 `kero.yaml.example`，可以复制成 `kero.yaml` 作为项目级默认配置。

设置 `KERO_HOME` 后，配置和运行数据会写到指定目录：

```bash
export KERO_HOME=~/.kero
python -m kero setup
```

## Config Commands

```bash
python -m kero config show
python -m kero config path
python -m kero config init
python -m kero config get llm.provider
python -m kero config set llm.provider openrouter
python -m kero config set llm.model anthropic/claude-sonnet-4.6
python -m kero config validate
```

配置优先级从低到高：

```text
默认值
  -> 项目 kero.yaml
  -> $KERO_HOME/config.yaml
  -> 环境变量
  -> 本次 CLI 参数
```

常用环境变量：

```bash
export KERO_PROVIDER=openrouter
export KERO_MODEL=anthropic/claude-sonnet-4.6
export OPENROUTER_API_KEY=...
```

聊天时也可以临时覆盖：

```bash
python -m kero --provider custom --model llama3 --base-url http://127.0.0.1:11434/v1
python -m kero --no-llm
```

## Supported LLM Providers

Kero 使用 Hermes 风格的 provider profile，但只保留聊天所需的轻量路径。

可直接使用的 provider：

- `openai`
- `openrouter`
- `anthropic`
- `custom` / `local` / `lmstudio` / `ollama`
- `deepseek`
- `kimi`
- `kimi-cn`
- `zai`
- `qwen`
- `nvidia`
- `nous-api`
- `ai-gateway`
- `huggingface`
- `novita`
- `xiaomi`
- `arcee`
- `minimax`

保留但不启用的重型 Hermes 路径：

- `openai-codex`
- `bedrock`

这些需要 OAuth、SDK auth 或复杂 runtime，Kero 第一版不引入。

## CLI Commands

进入聊天后支持：

```text
/help                 查看命令
/profile              查看结构化用户画像
/memory [query]       召回长期记忆
/remember <text>      显式保存记忆
/forget <substring>   删除匹配记忆
/reflect              立即反思
/model                查看模型配置和 provider 列表
/config               查看当前配置和 memory 状态
/memory-status        查看 memory 文件路径、大小、存在状态
/clear                清空短期上下文
/exit                 反思并退出
```

## Memory Design

Kero 的 memory 参考 Hermes 的内置 memory，而不是外部 memory provider。

### Curated Memory

启动时会保证这两个文件存在：

```text
data/memories/MEMORY.md
data/memories/USER.md
```

用途：

- `MEMORY.md`：Kero 的长期观察、陪伴策略、稳定事实。
- `USER.md`：用户画像、偏好、称呼、交流风格。

它们使用 Hermes 的关键设计：

- 字符上限，避免 prompt 无限增长。
- 使用 `§` 分隔多条记忆。
- add / replace / remove 都使用唯一子串匹配。
- 写入前扫描 prompt injection、密钥读取、SSH 后门、隐藏 Unicode 等风险。
- 启动时捕获 frozen snapshot；当前会话中新增记忆会落盘，但不会改变已构建的 memory snapshot。

### Long-Term Memory

```text
data/memory/long_term.jsonl
```

这是 Kero 为陪伴场景增加的轻量长期记忆。它保存反思抽取出的事实、偏好、情绪线索和主题，并用关键词 + 哈希向量做本地召回，不依赖外部 embedding 或向量库。

### Session And Reflection

```text
data/sessions/current.jsonl
data/profile/profile.json
data/reflections/reflections.jsonl
```

Kero 会在每 N 轮、`/reflect`、`/exit` 时反思当前会话。有 LLM 时要求模型返回严格 JSON；没有 LLM 或解析失败时，用规则提取“我叫/叫我/我喜欢/记住/以后你...”这类稳定信息。

## Project Structure

```text
kero-agent/
  kero/
    cli/             # CLI loop、banner、setup、config 命令
    llm/             # provider profile 和 LLM client
    memory/          # curated memory、长期记忆、召回、安全扫描
    evolution/       # 反思和自我进化
  data/              # 运行时数据
  tests/             # 单元测试
```

每个主要目录都有自己的 README，说明文件职责、核心函数和扩展建议。

## How Kero Differs From Hermes

保留：

- `MEMORY.md` / `USER.md` 双文件记忆。
- 安全扫描和字符预算。
- 会话边界反思。
- provider profile 的配置思想。
- 动态召回记忆与用户输入分隔。

删除：

- Tools / MCP。
- 外部 memory provider 插件系统。
- skills。
- gateway / cron / subagent。
- SQLite FTS5 session search。

## FAQ

### 为什么 `MEMORY.md` 和 `USER.md` 是空文件？

空文件代表 curated memory 已初始化但还没有条目。Kero 不写注释到文件里，因为注释会被当成真实记忆解析。

### `.lock` 文件是什么？

Kero 写 JSONL 和 memory 文件时使用 lock 文件，避免多个进程同时写入造成损坏。它们是正常运行产物。

### 没有 API key 能不能用？

可以。Kero 会使用本地规则 fallback 回复，并且仍然能测试 memory 和 reflection 的基本流程。

### 如何使用本地模型？

配置 OpenAI-compatible 本地服务：

```bash
python -m kero config set llm.provider custom
python -m kero config set llm.base_url http://127.0.0.1:1234/v1
python -m kero config set llm.model your-local-model
```
