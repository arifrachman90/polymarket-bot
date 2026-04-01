#!/usr/bin/env python3
"""
Chat YES/NO bridge -> execution plan JSON.

Tujuan: bikin input chat sesederhana mungkin:
- YES
- NO
- YES PSG 10
- NO Arsenal 5

Output: file plan JSON siap diteruskan ke executor remote.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from signal_dryrun import (
    Signal,
    auto_resolve_market,
    gamma_fetch_candidate_markets,
    make_plan,
)


def parse_chat_signal(text: str) -> tuple[str, Optional[str], Optional[float]]:
    raw = text.strip()
    if not raw:
        raise ValueError("Signal kosong")

    m = re.match(r"^(YES|NO)(?:\s+([A-Za-z0-9 .\-]+?))?(?:\s+(\d+(?:\.\d+)?))?$", raw, flags=re.IGNORECASE)
    if not m:
        raise ValueError("Format tidak valid. Contoh: YES PSG 10")

    side = m.group(1).upper()
    team = m.group(2).strip() if m.group(2) else None
    stake = float(m.group(3)) if m.group(3) else None
    return side, team, stake


def market_to_signal(side: str, team_hint: str, question: str) -> Signal:
    # Parser existing butuh format home vs away + pick
    # team_hint dipakai sebagai pick; home/away dummy agar auto_resolve jalan via pick+teams in question
    # Kita buat best-effort dari question "A vs B"
    q = question.strip()
    vs = re.split(r"\s+vs\s+", q, flags=re.IGNORECASE)
    if len(vs) >= 2:
        home = vs[0].strip()
        away = vs[1].strip()
    else:
        home = team_hint
        away = "Opponent"

    pick = team_hint if side == "YES" else "No"
    return Signal(raw=f"{home} vs {away} | pick: {pick}", home=home, away=away, pick=pick)


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert chat YES/NO text into remote exec plan")
    ap.add_argument("--text", required=True, help="Signal text, contoh: YES PSG 10")
    ap.add_argument("--default-stake", type=float, default=1.0)
    ap.add_argument("--scan-limit", type=int, default=1200)
    ap.add_argument("--market-question", default="", help="Konteks market aktif (opsional), contoh: PSG vs Toulouse")
    ap.add_argument("--idempotency-prefix", default="tg")
    ap.add_argument("--json-out", required=True)
    args = ap.parse_args()

    side, team_hint, stake = parse_chat_signal(args.text)
    stake_usd = stake if stake is not None else args.default_stake

    if not team_hint and not args.market_question:
        raise SystemExit("Perlu team hint atau --market-question. Contoh: YES PSG 10")

    # Build synthetic signal for existing resolver
    signal = market_to_signal(side, team_hint or "Yes", args.market_question or f"{team_hint} vs Opponent")

    candidates = gamma_fetch_candidate_markets(limit_total=args.scan_limit)
    market_item, token_id, reason = auto_resolve_market(signal, candidates)

    plan = make_plan(
        signal=signal,
        stake_usd=stake_usd,
        max_spread_cents=3,
        market_item=market_item,
        token_id=token_id,
        ready_status="READY_REMOTE_EXEC",
        max_slippage_pct=2.0,
        idempotency_prefix=args.idempotency_prefix,
        signal_index=1,
    )

    # side override from chat
    plan.side = "BUY_OUTCOME"
    if side == "NO":
        plan.reason = f"{plan.reason}; side=NO (mapped by outcome resolve)"
    if reason:
        plan.reason = f"{plan.reason}; {reason}"

    out: Dict[str, Any] = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "telegram",
        "status": plan.status,
        "signals": [
            {
                "chat_text": args.text,
                "side": side,
                "team_hint": team_hint,
                "stake_usd": stake_usd,
            }
        ],
        "plans": [plan.__dict__],
    }

    Path(args.json_out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {args.json_out} | status={plan.status} | reason={plan.reason}")


if __name__ == "__main__":
    main()
