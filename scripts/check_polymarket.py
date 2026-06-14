#!/usr/bin/env python3
"""Read-only Polymarket live-credential check — auth + USDC balance/allowance.

Run from the repo root:
    PYTHONPATH=. .venv/bin/python scripts/check_polymarket.py

Places NO orders. Reads POLYMARKET_* from .env. Use this before any --live run
to confirm: (1) private key + L2 api creds + funder match, (2) the funder holds
USDC, and (3) allowances are set (allowance > 0).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from eth_account import Account  # noqa: E402

from src.venue.wallet import LiveWallet  # noqa: E402
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams  # noqa: E402


def main() -> int:
    try:
        wallet = LiveWallet()
        client = wallet._client_sync()
    except Exception as e:
        print("❌ could not build/authenticate client:", e)
        print("   → check POLYMARKET_PRIVATE_KEY + API_KEY/SECRET/PASSPHRASE (must be derived")
        print("     from that key) + SIGNATURE_TYPE/FUNDER in .env")
        return 1

    funder = wallet._funder or Account.from_key(wallet._pk).address
    print(f"   funder address: {funder}  (sig_type={wallet._sig_type})")

    # Authoritative on-chain read (bypasses the CLOB's cached/lagging view).
    try:
        from web3 import Web3
        rpc = os.getenv("POLYGON_RPC", "https://1rpc.io/matic")
        w3 = Web3(Web3.HTTPProvider(rpc))
        usdce = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        abi = [{"name": "balanceOf", "type": "function", "stateMutability": "view",
                "inputs": [{"name": "o", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]}]
        owner = Web3.to_checksum_address(funder)
        bal = w3.eth.contract(address=usdce, abi=abi).functions.balanceOf(owner).call()
        pol = w3.eth.get_balance(owner)
        print(f"   on-chain (authoritative, {rpc}): USDC.e={bal/1e6}  POL={pol/1e18:.4f}")
    except Exception as e:
        print(f"   on-chain read skipped: {e}")
    print(f"   explorer: https://polygonscan.com/address/{funder}#tokentxns")

    try:
        print("✅ auth OK — api keys on account:", client.get_api_keys())
    except Exception as e:
        print("❌ auth failed (creds/key mismatch?):", e)
        return 1

    ok = True
    try:
        # Force the CLOB to re-read on-chain balances (its view is cached), then read.
        client.update_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        ba = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        print(f"   USDC (collateral): {ba}")
    except Exception as e:
        ok = False
        print(f"   USDC (collateral): error — {e}")
    # CTF (conditional / ERC-1155) balance can't be queried generically — it needs
    # a specific token_id — and its allowance is a blanket operator approval set
    # via update_balance_allowance(CONDITIONAL). Not shown here by design.

    print("\nNext: if balance is ~0 → fund the funder address with USDC.e on Polygon;")
    print("      if allowance is 0 → run update_balance_allowance (see Step 3 in the test guide).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
