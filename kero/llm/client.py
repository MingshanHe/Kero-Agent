from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from kero.config import LLMConfig
from kero.llm.providers import ProviderProfile, is_local_provider, resolve_provider


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
        self.profile = resolve_provider(
            config.provider,
            user_providers=config.providers,
            custom_providers=config.custom_providers,
        )

    def is_configured(self) -> bool:
        if not self.config.enabled:
            return False
        profile = self.profile
        if profile is None:
            return False
        if profile.api_mode == "unsupported":
            return False
        if profile.api_mode.startswith("local_"):
            return self._command_available(self._resolve_command(profile))
        if is_local_provider(profile):
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
        if profile.api_mode.startswith("local_"):
            return self._local_process_complete(profile, messages, purpose=purpose)
        if profile.api_mode == "anthropic_messages":
            return self._anthropic_complete(profile, messages)
        if profile.api_mode == "chat_completions":
            return self._chat_completions(profile, messages)
        raise LLMError(f"Unsupported api_mode: {profile.api_mode}")

    def _chat_completions(self, profile: ProviderProfile, messages: list[dict[str, str]]) -> LLMResponse:
        api_key = profile.resolve_api_key(self.config.api_key)
        base_url = profile.resolve_base_url(self.config.base_url)
        local_endpoint = self._is_local_endpoint(base_url)
        if not api_key and not local_endpoint:
            raise LLMError(
                f"No API key found for provider {profile.name}. "
                f"Set one of: {', '.join(profile.env_vars) or 'KERO_API_KEY'}"
            )

        model = self.config.model or profile.default_model

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if self.config.max_tokens:
            payload["max_tokens"] = self.config.max_tokens

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "kero-agent",
        }
        if api_key and not local_endpoint:
            headers["Authorization"] = f"Bearer {api_key}"
        if profile.default_headers:
            headers.update(profile.default_headers)

        endpoint = self._chat_completions_endpoint(base_url, profile=profile)
        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            raise LLMError(f"Provider {profile.name} timed out after {self.config.timeout_seconds}s") from exc
        except requests.RequestException as exc:
            detail = self._response_error_detail(getattr(exc, "response", None))
            suffix = f": {detail}" if detail else ""
            raise LLMError(f"Provider {profile.name} request failed{suffix}") from exc
        except ValueError as exc:
            raise LLMError(f"Provider {profile.name} returned non-JSON response.") from exc

        content = self._extract_chat_content(data)
        return LLMResponse(content=content.strip(), provider=profile.name, model=model)

    @staticmethod
    def _chat_completions_endpoint(base_url: str, *, profile: ProviderProfile | None = None) -> str:
        normalized = (base_url or "").strip().rstrip("/")
        if not normalized:
            raise LLMError("No base_url configured for chat_completions provider.")
        if normalized.endswith("/chat/completions"):
            return normalized
        if LLMClient._is_custom_local_root_url(normalized, profile):
            return normalized + "/v1/chat/completions"
        return normalized + "/chat/completions"

    @staticmethod
    def _is_local_endpoint(base_url: str) -> bool:
        hostname = (urlparse(base_url).hostname or "").lower()
        return hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

    @staticmethod
    def _is_custom_local_root_url(base_url: str, profile: ProviderProfile | None) -> bool:
        if profile is None or not profile.name.startswith("custom"):
            return False
        parsed = urlparse(base_url)
        hostname = (parsed.hostname or "").lower()
        if hostname not in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
            return False
        return parsed.path in {"", "/"}

    @staticmethod
    def _response_error_detail(response: Any) -> str:
        if response is None:
            return ""
        status = getattr(response, "status_code", "")
        text = (getattr(response, "text", "") or "").strip()
        if len(text) > 500:
            text = text[:500] + "..."
        return f"HTTP {status} {text}".strip()

    @staticmethod
    def _extract_chat_content(data: Any) -> str:
        if not isinstance(data, dict):
            raise LLMError("Provider returned an unexpected chat completion response.")
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            message = choice.get("message") if isinstance(choice, dict) else {}
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, dict) and isinstance(item.get("text"), str):
                            parts.append(item["text"])
                    return "\n".join(parts)
            text = choice.get("text") if isinstance(choice, dict) else None
            if isinstance(text, str):
                return text
        message = data.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(data.get("response"), str):
            return data["response"]
        raise LLMError("Provider returned no chat completion content.")

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
            base_url=profile.resolve_base_url(self.config.base_url) or None,
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

    def _local_process_complete(
        self,
        profile: ProviderProfile,
        messages: list[dict[str, str]],
        *,
        purpose: str,
    ) -> LLMResponse:
        command = self._resolve_command(profile)
        if not command:
            raise LLMError(
                f"Local provider {profile.name} needs a command. "
                "Set llm.command, llm.provider_options.command, or one of: "
                f"{', '.join(profile.command_env_vars) or 'KERO_LLM_COMMAND'}"
            )

        model = self.config.model or profile.default_model
        payload = {
            "provider": profile.name,
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "purpose": purpose,
            "options": self.config.provider_options,
        }
        try:
            completed = subprocess.run(
                shlex.split(command),
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.config.timeout_seconds,
                check=True,
            )
        except FileNotFoundError as exc:
            raise LLMError(f"Local provider command not found: {command}") from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"Local provider {profile.name} timed out after {self.config.timeout_seconds}s") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            detail = f": {stderr}" if stderr else ""
            raise LLMError(f"Local provider {profile.name} failed{detail}") from exc

        output = (completed.stdout or "").strip()
        if not output:
            raise LLMError(f"Local provider {profile.name} returned no content.")
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            content = output
        else:
            content = str(data.get("content") or data.get("text") or data.get("response") or "").strip()
        return LLMResponse(content=content, provider=profile.name, model=model)

    def _resolve_command(self, profile: ProviderProfile) -> str:
        explicit = self.config.command or str(self.config.provider_options.get("command") or "")
        if explicit:
            return explicit
        return profile.resolve_command()

    @staticmethod
    def _command_available(command: str) -> bool:
        if not command:
            return False
        try:
            executable = shlex.split(command)[0]
        except ValueError:
            return False
        return bool(shutil.which(executable))


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
