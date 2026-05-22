from __future__ import annotations
from unittest.mock import patch

import pytest

from bot_overgear import _USAGE, main


def test_main_shows_usage_with_no_args(capsys: pytest.CaptureFixture[str]) -> None:
    main([])
    captured = capsys.readouterr()
    assert "usage: bot-overgear" in captured.out
    assert captured.out == _USAGE + "\n"


def test_main_shows_usage_with_help(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--help"])
    captured = capsys.readouterr()
    assert "usage: bot-overgear" in captured.out


@patch("bot_overgear.observe.load_settings", side_effect=RuntimeError("mocked"))
def test_main_dispatches_observe(mock_load: object) -> None:
    with pytest.raises(RuntimeError, match="mocked"):
        main(["observe", "--no-listen"])


def test_main_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["nonexistent"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "unknown command" in captured.err
