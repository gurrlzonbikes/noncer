"""CLI: emit signed intents and query gate nonce."""

from __future__ import annotations

import argparse
import os
import sys

import requests

from noncer import __version__
from noncer.payload import build_intent
from noncer.sign_ledger import send_intent


DEFAULT_GATE_URL = os.environ.get("NONCER_GATE_URL", "http://127.0.0.1:3090")
DEFAULT_RPC = os.environ.get("NONCER_RPC_URL", "https://sepolia.base.org")


def fetch_expected_nonce(address: str, gate_url: str) -> int:
    url = gate_url.rstrip("/") + "/nonce"
    r = requests.get(url, params={"address": address}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return int(data["expected"])


def cmd_emit(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="noncer emit", description="Sign and broadcast intent (Ledger)")
    p.add_argument("--address", required=True, help="Your Ethereum address")
    p.add_argument("--derivation-path", required=True, help="Ledger path e.g. 44'/60'/0'/0/0")
    p.add_argument("--action", required=True, help="Shell command for the gate to execute")
    p.add_argument("--nonce", type=int, default=None, help="Application nonce (default: query gate)")
    p.add_argument("--gate-url", default=DEFAULT_GATE_URL)
    p.add_argument("--rpc-url", default=DEFAULT_RPC)
    p.add_argument("--chain-id", type=int, default=int(os.environ.get("NONCER_CHAIN_ID", "84532")))
    ns = p.parse_args(argv)

    nonce = ns.nonce
    if nonce is None:
        try:
            nonce = fetch_expected_nonce(ns.address, ns.gate_url)
            print(f"📋 Expected application nonce from gate: {nonce}")
        except requests.RequestException as e:
            print(
                "❌ Could not reach gate for nonce. Start the watcher or pass --nonce explicitly.\n",
                e,
                file=sys.stderr,
            )
            sys.exit(1)

    payload = build_intent(nonce, ns.action)
    result = send_intent(
        payload=payload,
        address=ns.address,
        derivation_path=ns.derivation_path,
        rpc_url=ns.rpc_url,
        chain_id=ns.chain_id,
    )

    if result.returncode != 0:
        print("❌ Signing/broadcast failed:", file=sys.stderr)
        print(result.stderr or result.stdout, file=sys.stderr)
        sys.exit(result.returncode or 1)

    print(result.stdout, end="")


def cmd_nonce(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="noncer nonce", description="Query expected application nonce from gate")
    p.add_argument("--address", required=True)
    p.add_argument("--gate-url", default=DEFAULT_GATE_URL)
    ns = p.parse_args(argv)
    try:
        n = fetch_expected_nonce(ns.address, ns.gate_url)
        print(n)
    except requests.RequestException as e:
        print(f"❌ Gate unreachable: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print(
            f"noncer {__version__}\n\nUsage: noncer emit ... | noncer nonce ...",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd in ("-h", "--help"):
        print(
            f"noncer {__version__}\n\n"
            "Commands:\n"
            "  emit   Ledger-sign intent JSON and broadcast (see: noncer emit -h)\n"
            "  nonce  Print expected application nonce (see: noncer nonce -h)"
        )
        return

    if cmd == "emit":
        cmd_emit(rest)
    elif cmd == "nonce":
        cmd_nonce(rest)
    elif cmd in ("-V", "--version"):
        print(__version__)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
