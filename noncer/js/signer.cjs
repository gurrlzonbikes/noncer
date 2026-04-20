/**
 * Two-step Ledger flow:
 *   1) EIP-712 clear-sign Intent (nonce, action, policyCommitment)
 *   2) Sign EIP-1559 tx with calldata = 0x01 || abi.encode(..., v, r, s)
 *
 * Stdin: JSON with action, policyCommitment (hex 32 bytes), address,
 *        derivationPath, rpcUrl, chainId, eip712Name, eip712Version, verifyingContract
 *
 * EIP-712 Intent.nonce and the broadcast tx nonce are both set to eth_getTransactionCount(addr, \"pending\")
 * so intent nonce == Ethereum tx nonce (dedicated-runner model).
 *
 * Env: NONCER_MAX_FEE_GWEI, NONCER_GAS_LIMIT
 */
const fs = require("fs");
const TransportNodeHid = require("@ledgerhq/hw-transport-node-hid").default;
const AppEth = require("@ledgerhq/hw-app-eth").default;
const { ethers } = require("ethers");

function envInt(name, fallback) {
  const v = process.env[name];
  if (v === undefined || v === "") return fallback;
  return parseInt(v, 10);
}

function buildTypedData(cfg, intentNonceBig) {
  const chainId = BigInt(cfg.chainId);
  const domain = {
    name: cfg.eip712Name || "Noncer",
    version: cfg.eip712Version || "1",
    chainId,
    verifyingContract: ethers.getAddress(cfg.verifyingContract || ethers.ZeroAddress),
  };

  const policyCommitment = cfg.policyCommitment
    ? ethers.zeroPadValue(ethers.toBeHex(cfg.policyCommitment), 32)
    : ethers.ZeroHash;

  const typesForLedger = {
    EIP712Domain: [
      { name: "name", type: "string" },
      { name: "version", type: "string" },
      { name: "chainId", type: "uint256" },
      { name: "verifyingContract", type: "address" },
    ],
    Intent: [
      { name: "nonce", type: "uint256" },
      { name: "action", type: "string" },
      { name: "policyCommitment", type: "bytes32" },
    ],
  };

  const message = {
    nonce: intentNonceBig,
    action: cfg.action,
    policyCommitment,
  };

  const typedDataForLedger = {
    domain,
    types: typesForLedger,
    primaryType: "Intent",
    message,
  };

  const typesForHash = {
    Intent: typesForLedger.Intent,
  };

  return { domain, typesForHash, typesForLedger, message, policyCommitment, typedDataForLedger };
}

async function sign712(eth, path, typedDataForLedger, domain, typesForHash, message) {
  try {
    return await eth.signEIP712Message(path, typedDataForLedger, false);
  } catch (e) {
    console.warn("⚠️ signEIP712Message failed, trying signEIP712HashedMessage:", e.message || e);
    const domainSep = ethers.TypedDataEncoder.hashDomain(domain).slice(2);
    const structHash = ethers.TypedDataEncoder.hashStruct("Intent", typesForHash, message).slice(2);
    return eth.signEIP712HashedMessage(path, domainSep, structHash);
  }
}

async function main() {
  const raw = fs.readFileSync(0, "utf8");
  const cfg = JSON.parse(raw.trim());

  const {
    address,
    derivationPath,
    action,
    rpcUrl,
    chainId,
  } = cfg;

  if (!address || !derivationPath || action === undefined) {
    console.error("Missing required stdin fields (address, derivationPath, action)");
    process.exit(2);
  }

  const rpc = rpcUrl || process.env.NONCER_RPC_URL || "https://sepolia.base.org";
  const cid = chainId ?? envInt("NONCER_CHAIN_ID", 84532);
  const feeGwei = process.env.NONCER_MAX_FEE_GWEI || "2";
  const gasLimit = envInt("NONCER_GAS_LIMIT", 500000);

  const provider = new ethers.JsonRpcProvider(rpc);
  const txNonce = await provider.getTransactionCount(address, "pending");
  const intentNonceBig = BigInt(txNonce);

  const { domain, typesForHash, typedDataForLedger, message, policyCommitment } = buildTypedData(
    {
      ...cfg,
      chainId: cid,
    },
    intentNonceBig,
  );

  const transport = await TransportNodeHid.create();
  const eth = new AppEth(transport);

  console.error("🔐 Sign EIP-712 intent on device (step 1/2)...");
  const sig = await sign712(eth, derivationPath, typedDataForLedger, domain, typesForHash, message);

  const vNum = typeof sig.v === "string" ? parseInt(sig.v, 16) : sig.v;
  const rHex = sig.r.startsWith("0x") ? sig.r : "0x" + sig.r;
  const sHex = sig.s.startsWith("0x") ? sig.s : "0x" + sig.s;

  const coder = ethers.AbiCoder.defaultAbiCoder();
  const encoded = coder.encode(
    ["uint256", "string", "bytes32", "uint8", "bytes32", "bytes32"],
    [intentNonceBig, action, policyCommitment, vNum, rHex, sHex],
  );

  const data = "0x01" + encoded.slice(2);

  const tx = {
    to: address,
    value: 0,
    data,
    nonce: txNonce, /* same value as EIP-712 Intent.nonce */
    gasLimit,
    maxFeePerGas: ethers.parseUnits(feeGwei, "gwei"),
    maxPriorityFeePerGas: ethers.parseUnits(feeGwei, "gwei"),
    chainId: cid,
  };

  console.error("🔐 Sign transaction on device (step 2/2)...");
  const unsignedTx = ethers.Transaction.from(tx);
  const rawTxHex = unsignedTx.unsignedSerialized.slice(2);
  const txSig = await eth.signTransaction(derivationPath, rawTxHex);

  const signedTx = ethers.Transaction.from({
    ...tx,
    signature: {
      v: parseInt(txSig.v, 16),
      r: "0x" + txSig.r,
      s: "0x" + txSig.s,
    },
  });

  const txResponse = await provider.broadcastTransaction(signedTx.serialized);
  console.log("✅ TX sent:", txResponse.hash);
}

main().catch((err) => {
  console.error("❌ Signer error:", err);
  process.exit(1);
});
