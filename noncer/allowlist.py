"""Load argv templates: signed EIP-712 ``action`` string must match a map key exactly."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from collections.abc import Mapping


class AllowlistError(ValueError):
    """Invalid allow-list file or command mapping."""


def load_command_allowlist(path: Path) -> dict[str, list[str]]:
    """
    Load JSON::

        {"commands": {"intent-key": ["/absolute/bin", "arg1", "..."]}}

    Keys are matched against the EIP-712 ``action`` field after stripping leading/trailing
    whitespace only (exact string match).
    """
    path = Path(path)
    if not path.is_file():
        raise AllowlistError(f"allow-list file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise AllowlistError(f"invalid JSON in {path}: {e}") from e

    if not isinstance(raw, dict) or "commands" not in raw:
        raise AllowlistError(
            f"{path} must be a JSON object with a top-level \"commands\" object "
            'mapping intent keys to argv arrays, e.g. {"commands": {"scan": ["/bin/true"]}}'
        )

    cmds = raw["commands"]
    if not isinstance(cmds, dict) or not cmds:
        raise AllowlistError(f"{path}: \"commands\" must be a non-empty object")

    out: dict[str, list[str]] = {}
    for key, argv in cmds.items():
        if not isinstance(key, str) or not key.strip():
            raise AllowlistError(f"{path}: invalid command key {key!r}")
        if not isinstance(argv, list) or not argv:
            raise AllowlistError(f"{path}: commands[{key!r}] must be a non-empty argv array")
        parsed: list[str] = []
        for i, part in enumerate(argv):
            if not isinstance(part, str) or not part:
                raise AllowlistError(f"{path}: commands[{key!r}][{i}] must be a non-empty string")
            parsed.append(part)
        out[key.strip()] = parsed

    return out


def resolve_argv_for_intent(action_field: str, commands: Mapping[str, list[str]]) -> list[str]:
    """Return argv list for ``action_field``, or raise AllowlistError."""
    key = action_field.strip()
    if key not in commands:
        raise AllowlistError(f"intent action not in allow-list (unknown key): {key!r}")
    return list(commands[key])


def validate_executable(argv0: str, *, strict: bool) -> None:
    """Optionally verify argv[0] resolves to an executable file."""
    if not strict:
        return
    path = argv0
    if not os.path.isabs(path):
        found = shutil.which(path)
        if found:
            path = found
    if not os.path.isfile(path):
        raise AllowlistError(f"executable not found: {argv0!r}")
    if not os.access(path, os.X_OK):
        raise AllowlistError(f"not executable: {path!r}")
