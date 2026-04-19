"""EIP-712 helpers and ABI calldata v1 (no Ledger required)."""

from eth_account import Account
from eth_account.messages import encode_typed_data

from noncer.calldata_v1 import recover_signer, unpack_v1
from noncer.eip712 import CALLDATA_VERSION, full_typed_message


def test_full_typed_message_policy_hex():
    pc = bytes.fromhex("ab" * 32)
    tm = full_typed_message(chain_id=84532, nonce=3, action="echo x", policy_commitment=pc)
    assert tm["message"]["nonce"] == 3
    assert tm["message"]["policyCommitment"] == "0x" + pc.hex()


def test_pack_unpack_abi_roundtrip():
    from eth_abi import encode

    nonce = 5
    action = 'printf "%s" hi'
    policy = bytes.fromhex("cd" * 32)
    v = 28
    r = bytes.fromhex("11" * 32)
    s = bytes.fromhex("22" * 32)

    body = encode(["uint256", "string", "bytes32", "uint8", "bytes32", "bytes32"], [nonce, action, policy, v, r, s])
    calldata = "0x" + CALLDATA_VERSION.hex() + body.hex()

    n2, a2, p2, v2, r2, s2 = unpack_v1(calldata)
    assert n2 == nonce
    assert a2 == action
    assert p2 == policy
    assert v2 == v
    assert r2 == r
    assert s2 == s


def test_recover_roundtrip_local_key():
    acct = Account.create()
    chain_id = 84532
    policy = bytes(32)

    tm = full_typed_message(
        chain_id=chain_id,
        nonce=0,
        action="whoami",
        policy_commitment=policy,
        verifying_contract="0x0000000000000000000000000000000000000000",
    )
    signable = encode_typed_data(full_message=tm)
    signed = acct.sign_message(signable)

    rv = int(signed.r) if hasattr(signed.r, "bit_length") else int(signed.r, 16)
    sv = int(signed.s) if hasattr(signed.s, "bit_length") else int(signed.s, 16)

    recovered = recover_signer(
        chain_id=chain_id,
        nonce=0,
        action="whoami",
        policy_commitment=policy,
        v=signed.v,
        r=rv.to_bytes(32, "big"),
        s=sv.to_bytes(32, "big"),
        domain_name="Noncer",
        domain_version="1",
        verifying_contract="0x0000000000000000000000000000000000000000",
    )
    assert recovered.lower() == acct.address.lower()


def test_recover_wrong_action_fails():
    acct = Account.create()
    tm = full_typed_message(chain_id=1, nonce=1, action="a", policy_commitment=bytes(32))
    signable = encode_typed_data(full_message=tm)
    signed = acct.sign_message(signable)

    rv = int(signed.r) if hasattr(signed.r, "bit_length") else int(signed.r, 16)
    sv = int(signed.s) if hasattr(signed.s, "bit_length") else int(signed.s, 16)

    wrong = recover_signer(
        chain_id=1,
        nonce=1,
        action="b",
        policy_commitment=bytes(32),
        v=signed.v,
        r=rv.to_bytes(32, "big"),
        s=sv.to_bytes(32, "big"),
        domain_name="Noncer",
        domain_version="1",
        verifying_contract="0x0000000000000000000000000000000000000000",
    )
    assert wrong.lower() != acct.address.lower()
