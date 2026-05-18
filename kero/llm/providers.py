from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


OMIT_TEMPERATURE = object()


@dataclass
class ProviderProfile:
    """Declarative LLM provider profile.

    Kero keeps provider identity, auth, endpoint defaults, and local backend
    wiring in one registry. Callers select by provider name; base_url is only
    an endpoint override.
    """

    name: str
    api_mode: str = "chat_completions"
    aliases: tuple[str, ...] = ()
    display_name: str = ""
    description: str = ""
    signup_url: str = ""
    env_vars: tuple[str, ...] = ()
    base_url: str = ""
    models_url: str = ""
    base_url_env_var: str = ""
    auth_type: str = "api_key"
    auth_url: str = ""
    supports_health_check: bool = True
    fallback_models: tuple[str, ...] = ()
    default_model: str = ""
    default_aux_model: str = ""
    default_headers: dict[str, str] = field(default_factory=dict)
    fixed_temperature: Any = None
    default_max_tokens: int | None = None
    command_env_vars: tuple[str, ...] = ()
    default_command: str = ""
    unsupported_reason: str = ""

    def resolve_api_key(self, explicit: str = "") -> str:
        if explicit:
            return explicit
        for name in self.env_vars:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return ""

    def resolve_base_url(self, explicit: str = "") -> str:
        if explicit:
            return explicit
        if self.base_url_env_var:
            value = os.environ.get(self.base_url_env_var, "").strip()
            if value:
                return value
        return self.base_url

    def resolve_command(self, explicit: str = "") -> str:
        if explicit:
            return explicit
        for name in self.command_env_vars:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return self.default_command

    def get_hostname(self) -> str:
        if not self.base_url:
            return ""
        return urlparse(self.base_url).hostname or ""

    def build_extra_body(self, **context: Any) -> dict[str, Any]:
        return {}

    def build_api_kwargs_extras(self, **context: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        return {}, {}

    def fetch_models(self, *, api_key: str | None = None, timeout: float = 8.0) -> list[str] | None:
        url = (self.models_url or "").strip()
        if not url and self.base_url:
            url = self.base_url.rstrip("/") + "/models"
        if not url or not self.supports_health_check:
            return None

        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "kero-agent")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        for key, value in self.default_headers.items():
            req.add_header(key, value)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            items = data if isinstance(data, list) else data.get("data", [])
            return [str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")]
        except Exception as exc:
            logger.debug("fetch_models(%s): %s", self.name, exc)
            return None


class CustomLocalProfile(ProviderProfile):
    def build_api_kwargs_extras(self, **context: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        extra_body: dict[str, Any] = {}
        num_ctx = context.get("ollama_num_ctx")
        if num_ctx:
            extra_body["options"] = {"num_ctx": num_ctx}
        if context.get("think") is False:
            extra_body["think"] = False
        return extra_body, {}


PROVIDERS: dict[str, ProviderProfile] = {}
ALIASES: dict[str, str] = {}


def normalize_provider(name: str) -> str:
    key = (name or "").strip().lower()
    return ALIASES.get(key, key)


def register(profile: ProviderProfile) -> None:
    canonical = profile.name.strip().lower()
    profile.name = canonical
    PROVIDERS[canonical] = profile
    for alias in profile.aliases:
        ALIASES[alias.strip().lower()] = canonical


def get_provider(name: str) -> ProviderProfile | None:
    return PROVIDERS.get(normalize_provider(name))


def list_providers() -> list[ProviderProfile]:
    return sorted(PROVIDERS.values(), key=lambda item: item.name)


def resolve_user_provider(name: str, user_providers: dict[str, Any] | None = None) -> ProviderProfile | None:
    if not isinstance(user_providers, dict):
        return None
    requested = (name or "").strip().lower()
    entry = user_providers.get(requested)
    if entry is None:
        for key, value in user_providers.items():
            if str(key).strip().lower() == requested:
                entry = value
                break
    if not isinstance(entry, dict):
        return None

    transport = str(entry.get("transport") or entry.get("api_mode") or "chat_completions")
    api_mode = {
        "openai_chat": "chat_completions",
        "anthropic": "anthropic_messages",
        "anthropic_messages": "anthropic_messages",
        "local_process": "local_process",
        "command": "local_process",
    }.get(transport, transport)
    env_var = str(entry.get("key_env") or entry.get("api_key_env") or "").strip()
    env_vars = (env_var,) if env_var else ()
    command_env = str(entry.get("command_env") or "").strip()
    command_env_vars = (command_env,) if command_env else ()

    return ProviderProfile(
        name=requested,
        api_mode=api_mode,
        display_name=str(entry.get("name") or requested),
        description=str(entry.get("description") or "User configured provider"),
        env_vars=env_vars,
        base_url=str(entry.get("base_url") or entry.get("api") or entry.get("url") or ""),
        base_url_env_var=str(entry.get("base_url_env") or ""),
        auth_type=str(entry.get("auth_type") or "api_key"),
        default_model=str(entry.get("model") or entry.get("default_model") or ""),
        default_command=str(entry.get("command") or ""),
        command_env_vars=command_env_vars,
    )


def _custom_provider_slug(display_name: str) -> str:
    return "custom:" + display_name.strip().lower().replace(" ", "-")


def resolve_custom_provider(
    name: str,
    custom_providers: list[dict[str, Any]] | None = None,
) -> ProviderProfile | None:
    if not isinstance(custom_providers, list):
        return None
    requested = (name or "").strip().lower()
    if not requested:
        return None

    first_valid: ProviderProfile | None = None
    for entry in custom_providers:
        if not isinstance(entry, dict):
            continue
        display_name = str(entry.get("name") or "").strip()
        base_url = str(entry.get("base_url") or entry.get("api") or entry.get("url") or "").strip()
        command = str(entry.get("command") or "").strip()
        if not display_name or not (base_url or command):
            continue
        slug = _custom_provider_slug(display_name)
        env_vars = entry.get("env_vars") or ()
        if isinstance(env_vars, str):
            env_vars = (env_vars,)
        profile = ProviderProfile(
            name=slug,
            api_mode="local_process" if command and not base_url else "chat_completions",
            display_name=display_name,
            description="Custom provider",
            env_vars=tuple(str(item) for item in env_vars),
            base_url=base_url,
            auth_type=str(entry.get("auth_type") or "api_key"),
            default_model=str(entry.get("model") or entry.get("default_model") or "custom-model"),
            default_command=command,
        )
        first_valid = first_valid or profile
        if requested in {display_name.lower(), slug, "custom"}:
            return profile
    return first_valid if requested == "custom" else None


def resolve_provider(
    name: str,
    *,
    user_providers: dict[str, Any] | None = None,
    custom_providers: list[dict[str, Any]] | None = None,
) -> ProviderProfile | None:
    canonical = normalize_provider(name)
    return (
        get_provider(canonical)
        or resolve_user_provider(canonical, user_providers)
        or resolve_user_provider(name, user_providers)
        or resolve_custom_provider(name, custom_providers)
    )


def is_local_provider(profile: ProviderProfile | None) -> bool:
    if profile is None:
        return False
    if profile.api_mode.startswith("local_"):
        return True
    base_url = profile.resolve_base_url("").lower()
    return profile.name == "custom" and any(host in base_url for host in ("localhost", "127.0.0.1", "0.0.0.0"))


register(
    ProviderProfile(
        name="openai",
        aliases=("oa",),
        display_name="OpenAI",
        env_vars=("OPENAI_API_KEY",),
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        fallback_models=("gpt-4o-mini", "gpt-4.1", "gpt-5"),
    )
)
register(
    ProviderProfile(
        name="openrouter",
        aliases=("or",),
        display_name="OpenRouter",
        description="OpenAI-compatible multi-model router",
        env_vars=("OPENROUTER_API_KEY", "OPENAI_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        models_url="https://openrouter.ai/api/v1/models",
        base_url_env_var="OPENROUTER_BASE_URL",
        default_model="anthropic/claude-sonnet-4.6",
        fallback_models=(
            "anthropic/claude-sonnet-4.6",
            "openai/gpt-5.4",
            "deepseek/deepseek-chat",
            "qwen/qwen3-plus",
        ),
        default_headers={
            "HTTP-Referer": "https://github.com/kero-agent",
            "X-Title": "Kero Agent",
        },
    )
)
register(
    ProviderProfile(
        name="anthropic",
        aliases=("claude",),
        api_mode="anthropic_messages",
        display_name="Anthropic",
        env_vars=("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN"),
        base_url="https://api.anthropic.com",
        default_model="claude-sonnet-4-6",
    )
)
register(
    CustomLocalProfile(
        name="custom",
        aliases=("local", "ollama", "vllm", "llamacpp", "llama.cpp", "llama-cpp", "lmstudio"),
        display_name="Custom OpenAI-compatible endpoint",
        env_vars=("KERO_API_KEY", "OPENAI_API_KEY"),
        base_url="http://127.0.0.1:1234/v1",
        base_url_env_var="KERO_BASE_URL",
        default_model="local-model",
    )
)
register(
    ProviderProfile(
        name="rknn",
        aliases=("rk3588", "rknn-llm", "gemma4-e2b-rknn"),
        api_mode="local_process",
        display_name="RKNN local inference",
        description="Local RK3588/RKNN backend using Kero's JSON command protocol",
        auth_type="none",
        supports_health_check=False,
        default_model="gemma4-e2b",
        command_env_vars=("KERO_RKNN_COMMAND", "RKNN_LLM_COMMAND"),
    )
)
register(
    ProviderProfile(
        name="llmapp",
        aliases=("llmapp.cpp", "llmapp-cpp"),
        api_mode="local_process",
        display_name="llmapp.cpp local inference",
        description="Local llmapp.cpp backend using Kero's JSON command protocol",
        auth_type="none",
        supports_health_check=False,
        default_model="gemma4-e2b",
        command_env_vars=("KERO_LLMAPP_COMMAND", "LLMAPP_COMMAND"),
        default_command="llmapp",
    )
)
register(
    ProviderProfile(
        name="deepseek",
        aliases=("deepseek-chat",),
        env_vars=("DEEPSEEK_API_KEY",),
        base_url="https://api.deepseek.com/v1",
        base_url_env_var="DEEPSEEK_BASE_URL",
        default_model="deepseek-chat",
    )
)
register(
    ProviderProfile(
        name="kimi",
        aliases=("moonshot", "kimi-coding"),
        env_vars=("KIMI_API_KEY", "MOONSHOT_API_KEY"),
        base_url="https://api.moonshot.ai/v1",
        base_url_env_var="KIMI_BASE_URL",
        default_model="kimi-k2-turbo-preview",
        fixed_temperature=OMIT_TEMPERATURE,
    )
)
register(
    ProviderProfile(
        name="kimi-cn",
        aliases=("moonshot-cn",),
        env_vars=("KIMI_CN_API_KEY",),
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2-turbo-preview",
        fixed_temperature=OMIT_TEMPERATURE,
    )
)
register(
    ProviderProfile(
        name="zai",
        aliases=("glm", "z-ai", "z.ai", "zhipu"),
        env_vars=("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
        base_url="https://api.z.ai/api/paas/v4",
        base_url_env_var="GLM_BASE_URL",
        default_model="glm-4.5",
    )
)
register(
    ProviderProfile(
        name="qwen",
        aliases=("alibaba", "dashscope", "aliyun"),
        env_vars=("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        base_url_env_var="DASHSCOPE_BASE_URL",
        default_model="qwen3-coder-plus",
    )
)
register(
    ProviderProfile(
        name="nvidia",
        aliases=("nvidia-nim", "nim"),
        env_vars=("NVIDIA_API_KEY",),
        base_url="https://integrate.api.nvidia.com/v1",
        base_url_env_var="NVIDIA_BASE_URL",
        default_model="nvidia/llama-3.3-70b-instruct",
    )
)
register(
    ProviderProfile(
        name="nous-api",
        aliases=("nous", "nousresearch"),
        env_vars=("NOUS_API_KEY",),
        base_url="https://inference.nousresearch.com/v1",
        default_model="hermes-3-70b",
    )
)
register(
    ProviderProfile(
        name="ai-gateway",
        aliases=("vercel", "vercel-ai-gateway"),
        env_vars=("AI_GATEWAY_API_KEY",),
        base_url="https://ai-gateway.vercel.sh/v1",
        default_model="google/gemini-3-flash",
    )
)
register(
    ProviderProfile(
        name="huggingface",
        aliases=("hf", "hugging-face"),
        env_vars=("HF_TOKEN", "HUGGINGFACE_API_KEY"),
        base_url="https://router.huggingface.co/v1",
        base_url_env_var="HF_BASE_URL",
        default_model="meta-llama/Llama-3.1-8B-Instruct",
    )
)
register(
    ProviderProfile(
        name="novita",
        env_vars=("NOVITA_API_KEY",),
        base_url="https://api.novita.ai/openai/v1",
        base_url_env_var="NOVITA_BASE_URL",
        default_model="deepseek/deepseek-v3-0324",
    )
)
register(
    ProviderProfile(
        name="xiaomi",
        aliases=("mimo",),
        env_vars=("XIAOMI_API_KEY",),
        base_url="https://api.xiaomimimo.com/v1",
        base_url_env_var="XIAOMI_BASE_URL",
        default_model="mimo-v2.5-pro",
    )
)
register(
    ProviderProfile(
        name="arcee",
        aliases=("arcee-ai", "arceeai"),
        env_vars=("ARCEEAI_API_KEY", "ARCEE_API_KEY"),
        base_url="https://conductor.arcee.ai/v1",
        base_url_env_var="ARCEE_BASE_URL",
        default_model="auto",
    )
)
register(
    ProviderProfile(
        name="minimax",
        aliases=("mini-max",),
        api_mode="anthropic_messages",
        env_vars=("MINIMAX_API_KEY",),
        base_url="https://api.minimax.io/anthropic",
        base_url_env_var="MINIMAX_BASE_URL",
        default_model="MiniMax-M2.7",
    )
)
register(
    ProviderProfile(
        name="copilot",
        aliases=("github-copilot", "github"),
        env_vars=("COPILOT_API_TOKEN", "COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
        base_url="https://api.githubcopilot.com",
        default_model="gpt-4.1",
        auth_type="oauth_device_code",
        default_headers={
            "Editor-Version": "vscode/1.104.1",
            "User-Agent": "KeroAgent/1.0",
            "Copilot-Integration-Id": "vscode-chat",
            "Openai-Intent": "conversation-edits",
            "x-initiator": "agent",
        },
        auth_url="https://github.com/login/device",
    )
)
register(
    ProviderProfile(
        name="openai-codex",
        aliases=("codex",),
        api_mode="unsupported",
        default_model="gpt-5",
        unsupported_reason="OpenAI Codex OAuth runtime is intentionally not copied into Kero.",
    )
)
register(
    ProviderProfile(
        name="bedrock",
        aliases=("aws", "aws-bedrock"),
        api_mode="unsupported",
        unsupported_reason="AWS Bedrock requires SDK auth and is outside Kero's first CLI scope.",
    )
)
