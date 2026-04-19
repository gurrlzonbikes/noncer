/**
 * Ledger signer: broadcasts a self-transfer tx whose calldata is UTF-8 payload (intent JSON).
 *
 * Env:
 *   NONCER_RPC_URL       — HTTP RPC (required if not using default)
 *   NONCER_CHAIN_ID      — EIP-155 chain id (default 84532 Base Sepolia)
 *   NONCER_MAX_FEE_GWEI  — maxFeePerGas / maxPriorityFeePerGas (default 2)
 *   NONCER_GAS_LIMIT     — gas limit (default 300000)
 *
 * Args: payload_json_string address derivation_path
 */
const TransportNodeHid = require("@ledgerhq/hw-transport-node-hid").default;
const AppEth = require("@ledgerhq/hw-app-eth").default;
const { ethers } = require("ethers");

function envInt(name, fallback) {
  const v = process.env[name];
  if (v === undefined || v === "") return fallback;
  return parseInt(v, 10);
}

async function main() {
  const payload = process.argv[2];
  const address = process.argv[3];
  const derivationPath = process.argv[4];

  if (!payload || !address || !derivationPath) {
    console.error("Usage: node signer.cjs <payload_json> <address> <derivation_path>");
    process.exit(2);
  }

  const rpc = process.env.NONCER_RPC_URL || "https://sepolia.base.org";
  const chainId = envInt("NONCER_CHAIN_ID", 84532);
  const feeGwei = process.env.NONCER_MAX_FEE_GWEI || "2";
  const gasLimit = envInt("NONCER_GAS_LIMIT", 300000);

  const provider = new ethers.JsonRpcProvider(rpc);
  const nonce = await provider.getTransactionCount(address);

  const tx = {
    to: address,
    value: 0,
    data: ethers.hexlify(ethers.toUtf8Bytes(payload)),
    nonce,
    gasLimit,
    maxFeePerGas: ethers.parseUnits(feeGwei, "gwei"),
    maxPriorityFeePerGas: ethers.parseUnits(feeGwei, "gwei"),
    chainId,
  };

  const transport = await TransportNodeHid.create();
  const eth = new AppEth(transport);

  const unsignedTx = ethers.Transaction.from(tx);
  const rawTxHex = unsignedTx.unsignedSerialized.slice(2);

  const sig = await eth.signTransaction(derivationPath, rawTxHex);

  const signedTx = ethers.Transaction.from({
    ...tx,
    signature: {
      v: parseInt(sig.v, 16),
      r: "0x" + sig.r,
      s: "0x" + sig.s,
    },
  });

  const serialized = signedTx.serialized;
  const txResponse = await provider.broadcastTransaction(serialized);

  console.log("✅ TX sent:", txResponse.hash);
}

main().catch((err) => {
  console.error("❌ Signer error:", err);
  process.exit(1);
});
