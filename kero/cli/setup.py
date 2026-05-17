from __future__ import annotations

from argparse import Namespace
from getpass import getpass
from typing import Callable
import webbrowser

from kero.config import get_home_config_path, get_home_env_path, load_config_data, save_config_data, write_env_value
from kero.llm.providers import ProviderProfile, get_provider, list_providers


InputFn = Callable[[str], str]
PrintFn = Callable[[str], None]


def add_setup_parser(subparsers) -> None:
    parser = subparsers.add_parser("setup", help="Run the interactive Kero setup wizard")
    parser.add_argument("--non-interactive", action="store_true", help="Write defaults without prompting")
    parser.add_argument("--only-copilot", action="store_true", help="Configure Copilot only, skipping other providers")
    parser.set_defaults(func=run_setup_command)


def run_setup_command(args: Namespace) -> None:
    run_setup(
        non_interactive=bool(getattr(args, "non_interactive", False)),
        only_copilot=bool(getattr(args, "only_copilot", False)),
    )


def run_setup(
    *,
    non_interactive: bool = False,
    input_fn: InputFn = input,
    print_fn: PrintFn = print,
    only_copilot: bool = False,
) -> None:
    data = load_config_data(include_env=False)
    provider = str(data.get("llm", {}).get("provider") or "openrouter")
    profile = get_provider(provider) or get_provider("openrouter")

    print_fn("")
    print_fn("Kero setup")
    print_fn("----------")

    if only_copilot:
        only_profile = get_provider("copilot")
        if only_profile is not None:
            profile = only_profile
            provider = profile.name
            print_fn("")
            print_fn("Copilot selected")
            model = data.get("llm", {}).get("model") or profile.default_model
            base_url = profile.base_url
            temp = str(data.get("llm", {}).get("temperature", 0.7))
            max_tokens = str(data.get("llm", {}).get("max_tokens", 1200))
            reflection = str(data.get("memory", {}).get("reflection_interval_turns", 8))
            memory_limit = str(data.get("memory", {}).get("memory_char_limit", 5000))
            user_limit = str(data.get("memory", {}).get("user_char_limit", 3000))
        else:
            print_fn("Copilot provider is not available. Falling back to interactive setup.")
            profile = _choose_provider(profile, input_fn, print_fn)
            provider = profile.name
            model_default = data.get("llm", {}).get("model") or profile.default_model
            model = _prompt(input_fn, f"Model [{model_default}]", model_default)
            base_default = data.get("llm", {}).get("base_url") or profile.base_url
            base_url = _prompt(input_fn, f"Base URL [{base_default or 'provider default'}]", base_default)
            temp = _prompt(input_fn, f"Temperature [{data.get('llm', {}).get('temperature', 0.7)}]", str(data.get("llm", {}).get("temperature", 0.7)))
            max_tokens = _prompt(input_fn, f"Max tokens [{data.get('llm', {}).get('max_tokens', 1200)}]", str(data.get("llm", {}).get("max_tokens", 1200)))
            reflection = _prompt(
                input_fn,
                f"Reflection interval turns [{data.get('memory', {}).get('reflection_interval_turns', 8)}]",
                str(data.get("memory", {}).get("reflection_interval_turns", 8)),
            )
            memory_limit = _prompt(
                input_fn,
                f"MEMORY.md char limit [{data.get('memory', {}).get('memory_char_limit', 5000)}]",
                str(data.get("memory", {}).get("memory_char_limit", 5000)),
            )
            user_limit = _prompt(
                input_fn,
                f"USER.md char limit [{data.get('memory', {}).get('user_char_limit', 3000)}]",
                str(data.get("memory", {}).get("user_char_limit", 3000)),
            )
    elif not non_interactive:
        profile = _choose_provider(profile, input_fn, print_fn)
        provider = profile.name
        model_default = data.get("llm", {}).get("model") or profile.default_model
        model = _prompt(input_fn, f"Model [{model_default}]", model_default)
        base_default = profile.base_url if profile.name == "copilot" else data.get("llm", {}).get("base_url") or profile.base_url
        base_url = _prompt(input_fn, f"Base URL [{base_default or 'provider default'}]", base_default)
        temp = _prompt(input_fn, f"Temperature [{data.get('llm', {}).get('temperature', 0.7)}]", str(data.get("llm", {}).get("temperature", 0.7)))
        max_tokens = _prompt(input_fn, f"Max tokens [{data.get('llm', {}).get('max_tokens', 1200)}]", str(data.get("llm", {}).get("max_tokens", 1200)))
        reflection = _prompt(
            input_fn,
            f"Reflection interval turns [{data.get('memory', {}).get('reflection_interval_turns', 8)}]",
            str(data.get("memory", {}).get("reflection_interval_turns", 8)),
        )
        memory_limit = _prompt(
            input_fn,
            f"MEMORY.md char limit [{data.get('memory', {}).get('memory_char_limit', 5000)}]",
            str(data.get("memory", {}).get("memory_char_limit", 5000)),
        )
        user_limit = _prompt(
            input_fn,
            f"USER.md char limit [{data.get('memory', {}).get('user_char_limit', 3000)}]",
            str(data.get("memory", {}).get("user_char_limit", 3000)),
        )
    else:
        model = data.get("llm", {}).get("model") or (profile.default_model if profile else "anthropic/claude-sonnet-4.6")
        base_url = data.get("llm", {}).get("base_url") or (profile.base_url if profile else "")
        temp = str(data.get("llm", {}).get("temperature", 0.7))
        max_tokens = str(data.get("llm", {}).get("max_tokens", 1200))
        reflection = str(data.get("memory", {}).get("reflection_interval_turns", 8))
        memory_limit = str(data.get("memory", {}).get("memory_char_limit", 5000))
        user_limit = str(data.get("memory", {}).get("user_char_limit", 3000))

    data.setdefault("llm", {})
    data.setdefault("memory", {})
    data["llm"].update(
        {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "temperature": float(temp),
            "max_tokens": int(max_tokens),
            "enabled": True,
        }
    )
    data["memory"].update(
        {
            "memory_char_limit": int(memory_limit),
            "user_char_limit": int(user_limit),
            "reflection_interval_turns": int(reflection),
        }
    )

    config_path = save_config_data(data, get_home_config_path())
    print_fn(f"Config saved: {config_path}")

    if not non_interactive and profile is not None and profile.env_vars:
        auth_type = getattr(profile, "auth_type", "api_key")
        # Device code flow (one-click/open + auto-poll like Hermes)
        if auth_type == "oauth_device_code":
            print_fn("")
            print_fn(f"{profile.name} selected — starting device authorization flow.")
            try:
                from kero.llm.copilot_auth import copilot_device_code_login

                token = copilot_device_code_login()
            except Exception:
                token = None

            if token:
                env_path = write_env_value(profile.env_vars[0], token, get_home_env_path())
                print_fn(f"Token saved to: {env_path}")
            else:
                print_fn("No token obtained; you can paste a token manually later.")
        else:
            api_key = _secret_prompt(f"API key for {profile.name} (blank to skip): ")
            if api_key:
                env_path = write_env_value(profile.env_vars[0], api_key, get_home_env_path())
                print_fn(f"API key saved to: {env_path}")
    elif non_interactive:
        env_path = get_home_env_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.touch(exist_ok=True)

    from kero.config import KeroConfig
    from kero.memory import MemoryManager

    MemoryManager(KeroConfig.load())
    print_fn("Setup complete. Run `python -m kero` to start chatting.")


