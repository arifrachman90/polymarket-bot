#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType


def load_env_file(path: str) -> None:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"env file not found: {path}")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def make_client() -> ClobClient:
    host = os.getenv("POLY_HOST", "https://clob.polymarket.com")
    chain_id = int(os.getenv("POLY_CHAIN_ID", "137"))
    signature_type = int(os.getenv("POLY_SIGNATURE_TYPE", "1"))
    key = os.getenv("POLY_PK", "").strip()
    funder = os.getenv("POLY_FUNDER", "").strip()
    if not key or not funder:
        raise SystemExit("POLY_PK dan POLY_FUNDER wajib di-set")

    creds = None
    if os.getenv("POLY_API_KEY") and os.getenv("POLY_API_SECRET") and os.getenv("POLY_API_PASSPHRASE"):
        creds = ApiCreds(
            api_key=os.getenv("POLY_API_KEY", "").strip(),
            api_secret=os.getenv("POLY_API_SECRET", "").strip(),
            api_passphrase=os.getenv("POLY_API_PASSPHRASE", "").strip(),
        )

    client = ClobClient(
        host,
        chain_id=chain_id,
        key=key,
        creds=creds,
        signature_type=signature_type,
        funder=funder,
    )
    if creds is None:
        derived = client.derive_api_key()
        client.set_api_creds(derived)
    return client


def try_call(label, fn):
    try:
        return {"ok": True, "value": fn()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default="")
    ap.add_argument("--update-allowance", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    out = {
        "env": {
            "host": os.getenv("POLY_HOST", "https://clob.polymarket.com"),
            "chain_id": os.getenv("POLY_CHAIN_ID", "137"),
            "signature_type": os.getenv("POLY_SIGNATURE_TYPE", "1"),
            "has_pk": bool(os.getenv("POLY_PK", "").strip()),
            "funder": os.getenv("POLY_FUNDER", "").strip(),
        }
    }

    client = make_client()
    out["collateral_address"] = client.get_collateral_address()

    collateral_params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    conditional_params = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL)

    out["collateral_balance_allowance"] = try_call(
        "collateral", lambda: client.get_balance_allowance(collateral_params)
    )
    out["conditional_balance_allowance"] = try_call(
        "conditional", lambda: client.get_balance_allowance(conditional_params)
    )

    if args.update_allowance:
        out["update_collateral_allowance"] = try_call(
            "update_collateral", lambda: client.update_balance_allowance(collateral_params)
        )
        out["update_conditional_allowance"] = try_call(
            "update_conditional", lambda: client.update_balance_allowance(conditional_params)
        )

    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(out)


if __name__ == "__main__":
    main()
