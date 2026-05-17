from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    api_mode: str = "chat_completions"
    aliases: tuple[str, ...] = ()
    env_vars: tuple[str, ...] = ()
    base_url: str = ""
    default_model: str = ""
    auth_type: str = "api_key"
    auth_url: str = ""
    default_headers: dict[str, str] = field(default_factory=dict)
    unsupported_reason: str = ""

    def resolve_api_key(self, explicit: str = "") -> str:
        if explicit:
            return explicit
        for name in self.env_vars:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return ""


PROVIDERS: dict[str, ProviderProfile] = {}
ALIASES: dict[str, str] = {}


def register(profile: ProviderProfile) -> None:
    PROVIDERS[profile.name] = profile
    for alias in profile.aliases:
        ALIASES[alias] = profile.name


def get_provider(name: str) -> ProviderProfile | None:
    normalized = (name or "").strip().lower()
    return PROVIDERS.get(ALIASES.get(normalized, normalized))


def list_providers() -> list[ProviderProfile]:
    return sorted(PROVIDERS.values(), key=lambda item: item.name)


register(
    ProviderProfile(
        name="openai",
        aliases=("oa",),
        env_vars=("OPENAI_API_KEY",),
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
    )
)
register(
    ProviderProfile(
        name="openrouter",
        aliases=("or",),
        env_vars=("OPENROUTER_API_KEY", "OPENAI_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        default_model="anthropic/claude-sonnet-4.6",
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
        env_vars=("ANTHROPIC_API_KEY",),
        base_url="https://api.anthropic.com",
        default_model="claude-sonnet-4-6",
    )
)
register(
    ProviderProfile(
        name="custom",
        aliases=("local", "ollama", "vllm", "llamacpp", "llama.cpp", "lmstudio"),
        env_vars=("KERO_API_KEY", "OPENAI_API_KEY"),
        base_url="http://127.0.0.1:1234/v1",
        default_model="local-model",
    )
)
register(
    ProviderProfile(
        name="deepseek",
        aliases=("deepseek-chat",),
        env_vars=("DEEPSEEK_API_KEY",),
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
    )
)
register(
    ProviderProfile(
        name="kimi",
        aliases=("moonshot", "kimi-coding"),
        env_vars=("KIMI_API_KEY", "MOONSHOT_API_KEY"),
        base_url="https://api.moonshot.ai/v1",
        default_model="kimi-k2-turbo-preview",
    )
)
register(
    ProviderProfile(
        name="kimi-cn",
        aliases=("moonshot-cn",),
        env_vars=("KIMI_CN_API_KEY",),
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2-turbo-preview",
    )
)
register(
    ProviderProfile(
        name="zai",
        aliases=("glm", "z-ai", "z.ai", "zhipu"),
        env_vars=("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
        base_url="https://api.z.ai/api/paas/v4",
        default_model="glm-4.5",
    )
)
register(
    ProviderProfile(
        name="qwen",
        aliases=("qwen-oauth", "qwen-portal"),
        env_vars=("QWEN_API_KEY",),
        base_url="https://portal.qwen.ai/v1",
        default_model="qwen3-coder-plus",
    )
)
register(
    ProviderProfile(
        name="nvidia",
        aliases=("nvidia-nim",),
        env_vars=("NVIDIA_API_KEY",),
        base_url="https://integrate.api.nvidia.com/v1",
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
        aliases=("hf",),
        env_vars=("HF_TOKEN", "HUGGINGFACE_API_KEY"),
        base_url="https://router.huggingface.co/v1",
        default_model="meta-llama/Llama-3.1-8B-Instruct",
    )
)
register(
    ProviderProfile(
        name="novita",
        env_vars=("NOVITA_API_KEY",),
        base_url="https://api.novita.ai/openai/v1",
        default_model="deepseek/deepseek-v3-0324",
    )
)
register(
    ProviderProfile(
        name="xiaomi",
        aliases=("mimo",),
        env_vars=("XIAOMI_API_KEY",),
        base_url="https://api.xiaomimimo.com/v1",
        default_model="mimo-v2.5-pro",
    )
)
register(
    ProviderProfile(
        name="arcee",
        aliases=("arcee-ai",),
        env_vars=("ARCEEAI_API_KEY",),
        base_url="https://conductor.arcee.ai/v1",
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
        default_model="MiniMax-M2.7",
    )
)

# GitHub Copilot provider for Kero.
# Uses a GitHub token (`gho_*`, `github_pat_*`, or `ghu_*`) against the
# Copilot API at api.githubcopilot.com and adds the required Copilot headers.
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
        api_mode="unsupported",
        unsupported_reason="AWS Bedrock requires SDK auth and is outside Kero's first CLI scope.",
    )
)
