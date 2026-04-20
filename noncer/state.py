"""Persistent gate state: block cursor, processed tx hashes, expected EOA tx nonce per runner."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class GateState:
    """JSON-backed store for scan cursor, seen txs, and next expected Ethereum nonce per runner address."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.state_dir / "gate_state.json"
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"expected_next_eth_nonce": {}, "seen_tx": [], "last_block": None}
        with open(self._path, encoding="utf-8") as f:
            raw = json.load(f)
        raw.setdefault("expected_next_eth_nonce", {})
        raw.setdefault("seen_tx", [])
        if "last_block" not in raw:
            raw["last_block"] = None
        raw["seen_tx"] = list(dict.fromkeys(raw["seen_tx"]))
        return raw

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)
        tmp.replace(self._path)

    def get_expected_next_eth_nonce(self, address_checksum: str) -> int | None:
        """Next tx nonce the watcher expects for this address, or None if never seen."""
        key = address_checksum.lower()
        v = self._data["expected_next_eth_nonce"].get(key)
        return int(v) if v is not None else None

    def record_observed_eth_nonce(self, address_checksum: str, mined_tx_nonce: int) -> None:
        """After observing a mined tx with nonce ``mined_tx_nonce``, chain expects ``mined_tx_nonce + 1`` next."""
        key = address_checksum.lower()
        self._data["expected_next_eth_nonce"][key] = mined_tx_nonce + 1
        self._save()

    def has_seen_tx(self, tx_hash_hex: str) -> bool:
        h = tx_hash_hex.lower().removeprefix("0x")
        return h in set(x.lower().removeprefix("0x") for x in self._data["seen_tx"])

    def mark_tx_seen(self, tx_hash_hex: str) -> None:
        h = tx_hash_hex.lower()
        if h.startswith("0x"):
            pass
        else:
            h = "0x" + h
        existing = {x.lower() for x in self._data["seen_tx"]}
        if h.lower() not in existing:
            self._data["seen_tx"].append(h)
            if len(self._data["seen_tx"]) > 50_000:
                self._data["seen_tx"] = self._data["seen_tx"][-50_000:]
            self._save()

    def get_last_block(self) -> int | None:
        lb = self._data.get("last_block")
        return int(lb) if lb is not None else None

    def set_last_block(self, value: int) -> None:
        self._data["last_block"] = value
        self._save()


def default_state_dir() -> Path:
    base = Path(os.environ.get("NONCER_STATE_DIR", Path.home() / ".noncer"))
    return base
