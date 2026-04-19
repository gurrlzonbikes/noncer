"""ABI calldata layout v1 (EIP-712-backed intent packaged for one tx)."""

from __future__ import annotations

from eth_abi import decode  # eth_abi ships with eth-account/web3 stack

from noncer.eip712 import CALLDATA_VERSION, full_typed_message


def _normalize_recovery_v(v: int) -> int:
    """ECDSA recovery id on Ethereum is typically 27/28; some devices emit 0/1."""
    if v in (0, 1):
        return v + 27
    return v


def unpack_v1(calldata_hex: str) -> tuple[int, str, bytes, int, bytes, bytes]:
    """
    Decode Noncer calldata bytes after version prefix.

    Returns:
        nonce, action, policy_commitment (32 bytes), v, r (32 bytes), s (32 bytes).
    """
    raw = bytes.fromhex(calldata_hex[2:] if calldata_hex.startswith("0x") else calldata_hex)

    if len(raw) < 1 + 32 * 5:  # loose lower bound (string has dynamic encoding)
        raise ValueError("calldata too short")

    if raw[:1] != CALLDATA_VERSION:
        raise ValueError(f"unsupported noncer calldata version {raw[:1].hex()}")

    body = raw[1:]
    tup = decode(
        ["uint256", "string", "bytes32", "uint8", "bytes32", "bytes32"],
        body,
    )
    nonce = int(tup[0])
    action = tup[1]
    policy = tup[2]
    v = int(tup[3])
    r = tup[4]
    s = tup[5]

    if len(policy) != 32 or len(r) != 32 or len(s) != 32:
        raise ValueError("invalid element lengths")

    return nonce, action, policy, v, r, s


def recover_signer(
    *,
    chain_id: int,
    nonce: int,
    action: str,
    policy_commitment: bytes,
    v: int,
    r: bytes,
    s: bytes,
    domain_name: str,
    domain_version: str,
    verifying_contract: str,
) -> str:
    """Return checksummed address recovered from EIP-712 signature."""
    from eth_account import Account
    from eth_account.messages import encode_typed_data

    tm = full_typed_message(
        chain_id=chain_id,
        nonce=nonce,
        action=action,
        policy_commitment=policy_commitment,
        domain_name=domain_name,
        domain_version=domain_version,
        verifying_contract=verifying_contract,
    )
    signable = encode_typed_data(full_message=tm)

    ri = int.from_bytes(r, "big")
    si = int.from_bytes(s, "big")
    vn = _normalize_recovery_v(v)
    recovered = Account.recover_message(signable, vrs=(vn, ri, si))
    return recovered
