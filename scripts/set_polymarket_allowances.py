#!/usr/bin/env python3
"""One-time on-chain allowance setup for a raw-EOA Polymarket wallet.

py-clob-client's update_balance_allowance() only refreshes the CLOB's cached view
— it does NOT send approvals. EOA wallets must approve on-chain themselves:
  - ERC-20  approve()          on USDC.e for each Polymarket exchange spender
  - ERC-1155 setApprovalForAll() on the CTF for each exchange spender
The spender set is read live from the CLOB so it stays correct if contracts change.

Run from repo root (sends REAL transactions, needs a little POL for gas):
    PYTHONPATH=. .venv/bin/python scripts/set_polymarket_allowances.py

Skip this entirely if you use a Polymarket proxy wallet (signature_type 1/2) —
those have allowances handled automatically.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from eth_account import Account  # noqa: E402
from web3 import Web3  # noqa: E402

from py_clob_client.clob_types import AssetType, BalanceAllowanceParams  # noqa: E402
from src.venue.wallet import LiveWallet  # noqa: E402

USDC_E = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
CTF = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
MAX_UINT = (1 << 256) - 1

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"name": "allowance", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
]
ERC1155_ABI = [
    {"name": "setApprovalForAll", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "op", "type": "address"}, {"name": "ok", "type": "bool"}], "outputs": []},
    {"name": "isApprovedForAll", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "o", "type": "address"}, {"name": "op", "type": "address"}],
     "outputs": [{"name": "", "type": "bool"}]},
]


def main() -> int:
    pk = os.getenv("POLYMARKET_PRIVATE_KEY", "").strip()
    if not pk:
        print("POLYMARKET_PRIVATE_KEY not set"); return 1
    pk = pk if pk.startswith("0x") else f"0x{pk}"
    if os.getenv("POLYMARKET_SIGNATURE_TYPE", "0") != "0":
        print("This script is for EOA wallets (SIGNATURE_TYPE=0). Proxy wallets auto-handle allowances.")
        return 1

    rpc = os.getenv("POLYGON_RPC", "https://1rpc.io/matic")  # polygon-rpc.com returned stale balances
    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        print(f"could not connect to Polygon RPC: {rpc}  (set POLYGON_RPC in .env)"); return 1
    acct = Account.from_key(pk)
    owner = acct.address
    print(f"owner (EOA): {owner}   RPC: {rpc}")

    # Discover the exchange spenders live from the CLOB.
    client = LiveWallet()._client_sync()
    ba = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
    spenders = [Web3.to_checksum_address(s) for s in (ba.get("allowances") or {}).keys()]
    if not spenders:
        print("no spender contracts returned by CLOB — aborting"); return 1
    print("exchange spenders:", spenders)

    usdc = w3.eth.contract(address=USDC_E, abi=ERC20_ABI)
    ctf = w3.eth.contract(address=CTF, abi=ERC1155_ABI)

    # Plan only the approvals that aren't already in place.
    todo = []
    for sp in spenders:
        if usdc.functions.allowance(owner, sp).call() < MAX_UINT // 2:
            todo.append(("USDC.e approve", usdc.functions.approve(sp, MAX_UINT)))
        if not ctf.functions.isApprovedForAll(owner, sp).call():
            todo.append(("CTF setApprovalForAll", ctf.functions.setApprovalForAll(sp, True)))

    if not todo:
        print("✅ all allowances already set — nothing to do.")
        client.update_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        return 0

    print(f"\n{len(todo)} approval tx(s) to send (unlimited approval to official Polymarket contracts):")
    for label, _ in todo:
        print("  -", label)
    if input("proceed? [y/N] ").strip().lower() != "y":
        print("aborted."); return 1

    nonce = w3.eth.get_transaction_count(owner)
    gas_price = w3.eth.gas_price
    for label, fn in todo:
        tx = fn.build_transaction({"from": owner, "nonce": nonce, "chainId": 137, "gasPrice": gas_price})
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        except Exception:
            tx["gas"] = 120_000
        signed = acct.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  {label}: sent {h.hex()} — waiting…")
        rcpt = w3.eth.wait_for_transaction_receipt(h, timeout=180)
        print(f"    status={'ok' if rcpt.status == 1 else 'FAILED'} block={rcpt.blockNumber}")
        nonce += 1

    # Refresh the CLOB's cached view so it sees the new allowances.
    client.update_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
    print("\n✅ done — re-run scripts/check_polymarket.py; allowances should now be non-zero.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
