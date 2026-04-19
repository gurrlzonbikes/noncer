"""Shared EIP-712 domain and types for Noncer intents (must match ``signer.cjs``)."""

from __future__ import annotations

from typing import Any

from eth_utils import to_checksum_address


def intent_types() -> dict[str, list[dict[str, str]]]:
    return {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "Intent": [
            {"name": "nonce", "type": "uint256"},
            {"name": "action", "type": "string"},
            {"name": "policyCommitment", "type": "bytes32"},
        ],
    }


def domain_dict(
    *,
    chain_id: int,
    name: str = "Noncer",
    version: str = "1",
    verifying_contract: str = "0x0000000000000000000000000000000000000000",
) -> dict[str, Any]:
    vc = verifying_contract.strip()
    if vc.startswith("0x") and len(vc) == 42:
        vc = to_checksum_address(vc)
    return {
        "name": name,
        "version": version,
        "chainId": chain_id,
        "verifyingContract": vc,
    }


def full_typed_message(
    *,
    chain_id: int,
    nonce: int,
    action: str,
    policy_commitment: bytes,
    domain_name: str = "Noncer",
    domain_version: str = "1",
    verifying_contract: str = "0x0000000000000000000000000000000000000000",
) -> dict[str, Any]:
    if len(policy_commitment) != 32:
        raise ValueError("policy_commitment must be 32 bytes")

    return {
        "types": intent_types(),
        "primaryType": "Intent",
        "domain": domain_dict(
            chain_id=chain_id,
            name=domain_name,
            version=domain_version,
            verifying_contract=verifying_contract,
        ),
        "message": {
            "nonce": nonce,
            "action": action,
            # eth-account expects hex string for EIP-712 bytes32 in JSON payload
            "policyCommitment": "0x" + policy_commitment.hex(),
        },
    }


# Calldata: 0x01 ++ abi.encode(uint256,string,bytes32,uint8,bytes32,bytes32)
CALLDATA_VERSION = bytes([1])
