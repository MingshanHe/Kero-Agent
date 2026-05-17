from __future__ import annotations

from kero.config import KeroConfig, MemoryConfig
from kero.evolution import ReflectionEngine
from kero.llm import LLMClient
from kero.memory import MemoryManager


def test_rule_reflection_updates_profile(tmp_path) -> None:
    config = KeroConfig(
        home=tmp_path,
        memory=MemoryConfig(reflection_interval_turns=2, reflection_min_turns=1),
    )
    memory = MemoryManager(config)
    llm = LLMClient(config.llm)
    engine = ReflectionEngine(config, memory, llm)

    memory.record_turn("我叫小林，请记住我喜欢安静的提醒。", "我记住了。")
    result = engine.reflect(trigger="manual")

    assert result is not None
    assert result.used_fallback is True
    profile = memory.profile_store.snapshot()
    assert profile["user_name"] == "小林"
    assert any("安静" in item for item in profile["preferences"])
