from __future__ import annotations

import sys

from kero.config import LLMConfig, validate_config_data
from kero.llm.client import LLMClient
from kero.llm.providers import get_provider, resolve_provider


def test_provider_aliases_and_local_profiles() -> None:
    assert get_provider("rk3588").name == "rknn"
    assert get_provider("llmapp.cpp").name == "llmapp"
    assert resolve_provider("ollama").name == "custom"


def test_custom_provider_validation() -> None:
    data = {
        "llm": {
            "provider": "my-local",
            "model": "demo",
            "temperature": 0.7,
            "max_tokens": 1200,
            "timeout_seconds": 120.0,
        },
        "providers": {
            "my-local": {
                "name": "My Local",
                "transport": "local_process",
                "command": sys.executable,
                "model": "demo",
            }
        },
        "custom_providers": [],
        "memory": {
            "short_term_turns": 1,
            "recall_top_k": 1,
            "memory_char_limit": 100,
            "user_char_limit": 100,
            "long_term_char_limit": 100,
            "reflection_interval_turns": 1,
            "reflection_min_turns": 1,
        },
    }

    assert validate_config_data(data) == []


def test_local_process_protocol(tmp_path) -> None:
    script = tmp_path / "fake_llm.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "print(json.dumps({'content': payload['model'] + ': ok'}))\n",
        encoding="utf-8",
    )

    client = LLMClient(
        LLMConfig(
            provider="rknn",
            model="gemma4-e2b",
            command=f"{sys.executable} {script}",
        )
    )

    assert client.is_configured()
    response = client.complete([{"role": "user", "content": "hi"}])
    assert response.provider == "rknn"
    assert response.model == "gemma4-e2b"
    assert response.content == "gemma4-e2b: ok"


def test_chat_completions_uses_requests_with_minimal_payload(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        text = ""
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "local ok"}}]}

    def fake_post(url, *, json, headers, timeout):
        calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr("kero.llm.client.requests.post", fake_post)

    client = LLMClient(
        LLMConfig(
            provider="ollama",
            model="llama3.2",
            base_url="http://127.0.0.1:11434/v1",
            max_tokens=64,
            timeout_seconds=5.0,
        )
    )
    messages = [{"role": "user", "content": "hi"}]

    response = client.complete(messages)

    assert response.provider == "custom"
    assert response.model == "llama3.2"
    assert response.content == "local ok"
    assert calls == [
        {
            "url": "http://127.0.0.1:11434/v1/chat/completions",
            "json": {
                "model": "llama3.2",
                "messages": messages,
                "max_tokens": 64,
            },
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "kero-agent",
            },
            "timeout": 5.0,
        }
    ]


def test_chat_completions_accepts_full_endpoint(monkeypatch) -> None:
    seen_urls = []

    class FakeResponse:
        text = ""
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, *, json, headers, timeout):
        seen_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr("kero.llm.client.requests.post", fake_post)

    client = LLMClient(
        LLMConfig(
            provider="ollama",
            model="local-model",
            base_url="http://127.0.0.1:11434/v1/chat/completions",
        )
    )

    assert client.complete([{"role": "user", "content": "hi"}]).content == "ok"
    assert seen_urls == ["http://127.0.0.1:11434/v1/chat/completions"]


def test_ollama_root_base_url_uses_openai_compatible_v1_endpoint(monkeypatch) -> None:
    seen_urls = []

    class FakeResponse:
        text = ""
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ollama ok"}}]}

    def fake_post(url, *, json, headers, timeout):
        seen_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr("kero.llm.client.requests.post", fake_post)

    client = LLMClient(
        LLMConfig(
            provider="ollama",
            model="qwen3:14b",
            base_url="http://localhost:11434",
        )
    )

    assert client.complete([{"role": "user", "content": "hi"}]).content == "ollama ok"
    assert seen_urls == ["http://localhost:11434/v1/chat/completions"]


def test_local_chat_completions_ignores_env_api_key_header(monkeypatch) -> None:
    seen_headers = []

    class FakeResponse:
        text = ""
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, *, json, headers, timeout):
        seen_headers.append(headers)
        return FakeResponse()

    monkeypatch.setattr("kero.llm.client.requests.post", fake_post)

    client = LLMClient(
        LLMConfig(
            provider="custom",
            model="qwen3:14b",
            api_key="\x1b[6~",
            base_url="http://localhost:11434",
        )
    )

    assert client.complete([{"role": "user", "content": "hi"}]).content == "ok"
    assert "Authorization" not in seen_headers[0]
