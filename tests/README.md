# `tests/`

Kero 的测试目录。

## Files

- `test_memory.py`：memory 安全扫描、curated memory、long-term recall、初始化文件。
- `test_reflection.py`：规则反思和 profile 更新。
- `test_config.py`：配置优先级、dot-path、setup 非交互写入。
- `test_cli.py`：CLI help 和子命令 help。

## Running

```bash
pip install -e ".[dev]"
pytest -q
```

当前环境如果没有安装 `pytest`，可以先用 `python -m compileall -q kero` 和 CLI smoke test 做基础验证。
