import json
from pathlib import Path

import pytest

from noncer.allowlist import AllowlistError, load_command_allowlist, resolve_argv_for_intent


def test_load_and_resolve(tmp_path: Path) -> None:
    p = tmp_path / "al.json"
    p.write_text(
        json.dumps({"commands": {"hello": ["/bin/echo", "x"], "true-cmd": ["/bin/true"]}}),
        encoding="utf-8",
    )
    m = load_command_allowlist(p)
    assert resolve_argv_for_intent("hello", m) == ["/bin/echo", "x"]
    assert resolve_argv_for_intent("  hello  ", m) == ["/bin/echo", "x"]


def test_unknown_key(tmp_path: Path) -> None:
    p = tmp_path / "al.json"
    p.write_text(json.dumps({"commands": {"a": ["/bin/true"]}}), encoding="utf-8")
    m = load_command_allowlist(p)
    with pytest.raises(AllowlistError, match="unknown"):
        resolve_argv_for_intent("b", m)


def test_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(AllowlistError):
        load_command_allowlist(p)


def test_missing_commands_key(tmp_path: Path) -> None:
    p = tmp_path / "al.json"
    p.write_text(json.dumps({"foo": {}}), encoding="utf-8")
    with pytest.raises(AllowlistError):
        load_command_allowlist(p)
