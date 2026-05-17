# `kero/evolution/`

自我进化层。它把短期对话转成长期画像、偏好和陪伴策略。

## Files

- `reflection.py`：反思引擎和结果类型。
- `__init__.py`：导出 `ReflectionEngine` 和 `ReflectionResult`。

## Main Classes And Functions

- `ReflectionEngine.maybe_reflect(trigger)`：按轮数判断是否需要反思。
- `ReflectionEngine.reflect(trigger)`：强制反思当前短期会话。
- `_reflect_with_llm(...)`：有 LLM 时要求模型输出严格 JSON。
- `_reflect_with_rules(...)`：无 LLM 或解析失败时的规则兜底。
- `_apply(result)`：把反思写入 profile、long-term memory 和 reflection log。
- `_extract_json_object(text)`：从模型输出中提取 JSON 对象。

## Reflection Output

反思会产生：

- `summary`
- `profile_update`
- `durable_memories`
- `used_fallback`

这些内容会落到：

```text
data/profile/profile.json
data/memory/long_term.jsonl
data/reflections/reflections.jsonl
```

## Extension Notes

如果要增强陪伴能力，优先改反思 schema 和 `_reflect_with_rules()`，再调整 `MemoryManager.merge_profile()` 的合并策略。
