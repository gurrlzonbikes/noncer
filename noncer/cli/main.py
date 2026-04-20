"""CLI: emit signed intents (nonce from RPC) and query next Ethereum tx nonce."""

from __future__ import annotations

import argparse
import os
import sys

from web3 import Web3

from noncer import __version__
from noncer.sign_ledger import send_structured_intent


DEFAULT_RPC = os.environ.get("NONCER_RPC_URL", "https://sepolia.base.org")
DEFAULT_POLICY = os.environ.get(
    "NONCER_POLICY_COMMITMENT",
    "0x0000000000000000000000000000000000000000000000000000000000000000",
)


def fetch_pending_tx_nonce(address: str, rpc_url: str) -> int:
    """Next Ethereum tx nonce for ``address`` (matches signer + EIP-712 Intent.nonce)."""
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"cannot connect to RPC: {rpc_url}")
    cs = Web3.to_checksum_address(address)
    return int(w3.eth.get_transaction_count(cs, "pending"))


def cmd_emit(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="noncer emit", description="EIP-712 intent + broadcast (Ledger, two device prompts)")
    p.add_argument("--address", required=True, help="Your Ethereum address")
    p.add_argument("--derivation-path", required=True, help="Ledger path e.g. 44'/60'/0'/0/0")
    p.add_argument(
        "--action",
        required=True,
        help="Intent key (must match a key in the gate allow-list JSON → fixed argv, no shell)",
    )
    p.add_argument("--policy-commitment", default=DEFAULT_POLICY, help="bytes32 hex (32-byte policy manifest hash)")
    p.add_argument("--rpc-url", default=DEFAULT_RPC)
    p.add_argument("--chain-id", type=int, default=int(os.environ.get("NONCER_CHAIN_ID", "84532")))
    p.add_argument("--eip712-name", default=os.environ.get("NONCER_EIP712_NAME", "Noncer"))
    p.add_argument("--eip712-version", default=os.environ.get("NONCER_EIP712_VERSION", "1"))
    p.add_argument(
        "--verifying-contract",
        default=os.environ.get("NONCER_VERIFYING_CONTRACT", "0x0000000000000000000000000000000000000000"),
        help="EIP-712 domain verifyingContract (default zero address)",
    )
    ns = p.parse_args(argv)

    pc = ns.policy_commitment.strip().lower()
    if not pc.startswith("0x") or len(pc) != 66:
        print("❌ --policy-commitment must be 32-byte hex (0x + 64 chars)", file=sys.stderr)
        sys.exit(2)

    try:
        pending = fetch_pending_tx_nonce(ns.address, ns.rpc_url)
        print(f"📋 Next Ethereum tx.nonce / EIP-712 Intent.nonce (pending): {pending}")
    except Exception as e:
        print(f"❌ Could not read nonce from RPC.\n{e}", file=sys.stderr)
        sys.exit(1)

    cfg = {
        "action": ns.action,
        "policyCommitment": ns.policy_commitment,
        "address": ns.address,
        "derivationPath": ns.derivation_path,
        "rpcUrl": ns.rpc_url,
        "chainId": ns.chain_id,
        "eip712Name": ns.eip712_name,
        "eip712Version": ns.eip712_version,
        "verifyingContract": ns.verifying_contract,
    }

    result = send_structured_intent(cfg, rpc_url=ns.rpc_url, chain_id=ns.chain_id)

    if result.returncode != 0:
        print("❌ Signing/broadcast failed:", file=sys.stderr)
        print(result.stderr or result.stdout, file=sys.stderr)
        sys.exit(result.returncode or 1)

    print(result.stdout, end="")


def cmd_nonce(argv: list[str]) -> None:
    p = argparse.ArgumentParser(
        prog="noncer nonce",
        description="Print next Ethereum tx nonce (pending pool) — same value used for EIP-712 Intent.nonce",
    )
    p.add_argument("--address", required=True)
    p.add_argument("--rpc-url", default=DEFAULT_RPC)
    ns = p.parse_args(argv)
    try:
        n = fetch_pending_tx_nonce(ns.address, ns.rpc_url)
        print(n)
    except Exception as e:
        print(f"❌ RPC error: {e}", file=sys.stderr)
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
            "  emit   EIP-712 intent + tx (Ledger, two prompts; see: noncer emit -h)\n"
            "  nonce  Next Ethereum tx nonce / intent nonce from RPC (see: noncer nonce -h)"
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
