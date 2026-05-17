# `kero/memory/`

Kero 最重要的子系统。它参考 Hermes 的内置 persistent memory，同时增加 JSONL 长期记忆召回。

## Files

- `store.py`：底层存储。包含 curated memory、long-term memory、profile store、原子写入和文件锁。
- `manager.py`：上层 facade。连接短期记忆、长期召回、用户画像和会话日志。
- `retrieval.py`：关键词、CJK bigram、哈希向量和 recency/importance 打分。
- `safety.py`：写入 memory 前的风险扫描。
- `__init__.py`：导出常用类。

## Main Classes And Functions

- `CuratedMemoryStore`：管理 `MEMORY.md` 和 `USER.md`。
- `LongTermMemoryStore`：管理 `long_term.jsonl`，支持 `add()`、`search()`、`remove()`。
- `ProfileStore`：管理结构化用户画像 `profile.json`。
- `MemoryManager.build_context(query)`：构建当前轮可用的 memory context。
- `MemoryManager.record_turn(user, assistant)`：保存当前轮到短期上下文和 session log。
- `MemoryManager.remember(...)`：显式写入 curated memory 和 long-term memory。
- `scan_memory_content(content)`：阻止 prompt injection、密钥读取和隐藏 Unicode。

## Runtime Files

```text
data/memories/MEMORY.md
data/memories/USER.md
data/memory/long_term.jsonl
data/profile/profile.json
data/sessions/current.jsonl
```

## Data Flow

1. CLI 启动时创建 `MemoryManager`。
2. `CuratedMemoryStore.load()` 保证 `MEMORY.md` 和 `USER.md` 存在，并捕获 frozen snapshot。
3. 每轮用户输入调用 `build_context()` 召回相关长期记忆。
4. 回复后调用 `record_turn()`。
5. 反思模块把稳定信息写回 profile、curated memory 和 long-term memory。

## Hermes Reference

保留 Hermes 的：

- 双文件 curated memory。
- `§` 分隔。
- 字符预算。
- frozen snapshot。
- 安全扫描。

Kero 暂不实现 Hermes 的外部 memory provider 插件、SQLite FTS5 session search 和 memory tool schema。
