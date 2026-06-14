#!/usr/bin/env bash
# Honeybee bounty readiness — read-only on-chain + config checks.
# Prints ✅/❌ per requirement. Re-runnable; sends no transactions.
set -u
cd "$(dirname "$0")/.." || exit 1
set -a; . ./.env 2>/dev/null; set +a

SEP="${SEPOLIA_RPC_URL:-https://ethereum-sepolia-rpc.publicnode.com}"
ARC="${ARC_RPC_URL:-https://rpc.testnet.arc.network}"
RES="${ENS_SEPOLIA_PUBLIC_RESOLVER:-0xE99638b40E4Fff0129D56f03b55b6bbC4BBE49b5}"
IDENT="${AGENT_IDENTITY_ADDRESS}"
REG="${ATTESTATION_REGISTRY_ADDRESS}"
AGENT="0x37bDa491084e489883cAaFd9545af2dE31edA8da"
SNODE=0xd2ec6a2dd1dd821df2230bf39617a035bfd76e30e2fd93547eeb2e79ba7be422
ANODE=0x46d702311155417a3e174b3dd3133f83ba0c2433bd5938f2142e1fb66822a5f9

pass(){ echo "  ✅ $1"; }
fail(){ echo "  ❌ $1"; }
chk(){ [ "$1" = "$2" ] && pass "$3" || fail "$3 (got: $1)"; }
nonempty(){ [ -n "$1" ] && [ "$1" != '""' ] && pass "$2" || fail "$2 (empty)"; }
codesize(){ local c; c=$(cast code "$1" --rpc-url "$2" 2>/dev/null); [ "${#c}" -gt 2 ] && pass "$3" || fail "$3 (no bytecode)"; }
lc(){ tr '[:upper:]' '[:lower:]'; }

echo "════════════════════════════════════════════════"
echo " ENS  ($AGENT)"
echo "════════════════════════════════════════════════"
ADDR=$(cast call "$RES" "addr(bytes32)(address)" "$SNODE" --rpc-url "$SEP" 2>/dev/null)
chk "$(echo "$ADDR"|lc)" "$(echo "$AGENT"|lc)" "alpha-trader.honeybee-agents.eth resolves to agent wallet"
nonempty "$(cast call "$RES" 'text(bytes32,string)(string)' "$SNODE" description --rpc-url "$SEP" 2>/dev/null)" "ENS 'description' record set"
nonempty "$(cast call "$RES" 'text(bytes32,string)(string)' "$SNODE" url --rpc-url "$SEP" 2>/dev/null)" "ENS 'url' record set"
nonempty "$(cast call "$RES" 'text(bytes32,string)(string)' "$SNODE" 'honeybee.reputation' --rpc-url "$SEP" 2>/dev/null)" "ENS 'honeybee.reputation' → Arc pointer set"

echo "════════════════════════════════════════════════"
echo " CIRCLE ARC  (chainId ${ARC_CHAIN_ID:-?})"
echo "════════════════════════════════════════════════"
codesize "$IDENT" "$ARC" "AgentIdentity deployed"
codesize "$REG" "$ARC" "AttestationRegistry deployed"
chk "$(cast call "$IDENT" 'addrOf(bytes32)(address)' "$ANODE" --rpc-url "$ARC" 2>/dev/null|lc)" "$(echo "$AGENT"|lc)" "alpha-trader registered on Arc (addrOf==wallet)"
BAL=$(cast balance "$AGENT" --rpc-url "$ARC" 2>/dev/null); [ -n "$BAL" ] && [ "$BAL" != "0" ] && pass "agent wallet funded for gas (USDC native)" || fail "agent wallet has no gas"
for h in 0xe7118251a6cda82ad8357308cb57dba176dc0acc04f10c3d7fb4e5a5b3d5a539 \
         0x2e772399cf74effd8d794352d4495af1ed631e426f7963deadf1efd7bfdaee73 \
         0xa6a3898d873e4830034a4af26cb45b5781056f331a7cf67ad8e0ae9f378be38e; do
  s=$(cast receipt "$h" status --rpc-url "$ARC" 2>/dev/null)
  echo "$s" | grep -q success && pass "tx ${h:0:12}… succeeded" || fail "tx ${h:0:12}… status=$s"
done

echo "════════════════════════════════════════════════"
echo " BLINK (testnet sandbox)"
echo "════════════════════════════════════════════════"
[ -f web/app/api/sign-payment/route.ts ] && pass "Blink signer route present" || fail "Blink signer route missing"
[ -f web/components/BlinkDeposit.tsx ] && pass "Blink deposit UI present" || fail "Blink deposit UI missing"
MID=$(grep -E '^BLINK_MERCHANT_ID=' web/.env.local 2>/dev/null | cut -d= -f2- | tr -d ' ')
if [ -n "$MID" ]; then
  PK=$(curl -sS "https://api-sandbox.blink.cash/v1/merchants/$MID/public-key" 2>/dev/null)
  echo "$PK" | grep -q 'BEGIN PUBLIC KEY' \
    && pass "sandbox merchant active + public key registered ($MID)" \
    || fail "merchant $MID not active at Blink sandbox"
else
  fail "BLINK_MERCHANT_ID not set in web/.env.local"
fi

echo
echo "Done. (transactions: see docs/ARCHITECTURE.md + arcscan/etherscan links)"
