# Noncer

**Noncer** is a small **gate** in front of a real process on a machine you run. A high-stakes action only runs if a **Ledger**-backed key has signed a structured **intent** (EIP-712), a **public chain** still says the sender is **allowed** via an **AccessControl** registry (`hasRole`), the **EIP-712 `Intent.nonce` equals the Ethereum transaction’s `nonce`** (same EOA counter the network enforces), the signed `action` is only a **key** into a local **allow-list** of fixed `argv` (no shell), and the gate’s local state is **not** a second source of truth for that counter. The design targets **governed automation** without a long-lived **bearer API key** for authorization.

**Revocation and response to anomalies** are **on-chain** (admin / multisig, e.g. `revokeRunner` on the registry). The gate host may **log `[ALARM]`** and must not be the only place that can “turn off” a runner; it should not hold the **admin** key for the registry.

---

## Threat model and design choices (summary)

- **Dedicated runner EOA** — This flow is meant for an address that **only** sends Noncer-shaped self-transactions. **Any** other on-chain use of that key (so **any** unexpected `tx.nonce` / calldata pattern) is treated as **suspicious**: the gate **alarms**; you **revoke** `RUNNER_ROLE` on the registry after review (false positives are acceptable if you prefer that to silent failure).
- **EIP-712 `Intent.nonce` = `tx.nonce`** — The signer uses `eth_getTransactionCount(address, "pending")` for both the typed `Intent` and the broadcast transaction, so the **authoritative sequence** is the **chain’s EOA nonce**, not a separate counter in `gate_state.json` (which is still used for **block cursor** and **deduplication of seen tx hashes** only).
- **Local file is not the security gate** — An attacker with disk access can tamper with `gate_state.json`, but they **cannot** forge the next on-chain nonce without the key. The **next** `tx.nonce` is read from the **RPC** at emit time; the **watcher** checks `unpack`’s nonce against `tx.nonce` and checks **expected** `tx.nonce` from its own record of the last observed runner tx (resynced in `finally` so it follows **mined** chain nonces even when the gate rejects execution).
- **Alarms, not auto-revoke** — Mismatches (bad calldata, `Intent.nonce != tx.nonce`, **sequence gap**) are logged with `[ALARM]`. **Registry revoke** is a separate, on-chain action (automation is your policy, not this package’s default).

It is **opinionated and heavy** on purpose: keys, chain, and a second device flow. That is a bad trade for “run tests on every push” and a reasonable trade for “this run can do real damage or touch real data if it is the wrong person or the wrong order.”

---

## Problem / non-goals

**What it is trying to address**

- Pipelines and agents often get **broad secrets**; anyone with the token can do a lot.
- **Revocation** and “who was allowed when” are easy to lose in a pile of internal configs.
- You may want a **dumb executor** (the gate) that only checks what you can state **from the outside** (signer, on-chain role, EOA nonce, then a **fixed** local command table).

**What it is *not* (use something else)**

- **Not** a drop-in for **OIDC / workload identity** for normal CI or SaaS login at scale.
- **Not** a **privacy** system: txs and addresses are **public**.
- **Not** optimized for **latency** or **volume** (Ledger + RPC).

**When to bother**

If the worst case is “the pipeline turns red,” you probably do not need this shape. If the worst case is “wrong human or wrong order runs **this** binary against **that** environment,” this is one possible stack.

---

## Mechanism (bullet map)

- **Identity:** EIP-712 `Intent(nonce, action, policyCommitment)` **with `nonce` equal to this tx’s Ethereum `nonce`** + broadcast tx → Ledger signs twice (`action` = allow-list **key**, not argv).
- **Live allow:** `hasRole(RUNNER_ROLE, sender)` on **`NoncerGateRegistry`** (**admin** calls `revokeRunner(sender)` — see `contracts/`).
- **Ordering:** Ethereum **account nonce** is the progression counter; gate checks **sequence** vs last observed miner tx per runner and **`Intent.nonce == tx.nonce`**.
- **Execution:** `allowlist.json` maps keys → argv; `subprocess` **without** shell.

**Calldata v1:** `0x01 || abi.encode(nonce, action, policyCommitment, v, r, s)` — gate recovers EIP-712 signer, requires `recover == tx.from`, eligibility, **`Intent.nonce == tx.nonce`**, nonce sequence policy, allow-list argv.

**Flow:** `noncer emit` → Ledger ×2 → Base Sepolia · `noncer-watch` → verify → argv (or **`[ALARM]`**).

---

## Allow-list (required)

Default: `~/.noncer/allowlist.json` · override: `--allowlist` / `NONCER_ALLOWLIST`

```json
{"commands": {"echo-demo": ["/bin/echo", "hello"], "true-cmd": ["/bin/true"]}}
```

Optional: `--strict-executable` / `NONCER_STRICT_EXECUTABLE=1` (require `argv[0]` exists + executable).

---

## Prerequisites

- Python ≥3.10, `npm install` at repo root (Ledger signer), Ledger (Ethereum app, typed data).
- Base Sepolia **gas**; deploy **`NoncerGateRegistry`** and **`grantRunner`** your emitter address.
- Default RPC `https://sepolia.base.org`, chain `84532`.

### Registry deploy

See **`contracts/README.md`**: Hardhat + OpenZeppelin `AccessControl`; constructor sets **admin** (multisig). **`grantRunner(0xEmitter)`**; **`revokeRunner(0xEmitter)`** removes eligibility **on-chain**.

---

## Install

```bash
git clone https://github.com/<your-org>/noncer.git && cd noncer
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
npm install
```

---

## Env (common)

| Var / flag | Role |
|------------|------|
| `NONCER_STATE_DIR` | State dir (`~/.noncer`): block cursor, seen txs, expected next **Ethereum** nonce per runner |
| `NONCER_ALLOWLIST` | Allow-list path |
| `NONCER_RPC_URL` / `NONCER_CHAIN_ID` | RPC / chain (emit + `noncer nonce`) |
| `NONCER_EIP712_*`, `NONCER_VERIFYING_CONTRACT` | Must match between **emit** and **watch** |
| `NONCER_POLICY_*`, `NONCER_EXPECTED_POLICY_COMMITMENT` | Optional policy bytes32 binding |
| `NONCER_REGISTRY_CONTRACT` | Registry address (`--registry-contract`) |
| `NONCER_RUNNER_ROLE` | Optional bytes32 hex for `hasRole` (default `keccak256("RUNNER")`) |
| `NONCER_GATE_HOST` / `NONCER_GATE_PORT` | Optional HTTP **health** only (`/health`) |

---

## Run

**Gate**

```bash
noncer-watch --registry-contract 0xYourDeployedRegistry
```

**Emit** (`--action` = allow-list key). Signer sets **EIP-712 `nonce` = next `eth_getTransactionCount(..., "pending")`** (printed before signing).

```bash
noncer emit --address 0x… --derivation-path "44'/60'/0'/0/0" \
  --action echo-demo \
  --policy-commitment 0x0000000000000000000000000000000000000000000000000000000000000000
```

**Inspect next tx / intent nonce** (RPC only — no gate oracle):

```bash
noncer nonce --address 0x…
```

---

## Status

Experimental — harden RPC trust, `/health` exposure, registry admin workflow, and policy for non-lab use.
