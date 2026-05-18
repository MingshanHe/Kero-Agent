from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_kero_home() -> Path:
    configured = os.environ.get("KERO_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / "data"


def get_project_config_path() -> Path:
    return project_root() / "kero.yaml"


def get_home_config_path(home: Path | None = None) -> Path:
    return (home or get_kero_home()) / "config.yaml"


def get_home_env_path(home: Path | None = None) -> Path:
    return (home or get_kero_home()) / ".env"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(path, override=False)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _dump_yaml(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    except Exception as exc:
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _deep_get(data: dict[str, Any], path: tuple[str, ...], default: Any) -> Any:
    node: Any = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _env_first(name: str, fallback: Any) -> Any:
    value = os.environ.get(name)
    return value if value not in (None, "") else fallback


def _parse_env_bool(name: str, fallback: bool) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_value(raw: str) -> Any:
    """Parse CLI config values using YAML rules, with string fallback."""
    try:
        import yaml
        return yaml.safe_load(raw)
    except Exception:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw


DEFAULT_CONFIG: dict[str, Any] = {
    "llm": {
        "provider": "openrouter",
        "model": "anthropic/claude-sonnet-4.6",
        "api_key": "",
        "base_url": "",
        "command": "",
        "provider_options": {},
        "temperature": 0.7,
        "max_tokens": 1200,
        "timeout_seconds": 120.0,
        "enabled": True,
    },
    "providers": {},
    "custom_providers": [],
    "memory": {
        "short_term_turns": 8,
        "recall_top_k": 6,
        "recall_min_score": 0.04,
        "memory_char_limit": 5000,
        "user_char_limit": 3000,
        "long_term_char_limit": 120000,
        "reflection_interval_turns": 8,
        "reflection_min_turns": 3,
    },
}


CONFIG_ENV_MAP: dict[tuple[str, ...], tuple[str, type]] = {
    ("llm", "provider"): ("KERO_PROVIDER", str),
    ("llm", "model"): ("KERO_MODEL", str),
    ("llm", "api_key"): ("KERO_API_KEY", str),
    ("llm", "base_url"): ("KERO_BASE_URL", str),
    ("llm", "command"): ("KERO_LLM_COMMAND", str),
    ("llm", "temperature"): ("KERO_TEMPERATURE", float),
    ("llm", "max_tokens"): ("KERO_MAX_TOKENS", int),
    ("llm", "timeout_seconds"): ("KERO_TIMEOUT_SECONDS", float),
    ("llm", "enabled"): ("KERO_LLM_ENABLED", bool),
    ("memory", "short_term_turns"): ("KERO_SHORT_TERM_TURNS", int),
    ("memory", "recall_top_k"): ("KERO_RECALL_TOP_K", int),
    ("memory", "recall_min_score"): ("KERO_RECALL_MIN_SCORE", float),
    ("memory", "memory_char_limit"): ("KERO_MEMORY_CHAR_LIMIT", int),
    ("memory", "user_char_limit"): ("KERO_USER_CHAR_LIMIT", int),
    ("memory", "long_term_char_limit"): ("KERO_LONG_TERM_CHAR_LIMIT", int),
    ("memory", "reflection_interval_turns"): ("KERO_REFLECTION_INTERVAL_TURNS", int),
    ("memory", "reflection_min_turns"): ("KERO_REFLECTION_MIN_TURNS", int),
}


def set_dot_path(data: dict[str, Any], key_path: str, value: Any) -> None:
    keys = [part for part in key_path.split(".") if part]
    if not keys:
        raise ValueError("config key cannot be empty")
    node = data
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[keys[-1]] = value


def get_dot_path(data: dict[str, Any], key_path: str) -> Any:
    keys = [part for part in key_path.split(".") if part]
    node: Any = data
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise KeyError(key_path)
        node = node[key]
    return node


def load_config_data(
    *,
    config_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    include_env: bool = True,
) -> dict[str, Any]:
    """Load raw config with Kero's precedence.

    Precedence, low to high:
    defaults -> project kero.yaml -> $KERO_HOME/config.yaml or explicit path
    -> environment variables -> explicit overrides.
    """
    home = get_kero_home()
    _load_dotenv(project_root() / ".env")
    _load_dotenv(get_home_env_path(home))

    data = dict(DEFAULT_CONFIG)
    project_config = _load_yaml(get_project_config_path())
    if project_config:
        data = _deep_merge(data, project_config)

    selected_path: Path | None
    if config_path:
        selected_path = Path(config_path).expanduser()
        if not selected_path.is_absolute():
            selected_path = (project_root() / selected_path).resolve()
    else:
        selected_path = get_home_config_path(home)

    home_config = _load_yaml(selected_path)
    if home_config:
        data = _deep_merge(data, home_config)

    if include_env:
        env_home = os.environ.get("KERO_HOME", "").strip()
        if env_home:
            data["home"] = env_home
        for path, (env_name, caster) in CONFIG_ENV_MAP.items():
            raw = os.environ.get(env_name)
            if raw in (None, ""):
                continue
            try:
                value = _parse_env_bool(env_name, False) if caster is bool else caster(raw)
            except (TypeError, ValueError):
                value = raw
            set_dot_path(data, ".".join(path), value)

    if overrides:
        data = _deep_merge(data, overrides)
    return data


def save_config_data(data: dict[str, Any], path: Path | None = None) -> Path:
    target = path or get_home_config_path()
    _dump_yaml(data, target)
    return target


def write_default_config(path: Path | None = None, *, force: bool = False) -> Path:
    target = path or get_home_config_path()
    if target.exists() and not force:
        return target
    return save_config_data(DEFAULT_CONFIG, target)


def write_env_value(key: str, value: str, path: Path | None = None) -> Path:
    target = path or get_home_env_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.startswith(f"{key}="):
                lines.append(line)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    lines.append(f'{key}="{escaped}"')
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


def redact_config(data: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(data, ensure_ascii=False, default=str))
    api_key = _deep_get(redacted, ("llm", "api_key"), "")
    if api_key:
        set_dot_path(redacted, "llm.api_key", "***")
    return redacted


def validate_config_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        from kero.llm.providers import resolve_provider
        provider = str(_deep_get(data, ("llm", "provider"), "") or "")
        if provider and resolve_provider(
            provider,
            user_providers=_deep_get(data, ("providers",), {}),
            custom_providers=_deep_get(data, ("custom_providers",), []),
        ) is None:
            errors.append(f"Unknown llm.provider: {provider}")
    except Exception:
        pass

    numeric_paths = [
        ("llm.temperature", float),
        ("llm.max_tokens", int),
        ("llm.timeout_seconds", float),
        ("memory.short_term_turns", int),
        ("memory.recall_top_k", int),
        ("memory.memory_char_limit", int),
        ("memory.user_char_limit", int),
        ("memory.long_term_char_limit", int),
        ("memory.reflection_interval_turns", int),
        ("memory.reflection_min_turns", int),
    ]
    for key_path, caster in numeric_paths:
        try:
            caster(get_dot_path(data, key_path))
        except (KeyError, TypeError, ValueError):
            errors.append(f"{key_path} must be a {caster.__name__}")
    return errors


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "openrouter"
    model: str = "anthropic/claude-sonnet-4.6"
    api_key: str = ""
    base_url: str = ""
    command: str = ""
    provider_options: dict[str, Any] = field(default_factory=dict)
    providers: dict[str, Any] = field(default_factory=dict)
    custom_providers: list[dict[str, Any]] = field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 1200
    timeout_seconds: float = 120.0
    enabled: bool = True


@dataclass(frozen=True)
class MemoryConfig:
    short_term_turns: int = 8
    recall_top_k: int = 6
    recall_min_score: float = 0.04
    memory_char_limit: int = 5000
    user_char_limit: int = 3000
    long_term_char_limit: int = 120000
    reflection_interval_turns: int = 8
    reflection_min_turns: int = 3


@dataclass(frozen=True)
class KeroConfig:
    home: Path = field(default_factory=get_kero_home)
    llm: LLMConfig = field(default_factory=LLMConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)

    @classmethod
    def load(
        cls,
        config_path: str | Path | None = None,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> "KeroConfig":
        data = load_config_data(config_path=config_path, overrides=overrides)

        home = Path(_deep_get(data, ("home",), get_kero_home()))
        home = home.expanduser().resolve()

        llm = LLMConfig(
            provider=str(_deep_get(data, ("llm", "provider"), "openrouter")),
            model=str(_deep_get(data, ("llm", "model"), "anthropic/claude-sonnet-4.6")),
            api_key=str(_deep_get(data, ("llm", "api_key"), "")),
            base_url=str(_deep_get(data, ("llm", "base_url"), "")),
            command=str(_deep_get(data, ("llm", "command"), "")),
            provider_options=dict(_deep_get(data, ("llm", "provider_options"), {}) or {}),
            providers=dict(_deep_get(data, ("providers",), {}) or {}),
            custom_providers=list(_deep_get(data, ("custom_providers",), []) or []),
            temperature=float(_deep_get(data, ("llm", "temperature"), 0.7)),
            max_tokens=int(_deep_get(data, ("llm", "max_tokens"), 1200)),
            timeout_seconds=float(_deep_get(data, ("llm", "timeout_seconds"), 120.0)),
            enabled=bool(_deep_get(data, ("llm", "enabled"), True)),
        )

        memory = MemoryConfig(
            short_term_turns=int(_deep_get(data, ("memory", "short_term_turns"), 8)),
            recall_top_k=int(_deep_get(data, ("memory", "recall_top_k"), 6)),
            recall_min_score=float(_deep_get(data, ("memory", "recall_min_score"), 0.04)),
            memory_char_limit=int(_deep_get(data, ("memory", "memory_char_limit"), 5000)),
            user_char_limit=int(_deep_get(data, ("memory", "user_char_limit"), 3000)),
            long_term_char_limit=int(_deep_get(data, ("memory", "long_term_char_limit"), 120000)),
            reflection_interval_turns=int(_deep_get(data, ("memory", "reflection_interval_turns"), 8)),
            reflection_min_turns=int(_deep_get(data, ("memory", "reflection_min_turns"), 3)),
        )
        return cls(home=home, llm=llm, memory=memory)
