# `kero/cli/`

CLI 交互层。这里负责终端入口、启动 banner、setup 向导和 config 子命令。

## Files

- `app.py`：主入口、聊天循环、slash commands。
- `banner.py`：纯 ASCII Kero Logo 和启动状态展示。
- `config_cmd.py`：`python -m kero config ...` 子命令。
- `setup.py`：`python -m kero setup` 交互式配置向导。
- `__init__.py`：导出 `main`。

## Main Functions

- `main(argv=None)`：解析命令行；无子命令时进入聊天。
- `_run_chat(config)`：创建 memory、LLM、reflection，并运行 REPL。
- `_handle_command(...)`：处理 `/help`、`/memory`、`/reflect` 等聊天内命令。
- `build_banner(config, llm_ready)`：生成启动 Logo 和运行状态。
- `run_setup(...)`：写入 `$KERO_HOME/config.yaml` 和 `.env`。
- `run_config_command(args)`：执行 config show/path/init/get/set/validate。

## Design Notes

Kero 保持无参数启动为聊天模式。`setup` 和 `config` 是显式子命令，不影响原本的 `python -m kero` 体验。
