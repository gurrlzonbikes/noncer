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
| **Execution** | The EIP-712 **`action`** string is an **intent key** only. The gate maps it to a **fixed argv** via a local **allow-list file** — **no shell** (`shell=False`). |

### Calldata v1 (single tx)

Prefix byte `0x01`, then ABI:

`abi.encode(uint256 nonce, string action, bytes32 policyCommitment, uint8 v, bytes32 r, bytes32 s)`

where `v,r,s` are the **EIP-712** signature over the intent (not the tx signature). The gate **recovers** the signer address and requires it to equal `tx.from` (and passes NFT + nonce checks).

---

## Ledger UX (two prompts)

1. **Sign EIP-712 intent** — structured fields on device (`nonce`, `action`, `policyCommitment`, domain). Here **`action`** is the **same string** as the allow-list key (e.g. `scan-staging`).
2. **Sign the EIP-1559 transaction** that carries the packed calldata (may present as data signing / blind depending on firmware).

---

## Architecture

```text
noncer emit  →  Node signer:
                  1) Ledger.signEIP712Message (or hashed fallback)
                  2) pack calldata v1 + Ledger.signTransaction → broadcast

noncer-watch →  decode v1 → ecrecover EIP-712 digest → must match from
               → NFT → application nonce → argv from allow-list JSON
               → GET /nonce for emit
```

---

## Command allow-list (required)

The gate **does not** interpret `action` as a shell command. Create a JSON file (default path: `$NONCER_STATE_DIR/allowlist.json`, usually `~/.noncer/allowlist.json`):

```json
{
  "commands": {
    "echo-demo": ["/bin/echo", "hello"],
    "true-cmd": ["/bin/true"]
  }
}
```

- Keys must match the **`action`** field in the signed intent **exactly** (after trim).
- Values are **argv arrays**: first element is the executable; remaining entries are literal arguments controlled by **you**, not by the signer’s string parsing.

Override path: `--allowlist /path/to/allowlist.json` or env **`NONCER_ALLOWLIST`**.

Optional **`--strict-executable`** (or **`NONCER_STRICT_EXECUTABLE=1`**): require `argv[0]` to exist on disk and be executable (recommended on production gate hosts).

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
| `NONCER_STATE_DIR` | Gate persistence (`~/.noncer`): `gate_state.json`, default **allow-list** path |
| `NONCER_ALLOWLIST` | Path to allow-list JSON (overrides default `<state-dir>/allowlist.json`) |
| `NONCER_STRICT_EXECUTABLE` | `1` / `true`: same as watcher `--strict-executable` |
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
# Ensure ~/.noncer/allowlist.json exists (or pass --allowlist)
noncer-watch --nft-contract 0xYourERC721Address \
  --eip712-name Noncer --eip712-version 1
```

Optional: `--expected-policy-commitment 0x...`, `--strict-executable`.

---

## Emit

Use an **`action`** string that matches an allow-list key:

```bash
noncer emit \
  --address 0xYourAddress \
  --derivation-path "44'/60'/0'/0/0" \
  --action echo-demo \
  --policy-commitment 0x0000000000000000000000000000000000000000000000000000000000000000
```

Use the same domain flags as the watcher if you override defaults.

---

## Revocation

NFT **transfer/burn** updates eligibility on-chain without a separate revoke API.

---

## Status

Experimental. Execution is **argv templates only** (allow-list JSON); extend with tighter policy manifests via `policyCommitment` as needed.
