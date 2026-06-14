#!/usr/bin/env bash
# Arc agentic-economy proof — sends 3 REAL Arc testnet transactions:
#   1. research attestation  2. trade attestation  3. agent->agent USDC nanopayment
# Signed by the agent's Privy wallet (auth-key + chain-locked policy) via
# scripts/privy_send.mjs. Calldata built with `cast`; receipts confirmed with `cast`.
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1
set -a; . ./.env 2>/dev/null; set +a

ARC="$ARC_RPC_URL"; REG="$ATTESTATION_REGISTRY_ADDRESS"; EXP="${ARC_EXPLORER_URL%/}"
AW="uhg6icj1ykutum1t9zxywftb"                                            # alpha-trader Privy walletId
AA="0x37bDa491084e489883cAaFd9545af2dE31edA8da"                          # alpha-trader wallet
AN="0x46d702311155417a3e174b3dd3133f83ba0c2433bd5938f2142e1fb66822a5f9"  # alpha-trader identity node
SP="0xc2e90514f1b785f712674A9A85Cf958190C9bF69"                          # sports-analyst wallet
USDC="0x3600000000000000000000000000000000000000"
N=$(date +%s)

send(){ WALLET_ID="$AW" node scripts/privy_send.mjs "$1" "$2"; }
confirm(){ echo "   status=$(cast receipt "$1" status --rpc-url "$ARC" 2>/dev/null) block=$(cast receipt "$1" blockNumber --rpc-url "$ARC" 2>/dev/null)"; echo "   $EXP/tx/$1"; }

echo "1. Research attestation (alpha-trader, Privy-signed)"
H=$(send "$REG" "$(cast calldata 'attestResearch(bytes32,bytes32,string)' "$(cast keccak "research:chess-$N")" "$AN" 'KXCHESSWORLDCHAMPION-GUKESH')")
echo "   tx=$H"; confirm "$H"

echo "2. Trade attestation (alpha-trader, Privy-signed)"
H=$(send "$REG" "$(cast calldata 'attestTrade(bytes32,bytes32,address,string,uint8,uint256,uint256)' "$(cast keccak "trade:chess-$N")" "$AN" "$AA" 'KXCHESSWORLDCHAMPION-GUKESH' 0 470000 25000000)")
echo "   tx=$H"; confirm "$H"

echo "3. x402 agent->agent USDC nanopayment (alpha-trader -> sports-analyst, 0.01 USDC)"
H=$(send "$USDC" "$(cast calldata 'transfer(address,uint256)' "$SP" 10000)")
echo "   tx=$H"; confirm "$H"
