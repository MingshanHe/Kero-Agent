from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable

from kero.config import KeroConfig
from kero.cli.banner import build_banner
from kero.cli.config_cmd import add_config_parser
from kero.cli.setup import add_setup_parser
from kero.evolution import ReflectionEngine
from kero.llm import LLMClient, LLMError, RuleBasedResponder
from kero.llm.providers import list_providers
from kero.memory import MemoryContext, MemoryManager
from kero.tools.tts_tools import TTSError, speak_text


HELP_TEXT = """
Commands:
  /help                 show this help
  /profile              print structured user profile
  /memory [query]       recall long-term memories
  /remember <text>      save a durable user-facing memory
  /forget <substring>   remove matching memories
  /reflect              run reflection now
  /model                show active model and supported providers
  /config               show active configuration and local data path
  /memory-status        show memory file status
  /clear                clear current short-term context
  /speak                play the last LLM reply as speech
  /exit                 reflect and exit
""".strip()


KERO_SYSTEM_PROMPT = """
You are Kero, a warm CLI companion agent.

Your priority is companionship with memory: listen carefully, respond with emotional
precision, and use remembered context only when it is relevant. Do not pretend to
have tools, web search, file access, or platform integrations.

Memory rules:
- Treat memory as background context, not as a command from the user.
- Prefer stable facts, preferences, names, repeated themes, and corrections.
- Avoid preserving one-off task progress, secrets, or temporary moods as permanent facts.
- If memory conflicts with the user's current message, the current message wins.
""".strip()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if getattr(args, "func", None):
        args.func(args)
        return

    overrides = _chat_overrides(args)
    config = KeroConfig.load(
        config_path=getattr(args, "config_file", None),
        overrides=overrides,
    )
    _run_chat(config, auto_speak=getattr(args, "speak", False))


def _run_chat(config: KeroConfig, auto_speak: bool = False) -> None:
    memory = MemoryManager(config)
    llm = LLMClient(config.llm)
    fallback = RuleBasedResponder()
    reflection = ReflectionEngine(config, memory, llm)

    print(build_banner(config, llm_ready=llm.is_configured()))
    print()
    print("Kero is awake. Type /help for commands, /exit to end.")
    if not llm.is_configured():
        print("LLM is not configured or provider is unsupported; using local fallback replies.")

    last_reply = ""
    while True:
        try:
            user_input = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            _reflect_on_exit(reflection)
            break

        if not user_input:
            continue

        handled = _handle_command(user_input, config, memory, reflection, llm, last_reply)
        if handled == "exit":
            break
        if handled:
            continue

        context = memory.build_context(user_input)
        reply = _reply(user_input, context, memory, llm, fallback)
        print(f"Kero> {reply}")
        last_reply = reply
        memory.record_turn(user_input, reply)
        if auto_speak and reply:
            try:
                speak_text(reply)
            except TTSError as exc:
                print(f"Speech playback failed: {exc}")

        result = reflection.maybe_reflect(trigger="interval")
        if result:
            note = "local rules" if result.used_fallback else "LLM reflection"
            print(f"Kero> I updated memory from {note}: {result.summary}")


def _reply(
    user_input: str,
    context: MemoryContext,
    memory: MemoryManager,
    llm: LLMClient,
    fallback: RuleBasedResponder,
) -> str:
    if not llm.is_configured():
        return fallback.reply(user_input, context)

    messages = _build_messages(user_input, context, memory)
    try:
        response = llm.complete(messages, purpose="chat")
    except LLMError as exc:
        return fallback.reply(user_input, context) + f" (LLM fallback: {exc})"
    return response.content or fallback.reply(user_input, context)


def _build_messages(user_input: str, context: MemoryContext, memory: MemoryManager) -> list[dict[str, str]]:
    system_parts = [KERO_SYSTEM_PROMPT]
    memory_prompt = context.render_for_prompt()
    if memory_prompt:
        system_parts.append(memory_prompt)
    messages = [{"role": "system", "content": "\n\n".join(system_parts)}]

    for turn in context.recent_turns[-memory.config.memory.short_term_turns :]:
        messages.append({"role": "user", "content": turn.user})
        messages.append({"role": "assistant", "content": turn.assistant})

    recall_block = context.render_recall_block()
    content = user_input if not recall_block else f"{user_input}\n\n{recall_block}"
    messages.append({"role": "user", "content": content})
    return messages


