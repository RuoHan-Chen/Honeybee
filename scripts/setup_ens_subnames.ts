/**
 * Issue ENS subnames under honeybee-agents.eth on Sepolia, one per agent
 * in var/agents.json, and set their `addr` record to the agent's Arc address.
 *
 * Result: alpha-trader.honeybee-agents.eth → 0x37bDa491… (resolves via real L1 ENS)
 *
 * Steps per agent:
 *   1. setSubnodeRecord(parentNode, labelhash, owner=registrant, resolver=PublicResolver, ttl=0)
 *   2. resolver.setAddr(node, agentArcAddress)
 *   3. resolver.setText(node, "description", role/desc)
 *   4. resolver.setText(node, "url", explorer link)
 *
 * Env required:
 *   ENS_SEPOLIA_OWNER_KEY            private key of name owner
 *   ENS_SEPOLIA_NAME                 e.g. honeybee-agents.eth
 *   SEPOLIA_RPC_URL                  default https://ethereum-sepolia-rpc.publicnode.com
 *   ENS_SEPOLIA_REGISTRY             default 0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e
 *   ENS_SEPOLIA_PUBLIC_RESOLVER      default 0xE99638b40E4Fff0129D56f03b55b6bbC4BBE49b5
 *
 * Note: parent ownership is held by the NameWrapper after registration. We unwrap
 * (or check) before issuing subnames. If wrapped, we use NameWrapper.setSubnodeRecord.
 */

