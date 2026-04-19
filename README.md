# Noncer

**High-stakes / low-frequency automation gate:** run a command only when a **Ledger-signed EIP-712 intent** matches on-chain **identity** (recoverable signature), **eligibility** (ERC-721 balance > 0), and the gate’s **monotonic application nonce**.

No API keys. The trust model is **hardware key + structured signing + on-chain eligibility + explicit sequence** (not long-lived CI secrets).

---

## Model

| Piece | Role |
|--------|------|
| **Intent (EIP-712)** | Typed data: `Intent(nonce, action, policyCommitment)` under domain `Noncer` / chainId / `verifyingContract` — shown on Ledger during **step 1** |
| **Tx** | Self-transfer whose `data` is **ABI v1** (see below); signed on Ledger **step 2** |
| **Eligibility** | `balanceOf(sender) > 0` for a configured NFT |
| **Nonce** | Application nonce in the typed message must equal gate state; incremented **only after successful execution** |
| **Replay** | Each mined tx handled **once** (persisted tx-hash set) |

### Calldata v1 (single tx)

Prefix byte `0x01`, then ABI:

`abi.encode(uint256 nonce, string action, bytes32 policyCommitment, uint8 v, bytes32 r, bytes32 s)`

where `v,r,s` are the **EIP-712** signature over the intent (not the tx signature). The gate **recovers** the signer address and requires it to equal `tx.from` (and passes NFT + nonce checks).

---

## Ledger UX (two prompts)

1. **Sign EIP-712 intent** — structured fields on device (`nonce`, `action`, `policyCommitment`, domain).
2. **Sign the EIP-1559 transaction** that carries the packed calldata (may present as data signing / blind depending on firmware).

---

## Architecture

```text
noncer emit  →  Node signer:
                  1) Ledger.signEIP712Message (or hashed fallback)
                  2) pack calldata v1 + Ledger.signTransaction → broadcast

noncer-watch →  decode v1 → ecrecover EIP-712 digest → must match from
               → NFT → application nonce → subprocess (demo)
               → GET /nonce for emit
```

Execution uses `subprocess` with **`shell=True`** — demo only; use argv allow-lists for real use.

---

## Prerequisites

- **Python** ≥ 3.10, **Node.js** + `npm install` at repo root (Ledger + `ethers`).
- Ledger **Ethereum** app; enable **contract / typed data** signing per device docs.
- **NFT** on **Base Sepolia** (chain id **84532** default).
- RPC URL (default `https://sepolia.base.org`).

---

## Install

```bash
git clone https://github.com/<your-org>/noncer.git
cd noncer

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

npm install
```

---

## Configure

Match **EIP-712 domain** between CLI and watcher (`name`, `version`, `chainId`, `verifyingContract`).

| Env / flag | Meaning |
|------------|---------|
| `NONCER_STATE_DIR` | Gate persistence (`~/.noncer`): `gate_state.json` |
| `NONCER_RPC_URL` | HTTP RPC |
| `NONCER_CHAIN_ID` | Default `84532` (Base Sepolia) |
| `NONCER_GATE_URL` | CLI `GET /nonce` target (default `http://127.0.0.1:3090`) |
| `NONCER_EIP712_NAME` / `NONCER_EIP712_VERSION` | Domain (defaults `Noncer` / `1`) |
| `NONCER_VERIFYING_CONTRACT` | EIP-712 `verifyingContract` (default zero address) |
| `NONCER_POLICY_COMMITMENT` | Default `bytes32` for CLI (64 hex chars); manifest hash |
| `NONCER_EXPECTED_POLICY_COMMITMENT` | If set on watcher, intent must use this **exact** `policyCommitment` |

---

## Run the gate

```bash
noncer-watch --nft-contract 0xYourERC721Address \
  --eip712-name Noncer --eip712-version 1
```

Optional: `--expected-policy-commitment 0x...` to enforce a manifest hash.

---

## Emit

```bash
noncer emit \
  --address 0xYourAddress \
  --derivation-path "44'/60'/0'/0/0" \
  --action 'echo hello' \
  --policy-commitment 0x0000000000000000000000000000000000000000000000000000000000000000
```

Use the same domain flags as the watcher if you override defaults.

---

## Revocation

NFT **transfer/burn** updates eligibility on-chain without a separate revoke API.

---

## Status

Experimental. Next hardening steps: fixed command templates, no shell, optional **policy allow-list** file keyed by `policyCommitment`.
