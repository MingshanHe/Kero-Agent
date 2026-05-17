# `data/`

Kero 默认运行时数据目录。设置 `KERO_HOME` 后，这些文件会写到新的 home 目录。

## Files And Directories

- `config.yaml`：setup/config 命令写入的主配置。
- `.env`：setup 写入的 API key 等敏感环境变量。
- `memories/MEMORY.md`：Kero 的 curated memory。
- `memories/USER.md`：用户画像 curated memory。
- `memory/long_term.jsonl`：可检索长期记忆。
- `profile/profile.json`：结构化用户画像。
- `sessions/current.jsonl`：当前会话历史。
- `reflections/reflections.jsonl`：反思日志。

## Lock Files

`*.lock` 文件是正常运行产物。Kero 用它们保护 JSONL 和 memory 文件，避免多个进程同时写入时破坏数据。

## Do Not Commit Personal Data

这个目录可能包含用户画像、对话历史和 API key。真实使用时建议把 `data/` 加入 `.gitignore`，或使用 `KERO_HOME=~/.kero` 把运行数据放到项目外。
