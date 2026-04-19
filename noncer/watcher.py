"""
Chain watcher + gate: NFT eligibility, monotonic application nonce, EIP-712 verification.

Exposes HTTP ``GET /nonce?address=0x...`` so ``noncer emit`` can learn the next expected nonce.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from hexbytes import HexBytes
from web3 import Web3

from noncer.calldata_v1 import recover_signer, unpack_v1
from noncer.state import GateState, default_state_dir

logger = logging.getLogger(__name__)

ERC721_MIN_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    }
]


def _run_gate_http(
    bind_host: str,
    port: int,
    state: GateState,
    w3: Web3,
) -> None:
    from flask import Flask, jsonify, request

    app = Flask(__name__)

    @app.route("/nonce")
    def nonce():
        addr = request.args.get("address")
        if not addr:
            return jsonify({"error": "missing address"}), 400
        try:
            cs = w3.to_checksum_address(addr)
        except ValueError:
            return jsonify({"error": "invalid address"}), 400
        expected = state.get_expected_nonce(cs)
        return jsonify({"expected": expected})

    @app.route("/health")
    def health():
        return jsonify({"ok": True})

    app.run(host=bind_host, port=port, threaded=True, use_reloader=False)


def execute_action(action: str) -> None:
    logger.warning("Executing shell command (demo mode): %s", action)
    subprocess.run(action, shell=True, check=True)


def _tx_hash_hex(tx: Any) -> str:
    h = tx["hash"]
    if isinstance(h, HexBytes):
        return h.hex()
    if hasattr(h, "hex"):
        return h.hex()
    return Web3.to_hex(h)


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
    nft: Any,
    w3: Web3,
    domain_name: str,
    domain_version: str,
    verifying_contract: str,
    expected_policy_bytes: bytes | None,
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
        bal = nft.functions.balanceOf(sender_cs).call()
    except Exception as e:
        logger.error("balanceOf failed for %s: %s", sender_cs, e)
        state.mark_tx_seen(tx_hash_hex)
        return

    if bal <= 0:
        logger.info("Not eligible (no NFT): %s", sender_cs)
        state.mark_tx_seen(tx_hash_hex)
        return

    inp_hex = _input_hex(tx, w3)
    try:
        app_nonce, action, policy_commitment, v, r_b, s_b = unpack_v1(inp_hex)
    except ValueError as e:
        logger.debug("Skip tx %s: calldata %s", tx_hash_hex, e)
        state.mark_tx_seen(tx_hash_hex)
        return

    chain_id_int = int(w3.eth.chain_id)

    try:
        recovered = recover_signer(
            chain_id=chain_id_int,
            nonce=app_nonce,
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

    expected = state.get_expected_nonce(sender_cs)
    if app_nonce != expected:
        logger.info(
            "Nonce mismatch for %s: got %s expected %s — tx %s",
            sender_cs,
            app_nonce,
            expected,
            tx_hash_hex,
        )
        state.mark_tx_seen(tx_hash_hex)
        return

    logger.info("Eligible intent → nonce=%s action=%r", app_nonce, action)

    try:
        execute_action(action)
    except subprocess.CalledProcessError as e:
        logger.error("Execution failed for %s: %s", tx_hash_hex, e)
        state.mark_tx_seen(tx_hash_hex)
        return

    state.increment_nonce(sender_cs)
    state.mark_tx_seen(tx_hash_hex)
    logger.info("Committed nonce → next expected=%s", state.get_expected_nonce(sender_cs))


def watch_forever(
    *,
    rpc_url: str,
    nft_contract: str,
    state: GateState,
    poll_seconds: float,
    bind_host: str,
    gate_port: int,
    http_enabled: bool,
    domain_name: str,
    domain_version: str,
    verifying_contract: str,
    expected_policy_bytes: bytes | None,
) -> None:
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise RuntimeError(f"cannot connect to RPC: {rpc_url}")

    nft_addr = w3.to_checksum_address(nft_contract)
    nft = w3.eth.contract(address=nft_addr, abi=ERC721_MIN_ABI)

    if http_enabled:
        t = threading.Thread(
            target=_run_gate_http,
            args=(bind_host, gate_port, state, w3),
            daemon=True,
            name="noncer-gate-http",
        )
        t.start()
        logger.info("Gate HTTP on http://%s:%s/nonce", bind_host, gate_port)

    logger.info("Watching chain via %s NFT=%s chainId=%s", rpc_url, nft_addr, int(w3.eth.chain_id))

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
                        nft=nft,
                        w3=w3,
                        domain_name=domain_name,
                        domain_version=domain_version,
                        verifying_contract=verifying_contract,
                        expected_policy_bytes=expected_policy_bytes,
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

    p = argparse.ArgumentParser(description="Noncer gate: watch chain, enforce EIP-712 + nonce + NFT")
    p.add_argument("--rpc-url", default=os.environ.get("NONCER_RPC_URL", "https://sepolia.base.org"))
    p.add_argument("--nft-contract", required=True, help="ERC-721 checksummed or hex address")
    p.add_argument(
        "--state-dir",
        type=Path,
        default=Path(os.environ.get("NONCER_STATE_DIR", default_state_dir())),
    )
    p.add_argument("--poll-interval", type=float, default=float(os.environ.get("NONCER_POLL_SECONDS", "2")))
    p.add_argument("--gate-host", default=os.environ.get("NONCER_GATE_HOST", "127.0.0.1"))
    p.add_argument("--gate-port", type=int, default=int(os.environ.get("NONCER_GATE_PORT", "3090")))
    p.add_argument("--no-http", action="store_true", help="disable /nonce HTTP endpoint")
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

    args = p.parse_args()

    try:
        policy_bytes = _parse_policy_hex(args.expected_policy_commitment)
    except ValueError as e:
        raise SystemExit(f"invalid --expected-policy-commitment: {e}") from e

    state = GateState(args.state_dir)

    watch_forever(
        rpc_url=args.rpc_url,
        nft_contract=args.nft_contract,
        state=state,
        poll_seconds=args.poll_interval,
        bind_host=args.gate_host,
        gate_port=args.gate_port,
        http_enabled=not args.no_http,
        domain_name=args.eip712_name,
        domain_version=args.eip712_version,
        verifying_contract=args.verifying_contract,
        expected_policy_bytes=policy_bytes,
    )


if __name__ == "__main__":
    main()
