from __future__ import annotations

import os

from kero.config import (
    KeroConfig,
    get_dot_path,
    load_config_data,
    parse_value,
    save_config_data,
    set_dot_path,
    validate_config_data,
)
from kero.cli.setup import run_setup


def test_home_config_and_env_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KERO_HOME", str(tmp_path))
    save_config_data(
        {
            "llm": {"provider": "custom", "model": "local-a"},
            "memory": {"reflection_interval_turns": 4},
        },
        tmp_path / "config.yaml",
    )
    monkeypatch.setenv("KERO_MODEL", "env-model")

    config = KeroConfig.load()

    assert config.home == tmp_path
    assert config.llm.provider == "custom"
    assert config.llm.model == "env-model"
    assert config.memory.reflection_interval_turns == 4


def test_dot_path_set_get_and_validate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KERO_HOME", str(tmp_path))
    data = load_config_data(include_env=False)
    set_dot_path(data, "llm.provider", parse_value("deepseek"))
    set_dot_path(data, "memory.recall_top_k", parse_value("3"))

    assert get_dot_path(data, "llm.provider") == "deepseek"
    assert get_dot_path(data, "memory.recall_top_k") == 3
    assert validate_config_data(data) == []


def test_noninteractive_setup_writes_config_and_memory_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KERO_HOME", str(tmp_path))
    run_setup(non_interactive=True, print_fn=lambda _line: None)

    assert (tmp_path / "config.yaml").exists()
    assert (tmp_path / "memories" / "MEMORY.md").exists()
    assert (tmp_path / "memories" / "USER.md").exists()
