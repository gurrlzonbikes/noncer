# Noncer

Noncer turns actions into **hardware-signed, on-chain intents**.

Execution is not granted by a server.  
It is **derived from cryptographic proof and chain state**.

---

## Model

Execution = signature + chain state + canonical ordering

- **Signature** — who is acting (Ledger-backed key, EIP-712)
- **Chain state** — are they allowed (AccessControl / registry)
- **Ordering** — when (Ethereum account nonce)

There is no API key, no session, and no server-side authorization state.

---

## Mechanism (concrete)

A command runs on the gate only if:

- the intent is signed by the expected key (EIP-712)
- the sender is currently allowed on-chain (`hasRole`)
- `Intent.nonce == tx.nonce`
- the action maps to a fixed local allow-list entry (no shell)

The executor (“gate”) does not decide policy.  
It verifies and executes.

Calldata format (v1):

```text
0x01 || abi.encode(nonce, action, policyCommitment, v, r, s)
```

Watcher verifies:

- recovered signer == `tx.from`
- eligibility on-chain
- nonce equality and sequence
- action → allow-listed argv

Flow:

```text
noncer emit → Ledger (EIP-712 + tx) → chain → noncer-watch → verify → argv
```

On mismatch / invalid input:

```text
[ALARM]
```

---

## Architecture

```text
          Intent.nonce
               │
               ▼
CLI ──sign──► Ledger
               │
               ▼
        tx.nonce (same value)
               │
               ▼
        Blockchain (source of truth)
               │
               ▼
        Watcher verifies:
     Intent.nonce == tx.nonce
```

- CLI builds intent
- Ledger signs typed data + transaction
- Blockchain enforces ordering (EOA nonce)
- Watcher verifies and executes

---

## Authorization model

Authorization is on-chain (registry contract), not server-side:

- `grantRunner(address)` → allow
- `revokeRunner(address)` → revoke

Revocation is a contract state change, not a server call.

---

## Nonce unification

`Intent.nonce == tx.nonce`

There is no separate application counter.

- signer uses `eth_getTransactionCount(..., "pending")`
- watcher validates against observed chain sequence

The chain is the source of truth.

---

## Allow-list (required)

**Default:** `~/.noncer/allowlist.json`

**Override:** `--allowlist` / `NONCER_ALLOWLIST`

Example:

```json
{
  "commands": {
    "echo-demo": ["/bin/echo", "hello"],
    "true-cmd": ["/bin/true"]
  }
}
```

**Optional strict mode:** `NONCER_STRICT_EXECUTABLE=1`

Requires `argv[0]` to exist and be executable.

---

## Usage

### Run watcher (gate)

```bash
noncer-watch --registry-contract 0xYourRegistry
```

### Emit action

```bash
noncer emit \
  --address 0xYOUR_ADDRESS \
  --derivation-path "44'/60'/0'/0/0" \
  --action echo-demo \
  --policy-commitment 0x0000000000000000000000000000000000000000000000000000000000000000
```

### Check next nonce (from RPC)

```bash
noncer nonce --address 0xYOUR_ADDRESS
```

---

## Prerequisites

- Python ≥ 3.10
- Node.js (for Ledger signer)
- Ledger device (Ethereum app, typed data enabled)
- Base Sepolia ETH

**Default RPC:** `https://sepolia.base.org`  
**Chain ID:** `84532`

### Registry deployment

See **`contracts/README.md`**.

- OpenZeppelin AccessControl
- set admin (preferably multisig)
- deploy **NoncerGateRegistry**
- call `grantRunner(0xYourEmitterAddress)`

**Revoke:** `revokeRunner(0xYourEmitterAddress)`

---

## Installation

```bash
git clone https://github.com/<your-org>/noncer.git
cd noncer

python3 -m venv .venv
source .venv/bin/activate

pip install -e .
npm install
```

---

## Environment variables

| Variable | Role |
|----------|------|
| `NONCER_STATE_DIR` | State dir (`~/.noncer`): block cursor, seen txs, expected next nonce |
| `NONCER_ALLOWLIST` | Allow-list path |
| `NONCER_RPC_URL` | RPC endpoint |
| `NONCER_CHAIN_ID` | Chain ID |
| `NONCER_EIP712_*` | Must match between emit and watch |
| `NONCER_VERIFYING_CONTRACT` | EIP-712 domain |
| `NONCER_POLICY_*` | Optional policy binding |
| `NONCER_EXPECTED_POLICY_COMMITMENT` | Optional check |
| `NONCER_REGISTRY_CONTRACT` | Registry address |
| `NONCER_RUNNER_ROLE` | Optional role (default `keccak256("RUNNER")`) |
| `NONCER_GATE_HOST` / `NONCER_GATE_PORT` | Optional HTTP health endpoint |

---

## Threat model (short)

**Dedicated runner EOA**

Address should only emit Noncer transactions. Unexpected calldata or sequence gaps → `[ALARM]`.

**On-chain revocation**

Revocation is explicit (`revokeRunner`). Not automatic by default.

**Local disk is not trusted**

State file is for scanning and dedup only—not a source of truth for nonce or authorization.

---

## When to use

**Use if:**

- wrong person or wrong order running an action is high impact

**Do not use if:**

- standard CI auth (OIDC, etc.) is sufficient
- you need privacy (everything is on-chain)
- you need low latency / high throughput

---

## Properties

- no API keys or shared secrets
- replay-safe (chain nonce)
- auditable (on-chain events)
- no hidden authorization state
- executor is minimal and deterministic

---

## Status

Experimental.

Before production use:

- harden RPC trust
- define registry admin workflow
- define operational response to alarms
