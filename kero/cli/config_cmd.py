from __future__ import annotations

import json
from argparse import ArgumentParser, Namespace
from pathlib import Path

from kero.config import (
    get_dot_path,
    get_home_config_path,
    get_home_env_path,
    get_project_config_path,
    load_config_data,
    parse_value,
    redact_config,
    save_config_data,
    set_dot_path,
    validate_config_data,
    write_default_config,
)


def add_config_parser(subparsers) -> None:
    parser = subparsers.add_parser("config", help="Show or edit Kero configuration")
    config_sub = parser.add_subparsers(dest="config_command")

    config_sub.add_parser("show", help="Show effective config with secrets redacted")
    config_sub.add_parser("path", help="Show config and env file paths")
    init_parser = config_sub.add_parser("init", help="Create $KERO_HOME/config.yaml")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config.yaml")

    get_parser = config_sub.add_parser("get", help="Read a dot-path config value")
    get_parser.add_argument("key")

    set_parser = config_sub.add_parser("set", help="Write a dot-path config value")
    set_parser.add_argument("key")
    set_parser.add_argument("value")

    config_sub.add_parser("validate", help="Validate effective config")
    parser.set_defaults(func=run_config_command)


def run_config_command(args: Namespace) -> None:
    command = args.config_command or "show"

    if command == "path":
        data = {
            "home_config": str(get_home_config_path()),
            "home_env": str(get_home_env_path()),
            "project_config": str(get_project_config_path()),
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if command == "init":
        path = write_default_config(force=bool(getattr(args, "force", False)))
        print(f"Config ready: {path}")
        return

    if command == "show":
        print(json.dumps(redact_config(load_config_data()), ensure_ascii=False, indent=2))
        return

    if command == "get":
        data = load_config_data()
        try:
            value = get_dot_path(data, args.key)
        except KeyError:
            raise SystemExit(f"Unknown config key: {args.key}")
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return

    if command == "set":
        path = get_home_config_path()
        raw = load_config_data(config_path=path, include_env=False)
        set_dot_path(raw, args.key, parse_value(args.value))
        save_config_data(raw, path)
        print(f"Updated {args.key} in {path}")
        return

    if command == "validate":
        errors = validate_config_data(load_config_data())
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            raise SystemExit(1)
        print("Config OK")
        return

    raise SystemExit(f"Unknown config command: {command}")
