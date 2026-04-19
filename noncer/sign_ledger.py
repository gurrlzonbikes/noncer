"""Invoke the Node + Ledger signer (``js/signer.cjs``); structured EIP-712 config via stdin JSON."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _signer_script() -> Path:
    return Path(__file__).resolve().parent / "js" / "signer.cjs"


def send_structured_intent(cfg: dict, *, rpc_url: str | None = None, chain_id: int | None = None) -> subprocess.CompletedProcess[str]:
    """
    Run signer with JSON on stdin. Required keys: appNonce, action, policyCommitment (hex),
    address, derivationPath, chainId; optional: rpcUrl, eip712Name, eip712Version, verifyingContract.
    """
    script = _signer_script()
    if not script.is_file():
        raise FileNotFoundError(f"signer script not found: {script}")

    env = os.environ.copy()
    if rpc_url:
        env["NONCER_RPC_URL"] = rpc_url
    if chain_id is not None:
        env["NONCER_CHAIN_ID"] = str(chain_id)

    payload = json.dumps(cfg, separators=(",", ":"))
    return subprocess.run(
        ["node", str(script)],
        input=payload,
        text=True,
        capture_output=True,
        env=env,
    )
