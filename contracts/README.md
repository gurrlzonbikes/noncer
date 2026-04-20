# NoncerGateRegistry (OpenZeppelin AccessControl)

Solidity registry with **`RUNNER_ROLE`** and **`DEFAULT_ADMIN_ROLE`**. Admin grants `grantRunner(addr)` to gate emitters; **`revokeRunner(addr)` is the killswitch** (instant off-chain visibility once mined).

## Compile

```bash
cd contracts
npm install
npm run compile
```

## Deploy (Hardhat network)

Set `ADMIN_ADDRESS` to your multisig or cold wallet (receives `DEFAULT_ADMIN_ROLE`).

Example `contracts/hardhat.config.cjs` networks section (add RPC + keys yourself):

```js
networks: {
  baseSepolia: {
    url: process.env.BASE_SEPOLIA_RPC_URL || "https://sepolia.base.org",
    accounts: process.env.DEPLOYER_PRIVATE_KEY
      ? [process.env.DEPLOYER_PRIVATE_KEY]
      : [],
  },
},
```

Then (deployer pays gas; `ADMIN_ADDRESS` receives admin rights):

```bash
export BASE_SEPOLIA_RPC_URL=https://sepolia.base.org   # or your RPC
export DEPLOYER_PRIVATE_KEY=0x...                     # deployer only; keep offline if possible
ADMIN_ADDRESS=0xYourMultisig npm run deploy-base-sepolia
```

Wire `noncer-watch --registry-contract <deployed> [--runner-role ...]` (default role id matches Solidity `RUNNER_ROLE`). Emit uses Ethereum **account** nonce for EIP-712 `Intent.nonce` (see repo README).

## Ops

1. **`grantRunner(0xExecEmitter)`** — allow the Ledger-derived address that submits intents.
2. **`revokeRunner(0xExecEmitter)`** — killswitch for that identity.
