#!/usr/bin/env python3
import json
import math
import os
import sys
import time
from pathlib import Path

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs

POSITIONS_URL = "https://data-api.polymarket.com/positions"
PROXY = os.getenv("POLY_FUNDER", "").strip()
STOP_LOSS_PCT = float(os.getenv("POLY_STOP_LOSS_PCT", "-25"))
POLL_SECONDS = int(os.getenv("POLY_STOPLOSS_POLL_SECONDS", "45"))
MIN_EXIT_PRICE = float(os.getenv("POLY_MIN_EXIT_PRICE", "0.05"))
TAKE_PROFIT_ARM_PCT = float(os.getenv("POLY_TP_ARM_PCT", "18"))
TRAILING_GIVEBACK_PCT = float(os.getenv("POLY_TP_GIVEBACK_PCT", "8"))
STATE_PATH = Path(os.getenv("POLY_STOPLOSS_STATE", "/root/polymarket-bot/stoploss_state.json"))


def make_client() -> ClobClient:
    host = os.getenv("POLY_HOST", "https://clob.polymarket.com")
    chain_id = int(os.getenv("POLY_CHAIN_ID", "137"))
    signature_type = int(os.getenv("POLY_SIGNATURE_TYPE", "2"))
    key = os.getenv("POLY_PK", "").strip()
    funder = os.getenv("POLY_FUNDER", "").strip()
    creds = None
    if os.getenv("POLY_API_KEY") and os.getenv("POLY_API_SECRET") and os.getenv("POLY_API_PASSPHRASE"):
        creds = ApiCreds(
            api_key=os.getenv("POLY_API_KEY", "").strip(),
            api_secret=os.getenv("POLY_API_SECRET", "").strip(),
            api_passphrase=os.getenv("POLY_API_PASSPHRASE", "").strip(),
        )
    client = ClobClient(host, chain_id=chain_id, key=key, creds=creds, signature_type=signature_type, funder=funder)
    if creds is None:
        derived = client.derive_api_key()
        client.set_api_creds(derived)
    return client


def load_state():
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text())
            data.setdefault("closed", {})
            data.setdefault("peak_pnl", {})
            return data
        except Exception:
            return {"closed": {}, "peak_pnl": {}}
    return {"closed": {}, "peak_pnl": {}}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))


def fetch_positions():
    r = requests.get(POSITIONS_URL, params={"user": PROXY, "sizeThreshold": 0}, timeout=30)
    r.raise_for_status()
    return r.json()


def pick_exit_price(client: ClobClient, token_id: str, cur_price: float, mode: str) -> float | None:
    book = client.get_order_book(token_id)
    bids = getattr(book, "bids", None) or []
    if not bids:
        return None
    prices = [float(b.price) for b in bids[:8] if float(b.price) > 0]
    if not prices:
        return None
    best_bid = prices[0]
    if best_bid < MIN_EXIT_PRICE and cur_price >= MIN_EXIT_PRICE:
        return None
    if mode == "STOP_LOSS":
        floor = max(MIN_EXIT_PRICE, round(cur_price * 0.85, 4))
    else:
        floor = max(MIN_EXIT_PRICE, round(cur_price * 0.92, 4))
    viable = [p for p in prices if p >= floor]
    return viable[0] if viable else None


def should_take_profit(pnl: float, peak_pnl: float) -> bool:
    if peak_pnl < TAKE_PROFIT_ARM_PCT:
        return False
    return pnl <= (peak_pnl - TRAILING_GIVEBACK_PCT)


def try_close_position(client: ClobClient, pos: dict, state: dict):
    token_id = str(pos.get("asset") or "")
    slug = pos.get("slug") or token_id
    if state["closed"].get(token_id):
        return None

    size = float(pos.get("size") or 0)
    cur_price = float(pos.get("curPrice") or 0)
    pnl = float(pos.get("percentPnl") or 0)
    outcome = pos.get("outcome")
    if size <= 0:
        return None

    prev_peak = float(state["peak_pnl"].get(token_id, pnl))
    peak_pnl = max(prev_peak, pnl)
    state["peak_pnl"][token_id] = peak_pnl
    save_state(state)

    mode = None
    if pnl <= STOP_LOSS_PCT:
        mode = "STOP_LOSS"
    elif should_take_profit(pnl, peak_pnl):
        mode = "TAKE_PROFIT"
    else:
        return None

    px = pick_exit_price(client, token_id, cur_price, mode=mode)
    if px is None:
        return {
            "slug": slug,
            "token_id": token_id,
            "action": f"HOLD_NO_SAFE_BID_{mode}",
            "cur_price": cur_price,
            "pnl": pnl,
            "peak_pnl": peak_pnl,
        }

    size = math.floor(size * 10000) / 10000
    order_args = OrderArgs(token_id=token_id, price=px, size=size, side="SELL")
    signed = client.create_order(order_args)
    posted = client.post_order(signed)
    state["closed"][token_id] = {
        "slug": slug,
        "outcome": outcome,
        "posted": posted,
        "price": px,
        "size": size,
        "pnl": pnl,
        "peak_pnl": peak_pnl,
        "mode": mode,
        "ts": time.time(),
    }
    save_state(state)
    return {
        "slug": slug,
        "token_id": token_id,
        "action": f"SELL_POSTED_{mode}",
        "price": px,
        "size": size,
        "pnl": pnl,
        "peak_pnl": peak_pnl,
        "posted": posted,
    }


def main():
    if not PROXY:
        raise SystemExit("POLY_FUNDER wajib di-set")
    once = "--once" in sys.argv
    state = load_state()
    client = make_client()
    while True:
        try:
            positions = fetch_positions()
            for pos in positions:
                try:
                    res = try_close_position(client, pos, state)
                    if res:
                        print(json.dumps(res, ensure_ascii=False), flush=True)
                except Exception as e:
                    print(json.dumps({"slug": pos.get("slug"), "error": str(e)}, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"loop_error": str(e)}, ensure_ascii=False), flush=True)
        if once:
            break
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
