# Noncer

**High-stakes / low-frequency automation gate:** run a command only when a **Ledger-signed** on-chain intent is valid, the sender is **eligible** (ERC-721 balance > 0), and the **application nonce** matches the gate’s **monotonic** counter.

No API keys. The trust model is **hardware key + on-chain eligibility + explicit sequence** (not long-lived CI secrets).

---

## Model

| Piece | Role |
|--------|------|
| **Identity** | Ethereum key on **Ledger** (tx signature) |
| **Eligibility** | On-chain: `balanceOf(sender) > 0` for a configured NFT |
| **Nonce** | **Application** nonce: gate stores `expected_nonce` per address; intent JSON must match; gate increments **only after successful execution** |
| **Replay** | Each mined tx handled **once** (persisted tx-hash set); wrong nonce rejected without advancing |

Calldata is UTF-8 JSON:

```json
{"nonce":0,"action":"echo hello"}
```

---

## Architecture

```text
noncer emit  →  Ledger (node/noncer signer)  →  Base Sepolia RPC
                                                   ↓
                                         self-transfer tx, data = intent JSON

noncer-watch →  scans blocks → decode intent → NFT check → nonce check → subprocess (demo)
               ↳ HTTP GET /nonce  so emit can fetch expected nonce
```

Execution uses `subprocess` with **`shell=True`** — appropriate for demos only; tighten before production (allow-listed binaries, argv lists, timeouts).

---

## Prerequisites

- **Python** ≥ 3.10, **Node.js** + `npm install` at repo root (Ledger signing).
- Ledger with **Ethereum** app; payloads use **generic calldata** — you may need **blind signing** enabled for review on device.
- **NFT contract** on **Base Sepolia** (chain id **84532** by default).
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

| Env / flag | Meaning |
|------------|---------|
| `NONCER_STATE_DIR` | Gate persistence (`~/.noncer` default): `gate_state.json` |
| `NONCER_RPC_URL` | HTTP RPC for watcher + signer |
| `NONCER_CHAIN_ID` | Default `84532` (Base Sepolia) |
| `NONCER_GATE_URL` | CLI queries `GET /nonce` here (default `http://127.0.0.1:3090`) |
| `NONCER_GATE_HOST` / `NONCER_GATE_PORT` | Watcher binds HTTP gate (default `127.0.0.1:3090`) |

---

## Run the gate (watcher)

```bash
noncer-watch --nft-contract 0xYourERC721Address
```

Optional: `--rpc-url`, `--state-dir`, `--gate-port`, `--no-http` (HTTP off; then use `--nonce` on every `emit`).

---

## Emit an intent

With the watcher running (so `/nonce` is available):

```bash
noncer emit \
  --address 0xYourAddress \
  --derivation-path "44'/60'/0'/0/0" \
  --action 'echo hello'
```

Or explicitly:

```bash
noncer nonce --address 0xYourAddress
noncer emit ... --nonce 0 --action 'echo hello'
```

---

## Revocation / delegation

Changing **NFT ownership** (mint, transfer, burn) updates eligibility **on-chain**. No separate “revoke” endpoint is required for that authorization model.

---

## Status

Experimental research code: hardened policy (capabilities, bounded commands, Fnox-facing adapters) is left to callers building on this gate.