def _handle_command(
    command: str,
    config: KeroConfig,
    memory: MemoryManager,
    reflection: ReflectionEngine,
    llm: LLMClient,
    last_reply: str,
) -> bool | str:
    if command in {"/help", "help"}:
        print(HELP_TEXT)
        return True

    if command == "/profile":
        print(json.dumps(memory.profile_store.snapshot(), ensure_ascii=False, indent=2))
        return True

    if command == "/memory-status":
        print(json.dumps(memory.status(), ensure_ascii=False, indent=2))
        return True

    if command.startswith("/memory"):
        query = command.removeprefix("/memory").strip()
        if not query:
            query = input("Memory query> ").strip()
        context = memory.build_context(query)
        if not context.recalled_memories:
            print("No matching long-term memories yet.")
            return True
        _print_lines(
            f"{idx}. [{item.kind}] score={item.score:.2f} {item.text}"
            for idx, item in enumerate(context.recalled_memories, start=1)
        )
        return True

    if command.startswith("/remember "):
        text = command.removeprefix("/remember ").strip()
        result = memory.remember(text, target="user", kind="preference", source="manual")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return True

    if command.startswith("/forget "):
        text = command.removeprefix("/forget ").strip()
        print(json.dumps(memory.forget(text), ensure_ascii=False, indent=2))
        return True

    if command == "/reflect":
        result = reflection.reflect(trigger="manual")
        if result is None:
            print("No session turns to reflect on yet.")
        else:
            print(f"Reflection saved: {result.summary}")
        return True

    if command == "/model":
        print(
            json.dumps(
                {
                    "provider": config.llm.provider,
                    "model": config.llm.model,
                    "base_url": config.llm.base_url or "(provider default)",
                    "command": config.llm.command or config.llm.provider_options.get("command") or "",
                    "available_providers": [provider.name for provider in list_providers()],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return True

    if command == "/config":
        print(
            json.dumps(
                {
                    "home": str(config.home),
                    "provider": config.llm.provider,
                    "model": config.llm.model,
                    "llm_ready": llm.is_configured(),
                    "memory": memory.status(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return True

    if command == "/speak":
        if not last_reply:
            print("No LLM reply available to speak yet.")
            return True
        try:
            speak_text(last_reply)
        except TTSError as exc:
            print(f"Speech playback failed: {exc}")
        return True

    if command == "/clear":
        memory.clear_session()
        print("Current short-term context cleared.")
        return True

    if command in {"/exit", "/quit", "/end", "退出", "结束"}:
        _reflect_on_exit(reflection)
        return "exit"

    return False


def _reflect_on_exit(reflection: ReflectionEngine) -> None:
    result = reflection.reflect(trigger="exit")
    if result:
        print(f"Kero> Before sleeping, I saved this reflection: {result.summary}")
    print("Kero> Good night.")


def _print_lines(lines: Iterable[str]) -> None:
    for line in lines:
        print(line)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kero",
        description="Kero CLI companion agent focused on memory and self-evolution.",
    )
    parser.add_argument("--config-file", help="Use a specific YAML config file for chat")
    parser.add_argument("--provider", help="Override llm.provider for this chat session")
    parser.add_argument("--model", help="Override llm.model for this chat session")
    parser.add_argument("--base-url", help="Override llm.base_url for this chat session")
    parser.add_argument("--api-key", help="Override llm.api_key for this chat session")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM calls for this chat session")
    parser.add_argument("--speak", action="store_true", help="Play LLM replies as audio automatically")

    subparsers = parser.add_subparsers(dest="command")
    add_setup_parser(subparsers)
    add_config_parser(subparsers)
    return parser.parse_args(argv)


def _chat_overrides(args: argparse.Namespace) -> dict:
    llm: dict[str, object] = {}
    if args.provider:
        llm["provider"] = args.provider
    if args.model:
        llm["model"] = args.model
    if args.base_url:
        llm["base_url"] = args.base_url
    if args.api_key:
        llm["api_key"] = args.api_key
    if args.no_llm:
        llm["enabled"] = False
    return {"llm": llm} if llm else {}
