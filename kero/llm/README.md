# `kero/llm/`

LLM 接入层。它借鉴 Hermes 的 provider profile 思路，但只保留聊天生成需要的最小实现。

## Files

- `providers.py`：静态 provider registry。
- `client.py`：统一 `LLMClient` 和本地 fallback responder。
- `__init__.py`：导出常用类型。

## Main Classes And Functions

- `ProviderProfile`：描述 provider 的名称、别名、base_url、默认模型、环境变量和 api mode。
- `get_provider(name)`：按名称或 alias 查 provider。
- `list_providers()`：列出可配置 provider。
- `LLMClient.complete(messages, purpose="chat")`：统一调用 chat completions 或 Anthropic messages。
- `LLMClient.is_configured()`：判断当前 provider/API key 是否足够可用。
- `RuleBasedResponder.reply(...)`：LLM 不可用时的本地陪伴回复。

## Supported API Modes

- `chat_completions`：OpenAI-compatible API。
- `anthropic_messages`：Anthropic Messages API。
- `unsupported`：保留 Hermes 中过重的 provider 名称，但运行时明确提示不支持。

## Extension Notes

新增 OpenAI-compatible provider 通常只需要在 `providers.py` 注册一个 `ProviderProfile`。如果 provider 需要 OAuth、工具调用或非标准 wire format，建议先保持 unsupported，避免把 Kero 拉回 Hermes 的复杂度。
