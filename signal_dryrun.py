#!/usr/bin/env python3
"""
Signal -> Order Plan (DRY RUN)

Tujuan:
- Terima input sederhana seperti:
  MU vs BARCA | pick: BARCA
  ARSENAL VS MAN CITY - arsenal win
- Parse jadi struktur signal
- Resolve ke katalog lokal (opsional)
- Hasilkan rencana order (tanpa kirim order ke Polymarket)

Catatan:
- Ini DRY RUN ONLY (tidak trade sungguhan).
- Untuk LIVE mode nanti, tinggal sambungkan planner ini ke executor CLOB.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


@dataclass
class Signal:
    raw: str
    home: str
    away: str
    pick: str
    market_type: str = "winner_3way"


@dataclass
class OrderPlan:
    home: str
    away: str
    pick: str
    side: str
    stake_usd: float
    max_spread_cents: int
    status: str
    reason: str
    market_slug: Optional[str] = None
    token_id: Optional[str] = None
    max_slippage_pct: float = 2.0
    idempotency_key: Optional[str] = None


TEAM_ALIASES = {
    "mu": "manchester united",
    "man utd": "manchester united",
    "man united": "manchester united",
    "barca": "barcelona",
    "mci": "manchester city",
    "man city": "manchester city",
    "psg": "paris saint germain",
    "tou": "toulouse",
    "ars": "arsenal",
}


def normalize_team(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    s = re.sub(r"\s+", " ", s)
    return TEAM_ALIASES.get(s, s)


def parse_line(line: str) -> Optional[Signal]:
    original = line.strip()
    if not original:
        return None

    # remove numeric prefix: "1. ..."
    original = re.sub(r"^\d+\.?\s*", "", original)

    # format A: "MU vs BARCA | pick: BARCA"
    m = re.match(
        r"(?P<home>.+?)\s+vs\s+(?P<away>.+?)\s*(?:\||-|,)\s*(?:pick\s*:\s*)?(?P<pick>.+)$",
        original,
        flags=re.IGNORECASE,
    )
    if m:
        return Signal(
            raw=line,
            home=m.group("home").strip(),
            away=m.group("away").strip(),
            pick=re.sub(r"\bwin\b", "", m.group("pick"), flags=re.IGNORECASE).strip(),
        )

    # format B: "MU VS BARCA" and no explicit pick -> cannot parse fully
    return None


def parse_signals(text: str) -> List[Signal]:
    signals: List[Signal] = []
    for line in text.splitlines():
        parsed = parse_line(line)
        if parsed:
            signals.append(parsed)
    return signals


def load_catalog(path: Path) -> Dict:
    if not path.exists():
        return {"matches": []}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "matches" not in data or not isinstance(data["matches"], list):
        raise ValueError("Catalog harus punya key 'matches' berupa list")
    return data


def parse_json_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except Exception:
        pass
    return []


def gamma_fetch_candidate_markets(limit_total: int = 1200, step: int = 200) -> List[Dict]:
    """Fetch active open markets from Gamma API for fuzzy sports match resolution."""
    base = "https://gamma-api.polymarket.com/markets"
    out: List[Dict] = []
    offset = 0
    while len(out) < limit_total:
        params = {
            "limit": min(step, limit_total - len(out)),
            "offset": offset,
            "active": True,
            "closed": False,
            "archived": False,
        }
        resp = requests.get(base, params=params, timeout=20)
        resp.raise_for_status()
        arr = resp.json()
        if not isinstance(arr, list) or not arr:
            break
        out.extend(arr)
        if len(arr) < params["limit"]:
            break
        offset += len(arr)
    return out


def auto_resolve_market(signal: Signal, candidates: List[Dict]) -> Tuple[Optional[Dict], Optional[str], str]:
    """Find market by fuzzy matching team names in question/event title and map pick->token."""
    home_n = normalize_team(signal.home)
    away_n = normalize_team(signal.away)
    pick_n = normalize_team(signal.pick)

    best = None
    best_score = -1

    for m in candidates:
        q = normalize_team(m.get("question", ""))
        event_titles = " ".join(
            normalize_team(e.get("title", "")) for e in (m.get("events") or []) if isinstance(e, dict)
        )
        hay = f"{q} {event_titles}".strip()

        score = 0
        home_exact = bool(home_n and home_n in hay)
        away_exact = bool(away_n and away_n in hay)
        if home_exact:
            score += 3
        if away_exact:
            score += 3

        # partial token overlap fallback
        home_tokens = [t for t in home_n.split() if len(t) >= 3]
        away_tokens = [t for t in away_n.split() if len(t) >= 3]
        home_tok_hits = sum(1 for t in home_tokens if t in hay)
        away_tok_hits = sum(1 for t in away_tokens if t in hay)
        score += home_tok_hits + away_tok_hits

        # strong guard: must mention both teams at least partially
        home_hit = home_exact or home_tok_hits > 0
        away_hit = away_exact or away_tok_hits > 0
        if not (home_hit and away_hit):
            continue

        if home_n and away_n and f"{home_n} vs {away_n}" in hay:
            score += 3
        if home_n and away_n and f"{away_n} vs {home_n}" in hay:
            score += 3

        if score > best_score:
            best_score = score
            best = m

    if not best or best_score < 4:
        return None, None, "Auto-resolve tidak menemukan match dengan confidence cukup"

    outcomes = parse_json_list(best.get("outcomes"))
    token_ids = parse_json_list(best.get("clobTokenIds"))
    outcome_map = {normalize_team(name): idx for idx, name in enumerate(outcomes)}

    token_id = None
    if pick_n in outcome_map and outcome_map[pick_n] < len(token_ids):
        token_id = token_ids[outcome_map[pick_n]]
    else:
        # soft matching for pick aliases inside outcomes
        for out_name, idx in outcome_map.items():
            if pick_n and (pick_n in out_name or out_name in pick_n):
                if idx < len(token_ids):
                    token_id = token_ids[idx]
                    break

    if not token_id:
        return best, None, "Market ketemu, tapi pick tidak cocok dengan outcomes"

    return best, token_id, "Auto-resolve sukses"


def fetch_live_league_games(league_slug: str = "ligue-1") -> Dict[str, List[str]]:
    """Fetch parent game ids from sports league page (__NEXT_DATA__)."""
    url = f"https://polymarket.com/sports/{league_slug}/games"
    html = requests.get(url, timeout=30).text
    start = html.find('<script id="__NEXT_DATA__"')
    if start < 0:
        return {}
    start = html.find('>', start) + 1
    end = html.find('</script>', start)
    if end < 0:
        return {}
    data = json.loads(html[start:end])

    queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    for q in queries:
        if q.get("queryKey") == ["parentToChildEventIds"]:
            ptc = q.get("state", {}).get("data", {})
            if isinstance(ptc, dict):
                return ptc
    return {}


def fetch_event(event_id: str) -> Optional[Dict]:
    r = requests.get("https://gamma-api.polymarket.com/events", params={"id": event_id}, timeout=20)
    r.raise_for_status()
    arr = r.json()
    if isinstance(arr, list) and arr:
        return arr[0]
    return None


def resolve_from_live_league(signal: Signal, league_slug: str = "ligue-1") -> Tuple[Optional[Dict], Optional[str], str]:
    """Resolve by scraping league live list then choosing suitable market (winner/halftime)."""
    raw_home = signal.home.strip().lower()
    raw_away = signal.away.strip().lower()
    home_n = normalize_team(signal.home)
    away_n = normalize_team(signal.away)
    pick_n = normalize_team(signal.pick)

    def token_set(raw_team: str, norm_team: str) -> set:
        toks = set()
        toks.update(t for t in re.split(r"\W+", raw_team) if len(t) >= 2)
        toks.update(t for t in norm_team.split() if len(t) >= 3)
        # common abbreviations used in parent keys
        if "paris saint germain" in norm_team:
            toks.add("psg")
        if "manchester city" in norm_team:
            toks.add("mci")
        if "manchester united" in norm_team:
            toks.add("mu")
        if "marseille" in norm_team:
            toks.add("olm")
        if "monaco" in norm_team:
            toks.add("asm")
        if "toulouse" in norm_team:
            toks.add("tou")
        if "strasbourg" in norm_team:
            toks.add("str")
        if "nice" in norm_team:
            toks.add("ogc")
        return toks

    home_tokens = token_set(raw_home, home_n)
    away_tokens = token_set(raw_away, away_n)

    ptc = fetch_live_league_games(league_slug=league_slug)
    if not ptc:
        return None, None, "Gagal ambil daftar game live league"

    target_parent = None
    best_parent_score = -1
    for parent_key, _ in ptc.items():
        k_parts = set(parent_key.lower().split('-'))
        hs = len(home_tokens & k_parts)
        as_ = len(away_tokens & k_parts)
        score = hs + as_
        if hs > 0 and as_ > 0 and score > best_parent_score:
            best_parent_score = score
            target_parent = parent_key

    if not target_parent:
        return None, None, "Game tidak ditemukan di live league list"

    child_ids = ptc.get(target_parent, [])
    if not child_ids:
        return None, None, "Game ditemukan tapi belum ada child event"

    # prefer full-time winner if available, fallback halftime result
    best_market = None
    for cid in child_ids:
        ev = fetch_event(str(cid))
        if not ev:
            continue
        for m in (ev.get("markets") or []):
            q = normalize_team(m.get("question", ""))
            if "leading at halftime" in q:
                best_market = m
                # continue search in case winner market exists
            if "who will win" in q or "to win" in q or "winner" in q:
                best_market = m
                break
        if best_market and any(x in normalize_team(best_market.get("question", "")) for x in ["who will win", "to win", "winner"]):
            break

    if not best_market:
        return None, None, "Market untuk game ditemukan, tapi belum ada market winner/halftime"

    outcomes = parse_json_list(best_market.get("outcomes"))
    token_ids = parse_json_list(best_market.get("clobTokenIds"))

    token_id = None
    for idx, out in enumerate(outcomes):
        on = normalize_team(out)
        if pick_n == on or pick_n in on or on in pick_n:
            if idx < len(token_ids):
                token_id = token_ids[idx]
                break

    # special mapping for halftime yes/no market
    if not token_id and len(outcomes) == 2:
        qn = normalize_team(best_market.get("question", ""))
        if "leading at halftime" in qn and {normalize_team(x) for x in outcomes} == {"yes", "no"}:
            # Yes means home leading at halftime
            if pick_n == home_n and len(token_ids) >= 1:
                token_id = token_ids[0]
            elif pick_n == away_n and len(token_ids) >= 2:
                token_id = token_ids[1]

    if not token_id:
        return best_market, None, "Market ketemu, tapi pick tidak cocok dengan outcomes"

    return best_market, token_id, f"Live resolve sukses ({league_slug})"


def resolve_market(signal: Signal, catalog: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    home_n = normalize_team(signal.home)
    away_n = normalize_team(signal.away)
    pick_n = normalize_team(signal.pick)

    best = None
    for item in catalog.get("matches", []):
        aliases = item.get("aliases", {})
        home_aliases = [normalize_team(x) for x in aliases.get("home", [])]
        away_aliases = [normalize_team(x) for x in aliases.get("away", [])]
        if home_n in home_aliases and away_n in away_aliases:
            best = item
            break

    if not best:
        return None, None

    # outcome mapping (3-way): home/draw/away
    outcome_map = best.get("outcome_map", {})

    # try exact alias match to decide token
    if pick_n in [normalize_team(x) for x in best.get("aliases", {}).get("home", [])]:
        token_id = outcome_map.get("home")
    elif pick_n in [normalize_team(x) for x in best.get("aliases", {}).get("away", [])]:
        token_id = outcome_map.get("away")
    elif pick_n in ["draw", "seri", "imbang"]:
        token_id = outcome_map.get("draw")
    else:
        token_id = None

    return best, token_id


def make_plan(
    signal: Signal,
    stake_usd: float,
    max_spread_cents: int,
    market_item: Optional[Dict],
    token_id: Optional[str],
    ready_status: str = "READY_DRY_RUN",
    max_slippage_pct: float = 2.0,
    idempotency_prefix: str = "local",
    signal_index: int = 0,
) -> OrderPlan:
    # Untuk kasus sinyal tim menang, default side = BUY_OUTCOME (3-way winner)
    side = "BUY_OUTCOME"

    if not market_item:
        return OrderPlan(
            home=signal.home,
            away=signal.away,
            pick=signal.pick,
            side=side,
            stake_usd=stake_usd,
            max_spread_cents=max_spread_cents,
            status="UNRESOLVED",
            reason="Market belum ketemu",
            max_slippage_pct=max_slippage_pct,
        )

    if not token_id:
        return OrderPlan(
            home=signal.home,
            away=signal.away,
            pick=signal.pick,
            side=side,
            stake_usd=stake_usd,
            max_spread_cents=max_spread_cents,
            status="UNRESOLVED",
            reason="Pick tidak cocok dengan outcome_map",
            market_slug=market_item.get("market_slug") or market_item.get("slug"),
            max_slippage_pct=max_slippage_pct,
        )

    return OrderPlan(
        home=signal.home,
        away=signal.away,
        pick=signal.pick,
        side=side,
        stake_usd=stake_usd,
        max_spread_cents=max_spread_cents,
        status=ready_status,
        reason="Siap dikirim ke executor",
        market_slug=market_item.get("market_slug") or market_item.get("slug"),
        token_id=token_id,
        max_slippage_pct=max_slippage_pct,
        idempotency_key=f"{idempotency_prefix}-{signal_index}",
    )


def render_summary(plans: List[OrderPlan]) -> str:
    lines = ["=== DRY RUN ORDER PLAN ==="]
    for i, p in enumerate(plans, 1):
        lines.append(
            f"{i}. {p.home} vs {p.away} | pick={p.pick} | side={p.side} | "
            f"stake=${p.stake_usd:.2f} | status={p.status}"
        )
        if p.market_slug:
            lines.append(f"   market: {p.market_slug}")
        if p.token_id:
            lines.append(f"   token: {p.token_id}")
        lines.append(f"   note: {p.reason}")
    return "\n".join(lines)


def render_manual_tickets(plans: List[OrderPlan], max_slippage_cents: int = 2) -> str:
    lines = ["=== MANUAL EXECUTION TICKETS ==="]
    for i, p in enumerate(plans, 1):
        lines.append(f"{i}) {p.home} vs {p.away}")
        lines.append(f"   PICK      : {p.pick}")
        lines.append(f"   STAKE     : ${p.stake_usd:.2f}")
        lines.append(f"   ACTION    : BUY_OUTCOME")
        lines.append(f"   STATUS    : {p.status}")
        if p.market_slug:
            lines.append(f"   MARKET    : {p.market_slug}")
            lines.append(f"   LINK      : https://polymarket.com/event/{p.market_slug}")
        if p.token_id:
            lines.append(f"   TOKEN_ID  : {p.token_id}")
        lines.append(f"   SLIPPAGE  : max {max_slippage_cents}¢")
        lines.append(f"   NOTE      : {p.reason}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket signal dry-run planner")
    parser.add_argument("--signals-file", default="signals.txt", help="File input sinyal")
    parser.add_argument("--catalog", default="markets_catalog.json", help="Katalog mapping market")
    parser.add_argument("--stake", type=float, default=20.0, help="Stake USD per signal")
    parser.add_argument("--max-spread", type=int, default=3, help="Max spread (cents)")
    parser.add_argument("--json-out", default="", help="Optional output JSON path")
    parser.add_argument("--manual-ticket-out", default="", help="Optional output manual execution ticket text")
    parser.add_argument("--max-slippage", type=int, default=2, help="Max slippage (cents) untuk ticket manual")
    parser.add_argument("--auto-resolve", action="store_true", help="Auto resolve market dari Gamma API")
    parser.add_argument("--scan-limit", type=int, default=1200, help="Jumlah market aktif untuk discan saat auto-resolve")
    parser.add_argument("--live-league", default="", help="Resolve langsung dari halaman sports league live (contoh: ligue-1)")
    parser.add_argument("--ready-status", default="READY_DRY_RUN", choices=["READY_DRY_RUN", "READY_REMOTE_EXEC"], help="Status plan siap eksekusi")
    parser.add_argument("--max-slippage-pct", type=float, default=2.0, help="Batas slippage persen untuk executor")
    parser.add_argument("--idempotency-prefix", default="sig", help="Prefix idempotency key")
    args = parser.parse_args()

    signals_path = Path(args.signals_file)
    if not signals_path.exists():
        raise SystemExit(f"Signals file tidak ditemukan: {signals_path}")

    text = signals_path.read_text(encoding="utf-8")
    signals = parse_signals(text)

    if not signals:
        raise SystemExit(
            "Tidak ada signal yang valid. Contoh format:\n"
            "MU vs BARCA | pick: BARCA\n"
            "ARSENAL VS MAN CITY - arsenal win\n"
        )

    catalog = load_catalog(Path(args.catalog))

    candidates: List[Dict] = []
    if args.auto_resolve:
        try:
            candidates = gamma_fetch_candidate_markets(limit_total=args.scan_limit)
        except Exception as e:
            print(f"[warn] auto-resolve fetch gagal: {e}")

    plans: List[OrderPlan] = []
    for idx, s in enumerate(signals, 1):
        if args.live_league:
            market_item, token_id, live_reason = resolve_from_live_league(s, league_slug=args.live_league)
            plan = make_plan(
                signal=s,
                stake_usd=args.stake,
                max_spread_cents=args.max_spread,
                market_item=market_item,
                token_id=token_id,
                ready_status=args.ready_status,
                max_slippage_pct=args.max_slippage_pct,
                idempotency_prefix=args.idempotency_prefix,
                signal_index=idx,
            )
            if plan.status == "UNRESOLVED":
                plan.reason = live_reason
            elif live_reason:
                plan.reason = f"{plan.reason}; {live_reason}"
            if market_item and not plan.market_slug:
                plan.market_slug = market_item.get("slug") or market_item.get("question")
            plans.append(plan)
            continue

        if args.auto_resolve and candidates:
            market_item, token_id, auto_reason = auto_resolve_market(s, candidates)
            plan = make_plan(
                signal=s,
                stake_usd=args.stake,
                max_spread_cents=args.max_spread,
                market_item=market_item,
                token_id=token_id,
                ready_status=args.ready_status,
                max_slippage_pct=args.max_slippage_pct,
                idempotency_prefix=args.idempotency_prefix,
                signal_index=idx,
            )
            if plan.status == "UNRESOLVED":
                plan.reason = auto_reason
            elif auto_reason:
                plan.reason = f"{plan.reason}; {auto_reason}"
            if market_item and not plan.market_slug:
                plan.market_slug = market_item.get("slug")
            plans.append(plan)
            continue

        market_item, token_id = resolve_market(s, catalog)
        plans.append(
            make_plan(
                signal=s,
                stake_usd=args.stake,
                max_spread_cents=args.max_spread,
                market_item=market_item,
                token_id=token_id,
                ready_status=args.ready_status,
                max_slippage_pct=args.max_slippage_pct,
                idempotency_prefix=args.idempotency_prefix,
                signal_index=idx,
            )
        )

    print(render_summary(plans))

    if args.json_out:
        out = {
            "signals": [asdict(s) for s in signals],
            "plans": [asdict(p) for p in plans],
        }
        Path(args.json_out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON written: {args.json_out}")

    if args.manual_ticket_out:
        ticket_text = render_manual_tickets(plans, max_slippage_cents=args.max_slippage)
        Path(args.manual_ticket_out).write_text(ticket_text + "\n", encoding="utf-8")
        print(f"Manual tickets written: {args.manual_ticket_out}")


if __name__ == "__main__":
    main()
