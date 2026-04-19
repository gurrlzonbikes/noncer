"""Intent payloads embedded in transaction calldata (UTF-8 JSON)."""

from __future__ import annotations

import json
from typing import Any


def build_intent(nonce: int, action: str) -> str:
    """Serialize intent for signing and broadcast in tx ``data``."""
    return json.dumps({"nonce": nonce, "action": action}, separators=(",", ":"))


def parse_intent(calldata_text: str) -> tuple[int, str]:
    """
    Parse intent JSON from calldata decoded as UTF-8 text.

    Raises:
        ValueError: if JSON is invalid or fields are missing / wrong type.
    """
    try:
        obj: Any = json.loads(calldata_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid intent JSON: {e}") from e

    if not isinstance(obj, dict):
        raise ValueError("intent must be a JSON object")

    n = obj.get("nonce")
    action = obj.get("action")
    if not isinstance(n, int) or n < 0:
        raise ValueError("intent.nonce must be a non-negative integer")
    if not isinstance(action, str) or not action.strip():
        raise ValueError("intent.action must be a non-empty string")

    return n, action
