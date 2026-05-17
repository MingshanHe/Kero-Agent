# `kero/`

Kero 的 Python 包根目录。这里放跨模块共享的配置、版本入口和各子系统。

## Files

- `__init__.py`：定义 `__version__`。
- `__main__.py`：支持 `python -m kero`，转发到 CLI。
- `config.py`：配置加载、保存、校验和 dot-path 读写。

## `config.py`

主要职责：

- `KeroConfig.load()`：加载最终运行配置。
- `load_config_data()`：按优先级合并默认值、项目配置、`$KERO_HOME/config.yaml`、环境变量和 CLI override。
- `save_config_data()`：写入 YAML 配置。
- `set_dot_path()` / `get_dot_path()`：支持 `llm.provider` 这种命令式配置路径。
- `validate_config_data()`：检查 provider 是否存在、数值配置是否可解析。

## Data Flow

CLI 启动后先调用 `KeroConfig.load()`，再把配置传给 `MemoryManager`、`LLMClient` 和 `ReflectionEngine`。

## Extension Notes

新增全局配置时，需要同时更新：

- `DEFAULT_CONFIG`
- dataclass 字段
- `CONFIG_ENV_MAP`，如果需要环境变量覆盖
- README 中的配置说明
