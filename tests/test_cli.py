from __future__ import annotations

import pytest

from kero.cli.app import main


def test_cli_help(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "setup" in capsys.readouterr().out


def test_setup_help(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["setup", "--help"])
    assert exc.value.code == 0
    assert "--non-interactive" in capsys.readouterr().out
