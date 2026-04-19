"""
Chain watcher + gate: NFT eligibility, monotonic application nonce, command execution.

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

from noncer.payload import parse_intent
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


def process_tx(
    *,
    tx: Any,
    tx_hash_hex: str,
    state: GateState,
    nft: Any,
    w3: Web3,
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

    inp = tx.get("input") or "0x"
    if inp == "0x":
        state.mark_tx_seen(tx_hash_hex)
        return

    try:
        raw = bytes.fromhex(inp[2:] if inp.startswith("0x") else inp)
        text = raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        logger.debug("Skip tx %s: calldata not UTF-8 intent", tx_hash_hex)
        state.mark_tx_seen(tx_hash_hex)
        return

    try:
        app_nonce, action = parse_intent(text)
    except ValueError as e:
        logger.info("Invalid intent in %s: %s", tx_hash_hex, e)
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

    logger.info("Watching chain via %s NFT=%s", rpc_url, nft_addr)

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
                    process_tx(tx=tx, tx_hash_hex=h, state=state, nft=nft, w3=w3)
                state.set_last_block(bn)

            time.sleep(poll_seconds)
        except Exception:
            logger.exception("watch loop error; backing off")
            time.sleep(min(poll_seconds * 2, 60))


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("NONCER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    p = argparse.ArgumentParser(description="Noncer gate: watch chain, enforce nonce + NFT, execute intents")
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

    args = p.parse_args()

    state = GateState(args.state_dir)

    watch_forever(
        rpc_url=args.rpc_url,
        nft_contract=args.nft_contract,
        state=state,
        poll_seconds=args.poll_interval,
        bind_host=args.gate_host,
        gate_port=args.gate_port,
        http_enabled=not args.no_http,
    )


if __name__ == "__main__":
    main()