def _choose_provider(current: ProviderProfile | None, input_fn: InputFn, print_fn: PrintFn) -> ProviderProfile:
    providers = [provider for provider in list_providers() if provider.api_mode != "unsupported"]
    default_idx = 0
    for idx, provider in enumerate(providers):
        if current and provider.name == current.name:
            default_idx = idx
            break
    print_fn("")
    print_fn("Providers:")
    for idx, provider in enumerate(providers, start=1):
        marker = "*" if idx - 1 == default_idx else " "
        print_fn(f"  {marker} {idx}. {provider.name} ({provider.default_model or provider.api_mode})")
    answer = input_fn(f"Choose provider [{providers[default_idx].name}]: ").strip()
    if not answer:
        return providers[default_idx]
    if answer.isdigit():
        selected = max(1, min(len(providers), int(answer))) - 1
        return providers[selected]
    profile = get_provider(answer)
    if profile is None or profile.api_mode == "unsupported":
        print_fn(f"Unknown or unsupported provider '{answer}', keeping {providers[default_idx].name}.")
        return providers[default_idx]
    return profile


def _prompt(input_fn: InputFn, label: str, default: str) -> str:
    value = input_fn(f"{label}: ").strip()
    return value or default


def _secret_prompt(label: str) -> str:
    try:
        return getpass(label).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""
