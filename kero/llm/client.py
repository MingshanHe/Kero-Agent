from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kero.config import LLMConfig
from kero.llm.providers import ProviderProfile, get_provider


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    used_fallback: bool = False


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config
        self.profile = get_provider(config.provider)

    def is_configured(self) -> bool:
        if not self.config.enabled:
            return False
        profile = self.profile
        if profile is None:
            return False
        if profile.api_mode == "unsupported":
            return False
        if self._is_local(profile):
            return True
        return bool(profile.resolve_api_key(self.config.api_key))

    def complete(self, messages: list[dict[str, str]], *, purpose: str = "chat") -> LLMResponse:
        profile = self.profile
        if profile is None:
            raise LLMError(f"Unknown provider: {self.config.provider}")
        if profile.api_mode == "unsupported":
            raise LLMError(profile.unsupported_reason or f"Provider {profile.name} is unsupported.")
        if not self.config.enabled:
            raise LLMError("LLM is disabled.")
        if profile.api_mode == "anthropic_messages":
            return self._anthropic_complete(profile, messages)
        if profile.api_mode == "chat_completions":
            return self._chat_completions(profile, messages)
        raise LLMError(f"Unsupported api_mode: {profile.api_mode}")

    def _chat_completions(self, profile: ProviderProfile, messages: list[dict[str, str]]) -> LLMResponse:
        api_key = profile.resolve_api_key(self.config.api_key)
        if not api_key and not self._is_local(profile):
            raise LLMError(
                f"No API key found for provider {profile.name}. "
                f"Set one of: {', '.join(profile.env_vars) or 'KERO_API_KEY'}"
            )
        try:
            from openai import OpenAI
        except Exception as exc:
            raise LLMError("The openai package is required for chat_completions providers.") from exc

        base_url = self.config.base_url or profile.base_url
        model = self.config.model or profile.default_model
        client_kwargs: dict[str, Any] = {"base_url": base_url}
        if api_key:
            client_kwargs["api_key"] = api_key
        else:
            client_kwargs["api_key"] = "not-needed"
        if profile.default_headers:
            client_kwargs["default_headers"] = profile.default_headers
        client = OpenAI(**client_kwargs)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "timeout": self.config.timeout_seconds,
        }
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        return LLMResponse(content=content.strip(), provider=profile.name, model=model)

    def _anthropic_complete(self, profile: ProviderProfile, messages: list[dict[str, str]]) -> LLMResponse:
        api_key = profile.resolve_api_key(self.config.api_key)
        if not api_key:
            raise LLMError(
                f"No API key found for provider {profile.name}. "
                f"Set one of: {', '.join(profile.env_vars)}"
            )
        try:
            import anthropic
        except Exception as exc:
            raise LLMError("The anthropic package is required for anthropic_messages providers.") from exc

        system = ""
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "system":
                system = (system + "\n\n" + content).strip()
                continue
            if role not in {"user", "assistant"}:
                role = "user"
            converted.append({"role": role, "content": content})

        client = anthropic.Anthropic(
            api_key=api_key,
            base_url=self.config.base_url or profile.base_url or None,
            timeout=self.config.timeout_seconds,
        )
        response = client.messages.create(
            model=self.config.model or profile.default_model,
            system=system or None,
            messages=converted,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
        )
        parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        return LLMResponse(
            content="\n".join(parts).strip(),
            provider=profile.name,
            model=self.config.model or profile.default_model,
        )

    @staticmethod
    def _is_local(profile: ProviderProfile) -> bool:
        base = (profile.base_url or "").lower()
        return profile.name == "custom" and any(host in base for host in ("localhost", "127.0.0.1", "0.0.0.0"))


class RuleBasedResponder:
    def reply(self, user_input: str, context: Any) -> str:
        profile = getattr(context, "profile", {}) or {}
        name = profile.get("user_name") or "你"
        recalled = getattr(context, "recalled_memories", []) or []
        prefix = "我想起了一点你之前提到过的事。 " if recalled else ""
        text = user_input.strip()
        if any(word in text for word in ("难过", "焦虑", "压力", "烦", "累", "崩溃")):
            return prefix + f"{name}，我在。先别急着把整件事一次扛完，我们可以只看最压着你的那一小块。"
        if any(word in text for word in ("开心", "高兴", "顺利", "喜欢", "期待")):
            return prefix + f"这听起来挺亮的，{name}。我想多听一点，最让你有感觉的是哪部分？"
        if text.endswith(("?", "？")):
            return prefix + "我会陪你一起想。先把你最在意的判断标准说出来，我们就能把问题拆清楚。"
        return prefix + "我在听。你可以继续说，我会把稳定的偏好、重要的人和反复出现的主题慢慢记下来。"
