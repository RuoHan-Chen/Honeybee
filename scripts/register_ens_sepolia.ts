/**
 * Register an ENS name on Sepolia via the TestnetV1PremigrationRegistrar.
 *
 * Sepolia is mid-ENS-v2 migration. The two "documented" controllers
 * (0xfb3c… and the legacy 0x7e02…) are NOT approved on the BaseRegistrar
 * right now, so register() reverts. The contract that actually works is the
 * premigration registrar at 0xdf60C561Ca35AD3C89D24BbA854654b1c3477078,
 * which:
 *   - is the only address approved as a `controller` on BaseRegistrar
 *   - registrations are FREE (value=0)
 *   - no commit/reveal — single-tx register
 *   - MIN_REGISTRATION_DURATION = 36028800s (~417 days)
 *
 * register signature (selector 0xef9c8805):
 *   register((string label,address owner,uint256 duration,bytes32 secret,
 *            address resolver,bytes[] data,uint8 reverseRecord,bytes32 referrer))
 *
 * Env:
 *   SEPOLIA_RPC_URL          default https://ethereum-sepolia-rpc.publicnode.com
 *   SEPOLIA_REGISTRANT_KEY   private key of registrant
 *   ENS_LABEL                e.g. "honeybee-agents"
 *   ENS_DURATION_SECS        default 36028800
 */

import "dotenv/config";
import {
  createPublicClient,
  createWalletClient,
  http,
  keccak256,
  parseAbiItem,
  stringToBytes,
  formatEther,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { sepolia } from "viem/chains";

const RPC = process.env.SEPOLIA_RPC_URL ?? "https://ethereum-sepolia-rpc.publicnode.com";
const KEY = process.env.SEPOLIA_REGISTRANT_KEY;
const LABEL = process.env.ENS_LABEL ?? "honeybee-agents";
const DURATION = BigInt(process.env.ENS_DURATION_SECS ?? "36028800");
const REGISTRAR = "0xdf60C561Ca35AD3C89D24BbA854654b1c3477078" as const;
const RESOLVER = "0xE99638b40E4Fff0129D56f03b55b6bbC4BBE49b5" as const; // PublicResolver
const BASE_REGISTRAR = "0x57f1887a8bf19b14fc0df6fd9b2acc9af147ea85" as const;

if (!KEY) {
  console.error("missing SEPOLIA_REGISTRANT_KEY");
  process.exit(1);
}

const account = privateKeyToAccount(KEY as `0x${string}`);
const pub = createPublicClient({ chain: sepolia, transport: http(RPC) });
const wallet = createWalletClient({ account, chain: sepolia, transport: http(RPC) });

const registrarAbi = [
  parseAbiItem(
    "function register((string label,address owner,uint256 duration,bytes32 secret,address resolver,bytes[] data,uint8 reverseRecord,bytes32 referrer) registration) payable"
  ),
  parseAbiItem("function MIN_REGISTRATION_DURATION() view returns (uint256)"),
] as const;

const baseAbi = [
  parseAbiItem("function available(uint256 id) view returns (bool)"),
  parseAbiItem("function ownerOf(uint256 id) view returns (address)"),
] as const;

async function main() {
  console.log(`registrant: ${account.address}`);
  console.log(`label: ${LABEL}.eth, duration: ${DURATION}s (${Number(DURATION) / 86400} days)`);
  console.log(`registrar: ${REGISTRAR} (TestnetV1PremigrationRegistrar)`);

  const balance = await pub.getBalance({ address: account.address });
  console.log(`sepolia balance: ${formatEther(balance)} ETH`);

  const minDuration = (await pub.readContract({
    address: REGISTRAR,
    abi: registrarAbi,
    functionName: "MIN_REGISTRATION_DURATION",
  })) as bigint;
  if (DURATION < minDuration) {
    console.error(`duration ${DURATION} < minimum ${minDuration} (${Number(minDuration) / 86400} days)`);
    process.exit(1);
  }
  console.log(`✓ duration above minimum (${minDuration}s)`);

  const labelhash = keccak256(stringToBytes(LABEL));
  const tokenId = BigInt(labelhash);
  const available = await pub.readContract({
    address: BASE_REGISTRAR,
    abi: baseAbi,
    functionName: "available",
    args: [tokenId],
  });
  if (!available) {
    const owner = (await pub.readContract({
      address: BASE_REGISTRAR,
      abi: baseAbi,
      functionName: "ownerOf",
      args: [tokenId],
    })) as `0x${string}`;
    console.log(`${LABEL}.eth already registered, owner: ${owner}`);
    if (owner.toLowerCase() === account.address.toLowerCase()) {
      console.log(`✓ already owned by us, skipping`);
      return;
    }
    console.error(`owned by someone else, aborting`);
    process.exit(1);
  }
  console.log(`✓ ${LABEL}.eth is available`);

  const secret = keccak256(stringToBytes(`${LABEL}-${Date.now()}`));
  const registration = {
    label: LABEL,
    owner: account.address,
    duration: DURATION,
    secret,
    resolver: RESOLVER,
    data: [] as `0x${string}`[],
    reverseRecord: 0,
    referrer: "0x0000000000000000000000000000000000000000000000000000000000000000" as const,
  };

  console.log("\n→ submitting register tx (free)…");
  const registerHash = await wallet.writeContract({
    address: REGISTRAR,
    abi: registrarAbi,
    functionName: "register",
    args: [registration],
    value: 0n,
    gas: 500_000n,
  });
  console.log(`register tx: ${registerHash}`);
  const receipt = await pub.waitForTransactionReceipt({ hash: registerHash });
  if (receipt.status !== "success") {
    console.error(`register tx FAILED in block ${receipt.blockNumber}`);
    process.exit(1);
  }
  console.log(`✓ registered in block ${receipt.blockNumber}, gas used ${receipt.gasUsed}`);

  console.log(`\n🎉 ${LABEL}.eth registered on Sepolia`);
  console.log(`   owner: ${account.address}`);
  console.log(`   resolver: ${RESOLVER}`);
  console.log(`   view: https://sepolia.app.ens.domains/${LABEL}.eth`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
