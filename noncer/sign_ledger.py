"""Invoke the Node + Ledger signer (package-relative ``js/signer.cjs``)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _signer_script() -> Path:
    return Path(__file__).resolve().parent / "js" / "signer.cjs"


def send_intent(
    *,
    payload: str,
    address: str,
    derivation_path: str,
    rpc_url: str | None = None,
    chain_id: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Broadcast a signed tx; calldata is UTF-8 ``payload`` (intent JSON)."""
    script = _signer_script()
    if not script.is_file():
        raise FileNotFoundError(f"signer script not found: {script}")

    env = os.environ.copy()
    if rpc_url:
        env["NONCER_RPC_URL"] = rpc_url
    if chain_id is not None:
        env["NONCER_CHAIN_ID"] = str(chain_id)

    cmd = ["node", str(script), payload, address, derivation_path]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)
