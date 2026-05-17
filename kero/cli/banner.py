from __future__ import annotations

import shutil

from kero import __version__
from kero.config import KeroConfig


WIDE_LOGO = r"""
 _  __                 ____                  _   
| |/ /___ _ __ ___    / ___|___  _ __  ___  | |_ 
| ' // _ \ '__/ _ \  | |   / _ \| '_ \/ __| | __|
| . \  __/ | | (_) | | |__| (_) | | | \__ \ | |_ 
|_|\_\___|_|  \___/   \____\___/|_| |_|___/  \__|
""".strip("\n")


COMPACT_LOGO = r"""
 _  __              
| |/ /___ _ __ ___ 
| ' // _ \ '__/ _ \
| . \  __/ | | (_) |
|_|\_\___|_|  \___/
""".strip("\n")


def build_banner(config: KeroConfig, *, llm_ready: bool) -> str:
    width = shutil.get_terminal_size((80, 20)).columns
    logo = WIDE_LOGO if width >= 58 else COMPACT_LOGO
    status = "ready" if llm_ready else "local fallback"
    lines = [
        logo,
        "",
        f"Kero Agent v{__version__}",
        f"Provider: {config.llm.provider} | Model: {config.llm.model}",
        f"Data home: {config.home}",
        f"LLM: {status}",
    ]
    return "\n".join(lines)