import "dotenv/config";
import {
  createPublicClient,
  createWalletClient,
  http,
  keccak256,
  namehash,
  toBytes,
  parseAbiItem,
  formatEther,
  encodeFunctionData,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { sepolia } from "viem/chains";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const RPC = process.env.SEPOLIA_RPC_URL ?? "https://ethereum-sepolia-rpc.publicnode.com";
const KEY = process.env.ENS_SEPOLIA_OWNER_KEY;
const PARENT = process.env.ENS_SEPOLIA_NAME ?? "honeybee-agents.eth";
const REGISTRY = (process.env.ENS_SEPOLIA_REGISTRY ?? "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e") as `0x${string}`;
const RESOLVER = (process.env.ENS_SEPOLIA_PUBLIC_RESOLVER ?? "0xE99638b40E4Fff0129D56f03b55b6bbC4BBE49b5") as `0x${string}`;
const NAME_WRAPPER = "0x0635513f179D50A207757E05759CbD106d7dFcE8" as `0x${string}`;
const COIN_TYPE_ETH = 60n;

if (!KEY) {
  console.error("missing ENS_SEPOLIA_OWNER_KEY");
  process.exit(1);
}

const account = privateKeyToAccount(KEY as `0x${string}`);
const pub = createPublicClient({ chain: sepolia, transport: http(RPC) });
const wallet = createWalletClient({ account, chain: sepolia, transport: http(RPC) });

const registryAbi = [
  parseAbiItem("function owner(bytes32 node) view returns (address)"),
  parseAbiItem("function resolver(bytes32 node) view returns (address)"),
  parseAbiItem("function setSubnodeRecord(bytes32 node, bytes32 label, address owner, address resolver, uint64 ttl)"),
  parseAbiItem("function setResolver(bytes32 node, address resolver)"),
] as const;

const wrapperAbi = [
  parseAbiItem("function ownerOf(uint256 id) view returns (address)"),
  parseAbiItem(
    "function setSubnodeRecord(bytes32 parentNode, string label, address owner, address resolver, uint64 ttl, uint32 fuses, uint64 expiry) returns (bytes32)"
  ),
] as const;

const resolverAbi = [
  parseAbiItem("function setAddr(bytes32 node, address a)"),
  parseAbiItem("function setAddr(bytes32 node, uint256 coinType, bytes a)"),
  parseAbiItem("function setText(bytes32 node, string key, string value)"),
  parseAbiItem("function addr(bytes32 node) view returns (address)"),
] as const;

type Agent = {
  label: string;
  role: string;
  description: string;
  address: string;
  explorer: { address: string };
};

async function main() {
  console.log(`signer: ${account.address}`);
  const bal = await pub.getBalance({ address: account.address });
  console.log(`sepolia balance: ${formatEther(bal)} ETH`);

  const rosterPath = resolve(process.cwd(), "var/agents.json");
  const roster = JSON.parse(readFileSync(rosterPath, "utf8"));
  const agents: Agent[] = roster.agents;
  console.log(`roster: ${agents.length} agents from ${rosterPath}`);

  const parentNode = namehash(PARENT);
  console.log(`parent: ${PARENT} → node ${parentNode}`);

  // Who owns the parent in the registry?
  const registryOwner = (await pub.readContract({
    address: REGISTRY,
    abi: registryAbi,
    functionName: "owner",
    args: [parentNode],
  })) as `0x${string}`;
  console.log(`registry owner of ${PARENT}: ${registryOwner}`);

  const isWrapped = registryOwner.toLowerCase() === NAME_WRAPPER.toLowerCase();
  if (isWrapped) {
    console.log("→ name is held by NameWrapper, will use wrapper.setSubnodeRecord");
    const wrapperOwner = (await pub.readContract({
      address: NAME_WRAPPER,
      abi: wrapperAbi,
      functionName: "ownerOf",
      args: [BigInt(parentNode)],
    })) as `0x${string}`;
    console.log(`wrapper ownerOf: ${wrapperOwner}`);
    if (wrapperOwner.toLowerCase() !== account.address.toLowerCase()) {
      console.error(`signer ${account.address} is not the wrapped owner ${wrapperOwner}`);
      process.exit(1);
    }
  } else if (registryOwner.toLowerCase() !== account.address.toLowerCase()) {
    console.error(`signer ${account.address} does not own parent node`);
    process.exit(1);
  }

  for (const a of agents) {
    console.log(`\n── ${a.label}.${PARENT} → ${a.address}`);
    const labelhash = keccak256(toBytes(a.label));
    const subNode = namehash(`${a.label}.${PARENT}`);
    console.log(`  labelhash: ${labelhash}`);
    console.log(`  subnode:   ${subNode}`);

    // Check if subnode already exists with this resolver
    const existingResolver = (await pub.readContract({
      address: REGISTRY,
      abi: registryAbi,
      functionName: "resolver",
      args: [subNode],
    })) as `0x${string}`;

    if (existingResolver.toLowerCase() !== RESOLVER.toLowerCase()) {
      console.log("  → creating subnode with PublicResolver");
      if (isWrapped) {
        const txHash = await wallet.writeContract({
          address: NAME_WRAPPER,
          abi: wrapperAbi,
          functionName: "setSubnodeRecord",
          args: [parentNode, a.label, account.address, RESOLVER, 0n, 0, 0n],
          gas: 300_000n,
        });
        console.log(`    tx: ${txHash}`);
        await pub.waitForTransactionReceipt({ hash: txHash });
      } else {
        const txHash = await wallet.writeContract({
          address: REGISTRY,
          abi: registryAbi,
          functionName: "setSubnodeRecord",
          args: [parentNode, labelhash, account.address, RESOLVER, 0n],
          gas: 200_000n,
        });
        console.log(`    tx: ${txHash}`);
        await pub.waitForTransactionReceipt({ hash: txHash });
      }
    } else {
      console.log("  ✓ subnode already exists with PublicResolver");
    }

    // setAddr (default coin type = ETH)
    const currentAddr = (await pub.readContract({
      address: RESOLVER,
      abi: [parseAbiItem("function addr(bytes32 node) view returns (address)")],
      functionName: "addr",
      args: [subNode],
    })) as `0x${string}`;

    if (currentAddr.toLowerCase() !== a.address.toLowerCase()) {
      console.log(`  → setAddr → ${a.address}`);
      const txHash = await wallet.writeContract({
        address: RESOLVER,
        abi: [parseAbiItem("function setAddr(bytes32 node, address a)")],
        functionName: "setAddr",
        args: [subNode, a.address as `0x${string}`],
        gas: 100_000n,
      });
      console.log(`    tx: ${txHash}`);
      await pub.waitForTransactionReceipt({ hash: txHash });
    } else {
      console.log(`  ✓ addr already set to ${currentAddr}`);
    }

    // setText "description"
    const desc = `${a.role}: ${a.description}`;
    console.log(`  → setText description = "${desc.slice(0, 60)}…"`);
    const descTx = await wallet.writeContract({
      address: RESOLVER,
      abi: resolverAbi,
      functionName: "setText",
      args: [subNode, "description", desc],
      gas: 120_000n,
    });
    console.log(`    tx: ${descTx}`);
    await pub.waitForTransactionReceipt({ hash: descTx });

    // setText "url" → arcscan link
    console.log(`  → setText url = "${a.explorer.address}"`);
    const urlTx = await wallet.writeContract({
      address: RESOLVER,
      abi: resolverAbi,
      functionName: "setText",
      args: [subNode, "url", a.explorer.address],
      gas: 120_000n,
    });
    console.log(`    tx: ${urlTx}`);
    await pub.waitForTransactionReceipt({ hash: urlTx });

    console.log(`  🎉 ${a.label}.${PARENT} resolved on Sepolia → https://sepolia.app.ens.domains/${a.label}.${PARENT}`);
  }

  console.log("\n✅ all agents now have real ENS subnames on Sepolia");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
