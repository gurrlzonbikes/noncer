"""
Chain watcher + gate: AccessControl eligibility, EIP-712 intent nonce == Ethereum tx nonce, EIP-712 verify.

Optional HTTP GET /health only (no nonce oracle — next nonce comes from RPC ``eth_getTransactionCount``).
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hexbytes import HexBytes
from web3 import Web3

from noncer.allowlist import (
    AllowlistError,
    load_command_allowlist,
    resolve_argv_for_intent,
    validate_executable,
)
from noncer.calldata_v1 import recover_signer, unpack_v1
from noncer.state import GateState, default_state_dir

logger = logging.getLogger(__name__)

ACCESS_CONTROL_HAS_ROLE_ABI = [
    {
        "inputs": [
            {"name": "role", "type": "bytes32"},
            {"name": "account", "type": "address"},
        ],
        "name": "hasRole",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def _parse_runner_role_hex(s: str | None) -> bytes:
    """Default: same as Solidity ``keccak256(bytes('RUNNER'))`` / ``RUNNER_ROLE`` constant."""
    if not s or not str(s).strip():
        return bytes(Web3.keccak(text="RUNNER"))
    h = str(s).strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    if len(h) != 64:
        raise ValueError("runner-role must be 32 bytes (64 hex chars)")
    return bytes.fromhex(h)


def _run_gate_http(bind_host: str, port: int) -> None:
    from flask import Flask, jsonify

    app = Flask(__name__)

    @app.route("/health")
    def health():
        return jsonify({"ok": True})

    app.run(host=bind_host, port=port, threaded=True, use_reloader=False)


def execute_action(
    *,
    action_key: str,
    commands: dict[str, list[str]],
    strict_executable: bool,
) -> None:
    """Run a fixed argv template; ``action_key`` must match an allow-list entry (no shell)."""
    argv = resolve_argv_for_intent(action_key, commands)
    validate_executable(argv[0], strict=strict_executable)
    logger.info("Executing allow-listed argv: %s", argv)
    subprocess.run(argv, shell=False, check=True)


def _tx_hash_hex(tx: Any) -> str:
    h = tx["hash"]
    if isinstance(h, HexBytes):
        return h.hex()
    if hasattr(h, "hex"):
        return h.hex()
    return Web3.to_hex(h)


def _tx_nonce_int(tx: Any) -> int:
    n = tx["nonce"]
    if isinstance(n, int):
        return n
    return int(n)


def _input_hex(tx: Any, w3: Web3) -> str:
    inp = tx.get("input") or "0x"
    if hasattr(inp, "hex"):
        return inp.hex()
    return w3.to_hex(inp)


def process_tx(
    *,
    tx: Any,
    tx_hash_hex: str,
    state: GateState,
    is_eligible: Callable[[str], bool],
    w3: Web3,
    domain_name: str,
    domain_version: str,
    verifying_contract: str,
    expected_policy_bytes: bytes | None,
    commands: dict[str, list[str]],
    strict_executable: bool,
) -> None:
    if state.has_seen_tx(tx_hash_hex):
        return

    if not tx.get("to"):
        state.mark_tx_seen(tx_hash_hex)
        return

    sender = tx["from"]
    if not sender:
        state.mark_tx_seen(tx_hash_hex)
        return

    sender_cs = Web3.to_checksum_address(sender)

    try:
        ok = is_eligible(sender_cs)
    except Exception as e:
        logger.error("eligibility check failed for %s: %s", sender_cs, e)
        state.mark_tx_seen(tx_hash_hex)
        return

    if not ok:
        logger.debug("Not a registry runner: %s", sender_cs)
        state.mark_tx_seen(tx_hash_hex)
        return

    eth_nonce = _tx_nonce_int(tx)

    try:
        inp_hex = _input_hex(tx, w3)
        try:
            intent_nonce, action, policy_commitment, v, r_b, s_b = unpack_v1(inp_hex)
        except ValueError as e:
            logger.error(
                "[ALARM] runner %s mined tx without Noncer calldata (%s) tx=%s eth_nonce=%s — "
                "investigate compromise or misuse",
                sender_cs,
                e,
                tx_hash_hex,
                eth_nonce,
            )
            state.mark_tx_seen(tx_hash_hex)
            return

        if intent_nonce != eth_nonce:
            logger.error(
                "[ALARM] EIP-712 intent nonce != Ethereum tx nonce: signer=%s intent_nonce=%s "
                "tx.nonce=%s tx=%s",
                sender_cs,
                intent_nonce,
                eth_nonce,
                tx_hash_hex,
            )
            state.mark_tx_seen(tx_hash_hex)
            return

        chain_id_int = int(w3.eth.chain_id)

        try:
            recovered = recover_signer(
                chain_id=chain_id_int,
                nonce=intent_nonce,
                action=action,
                policy_commitment=policy_commitment,
                v=v,
                r=r_b,
                s=s_b,
                domain_name=domain_name,
                domain_version=domain_version,
                verifying_contract=verifying_contract,
            )
        except Exception as e:
            logger.info("EIP-712 recover failed for %s: %s", tx_hash_hex, e)
            state.mark_tx_seen(tx_hash_hex)
            return

        recovered_cs = Web3.to_checksum_address(recovered)
        if recovered_cs != sender_cs:
            logger.info(
                "Signer mismatch tx %s: recovered %s != from %s",
                tx_hash_hex,
                recovered_cs,
                sender_cs,
            )
            state.mark_tx_seen(tx_hash_hex)
            return

        if expected_policy_bytes is not None and policy_commitment != expected_policy_bytes:
            logger.info(
                "Policy commitment mismatch for %s (expected %s got %s)",
                tx_hash_hex,
                expected_policy_bytes.hex(),
                policy_commitment.hex(),
            )
            state.mark_tx_seen(tx_hash_hex)
            return

        expected_next = state.get_expected_next_eth_nonce(sender_cs)
        if expected_next is not None and eth_nonce != expected_next:
            logger.error(
                "[ALARM] Ethereum nonce sequence mismatch for %s: tx.nonce=%s expected=%s tx=%s — "
                "possible gap, reorder, or missed block; revoke runner on-chain after review",
                sender_cs,
                eth_nonce,
                expected_next,
                tx_hash_hex,
            )
            state.mark_tx_seen(tx_hash_hex)
            return

        logger.info("Eligible intent → eth_nonce=%s action=%r", eth_nonce, action)

        try:
            execute_action(
                action_key=action,
                commands=commands,
                strict_executable=strict_executable,
            )
        except AllowlistError as e:
            logger.info("Allow-list rejected %s: %s", tx_hash_hex, e)
            state.mark_tx_seen(tx_hash_hex)
            return
        except subprocess.CalledProcessError as e:
            logger.error("Execution failed for %s: %s", tx_hash_hex, e)
            state.mark_tx_seen(tx_hash_hex)
            return

        state.mark_tx_seen(tx_hash_hex)
        logger.info(
            "Committed argv for eth_nonce=%s → next expected tx.nonce=%s",
            eth_nonce,
            eth_nonce + 1,
        )
    finally:
        state.record_observed_eth_nonce(sender_cs, eth_nonce)


def watch_forever(
    *,
    rpc_url: str,
    state: GateState,
    poll_seconds: float,
    bind_host: str,
    gate_port: int,
    http_enabled: bool,
    domain_name: str,
    domain_version: str,
    verifying_contract: str,
    expected_policy_bytes: bytes | None,
    commands: dict[str, list[str]],
    strict_executable: bool,
    registry_contract: str,
    runner_role_bytes: bytes,
) -> None:
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise RuntimeError(f"cannot connect to RPC: {rpc_url}")

    reg_addr = w3.to_checksum_address(registry_contract)
    reg = w3.eth.contract(address=reg_addr, abi=ACCESS_CONTROL_HAS_ROLE_ABI)
    rr = runner_role_bytes

    def is_eligible(addr: str) -> bool:
        return reg.functions.hasRole(rr, addr).call()

    elig_label = f"registry={reg_addr} role={rr.hex()}"

    if http_enabled:
        t = threading.Thread(
            target=_run_gate_http,
            args=(bind_host, gate_port),
            daemon=True,
            name="noncer-gate-http",
        )
        t.start()
        logger.info("Gate HTTP health on http://%s:%s/health", bind_host, gate_port)

    logger.info("Watching chain via %s eligibility=%s chainId=%s", rpc_url, elig_label, int(w3.eth.chain_id))

    while True:
        try:
            latest = w3.eth.block_number
            lb = state.get_last_block()
            if lb is None:
                lb = latest - 1

            for bn in range(lb + 1, latest + 1):
                block = w3.eth.get_block(bn, full_transactions=True)
                txs = block.transactions
                for tx in txs:
                    h = _tx_hash_hex(tx)
                    process_tx(
                        tx=tx,
                        tx_hash_hex=h,
                        state=state,
                        is_eligible=is_eligible,
                        w3=w3,
                        domain_name=domain_name,
                        domain_version=domain_version,
                        verifying_contract=verifying_contract,
                        expected_policy_bytes=expected_policy_bytes,
                        commands=commands,
                        strict_executable=strict_executable,
                    )
                state.set_last_block(bn)

            time.sleep(poll_seconds)
        except Exception:
            logger.exception("watch loop error; backing off")
            time.sleep(min(poll_seconds * 2, 60))


def _parse_policy_hex(s: str | None) -> bytes | None:
    if not s or not s.strip():
        return None
    h = s.strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    if len(h) != 64:
        raise ValueError("expected-policy-commitment must be 32 bytes hex")
    return bytes.fromhex(h)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("NONCER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    p = argparse.ArgumentParser(description="Noncer gate: EIP-712 + Ethereum tx nonce + registry eligibility")
    p.add_argument("--rpc-url", default=os.environ.get("NONCER_RPC_URL", "https://sepolia.base.org"))
    p.add_argument(
        "--registry-contract",
        default=os.environ.get("NONCER_REGISTRY_CONTRACT"),
        help="AccessControl contract (e.g. NoncerGateRegistry); env: NONCER_REGISTRY_CONTRACT",
    )
    p.add_argument(
        "--runner-role",
        default=os.environ.get("NONCER_RUNNER_ROLE"),
        help="bytes32 hex for hasRole (default: keccak256('RUNNER') matching NoncerGateRegistry.RUNNER_ROLE)",
    )
    p.add_argument(
        "--state-dir",
        type=Path,
        default=Path(os.environ.get("NONCER_STATE_DIR", default_state_dir())),
    )
    p.add_argument("--poll-interval", type=float, default=float(os.environ.get("NONCER_POLL_SECONDS", "2")))
    p.add_argument("--gate-host", default=os.environ.get("NONCER_GATE_HOST", "127.0.0.1"))
    p.add_argument("--gate-port", type=int, default=int(os.environ.get("NONCER_GATE_PORT", "3090")))
    p.add_argument("--no-http", action="store_true", help="disable HTTP /health endpoint")
    p.add_argument("--eip712-name", default=os.environ.get("NONCER_EIP712_NAME", "Noncer"))
    p.add_argument("--eip712-version", default=os.environ.get("NONCER_EIP712_VERSION", "1"))
    p.add_argument(
        "--verifying-contract",
        default=os.environ.get("NONCER_VERIFYING_CONTRACT", "0x0000000000000000000000000000000000000000"),
    )
    p.add_argument(
        "--expected-policy-commitment",
        default=os.environ.get("NONCER_EXPECTED_POLICY_COMMITMENT"),
        help="If set, intent policyCommitment bytes32 must match this hex",
    )
    p.add_argument(
        "--allowlist",
        type=Path,
        default=None,
        help="JSON file: {\"commands\": {\"intent-key\": [\"/bin/app\", \"arg\"]}} (env: NONCER_ALLOWLIST)",
    )
    p.add_argument(
        "--strict-executable",
        action="store_true",
        help="Require argv[0] to exist on disk and be executable (recommended on gate hosts)",
    )

    args = p.parse_args()

    if not args.registry_contract:
        print("--registry-contract is required (or set NONCER_REGISTRY_CONTRACT)", file=sys.stderr)
        sys.exit(2)
    try:
        runner_role_bytes = _parse_runner_role_hex(args.runner_role)
    except ValueError as e:
        raise SystemExit(f"invalid --runner-role: {e}") from e

    try:
        policy_bytes = _parse_policy_hex(args.expected_policy_commitment)
    except ValueError as e:
        raise SystemExit(f"invalid --expected-policy-commitment: {e}") from e

    allow_path = args.allowlist
    if allow_path is None:
        env_al = os.environ.get("NONCER_ALLOWLIST")
        allow_path = Path(env_al) if env_al else Path(args.state_dir) / "allowlist.json"

    try:
        commands = load_command_allowlist(allow_path)
    except AllowlistError as e:
        raise SystemExit(f"allow-list: {e}") from e

    state = GateState(args.state_dir)

    strict_exe = args.strict_executable or (
        os.environ.get("NONCER_STRICT_EXECUTABLE", "").lower() in ("1", "true", "yes")
    )

    watch_forever(
        rpc_url=args.rpc_url,
        state=state,
        poll_seconds=args.poll_interval,
        bind_host=args.gate_host,
        gate_port=args.gate_port,
        http_enabled=not args.no_http,
        domain_name=args.eip712_name,
        domain_version=args.eip712_version,
        verifying_contract=args.verifying_contract,
        expected_policy_bytes=policy_bytes,
        commands=commands,
        strict_executable=strict_exe,
        registry_contract=args.registry_contract,
        runner_role_bytes=runner_role_bytes,
    )


if __name__ == "__main__":
    main()
