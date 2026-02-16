import os
import json
from decimal import Decimal, getcontext
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
try:
    django.setup()
except ModuleNotFoundError as exc:
    if exc.name == "config":
        os.environ["DJANGO_SETTINGS_MODULE"] = "polymarket_project.settings"
        django.setup()
    else:
        raise

from wallet_analysis.models import Wallet, Trade, Activity  # noqa: E402


getcontext().prec = 28

WALLET_ID = 7
WALLET_ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
CUTOFF_DT = datetime(2026, 2, 9, 16, 0, 0, tzinfo=timezone.utc)
CUTOFF_TS = int(CUTOFF_DT.timestamp())

TARGET_NOW = Decimal("6.69")
TARGET_BEFORE = Decimal("7.56")
TARGET_DROP = TARGET_NOW - TARGET_BEFORE  # -0.87


def D(x) -> Decimal:
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def fmt_ts(ts: Optional[int]) -> str:
    if ts is None:
        return "None"
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ts_from_point(p: dict) -> Optional[int]:
    for k in ("t", "ts", "time", "timestamp", "x"):
        if k in p and p[k] is not None:
            try:
                return int(float(p[k]))
            except Exception:
                pass
    return None


def val_from_point(p: dict) -> Optional[Decimal]:
    for k in ("pnl", "value", "y", "p", "profit", "amount", "totalPnl"):
        if k in p and p[k] is not None:
            try:
                return D(p[k])
            except Exception:
                pass
    return None


def fetch_json(url: str, params=None):
    r = requests.get(url, params=params, timeout=45)
    try:
        data = r.json()
    except Exception:
        data = None
    return r.status_code, data, r.text


@dataclass
class Pos:
    shares: Decimal = Decimal("0")
    avg_cost: Decimal = Decimal("0")

    def buy(self, size: Decimal, price: Decimal):
        old_cost = self.shares * self.avg_cost
        self.shares += size
        if self.shares > 0:
            self.avg_cost = (old_cost + size * price) / self.shares

    def sell(self, size: Decimal, price: Decimal) -> Decimal:
        if self.shares <= 0:
            return Decimal("0")
        qty = min(size, self.shares)
        pnl = qty * (price - self.avg_cost)
        self.shares -= qty
        if self.shares <= 0:
            self.shares = Decimal("0")
            self.avg_cost = Decimal("0")
        return pnl

    def zero_out(self) -> Decimal:
        if self.shares <= 0:
            return Decimal("0")
        pnl = -self.shares * self.avg_cost
        self.shares = Decimal("0")
        self.avg_cost = Decimal("0")
        return pnl


def print_header(title: str):
    print("\n" + "=" * 120)
    print(title)
    print("=" * 120)


def load_events(wallet: Wallet):
    trades = list(Trade.objects.filter(wallet=wallet).select_related("market").order_by("timestamp", "id"))
    activities = list(Activity.objects.filter(wallet=wallet).select_related("market").order_by("timestamp", "id"))
    events = [("trade", t.timestamp, t.id, t) for t in trades] + [("activity", a.timestamp, a.id, a) for a in activities]
    # process trades before activities at same ts so avg cost is ready for redeem
    events.sort(key=lambda x: (x[1], 0 if x[0] == "trade" else 1, x[2]))
    return trades, activities, events


def replay_until(events, cutoff_ts: int):
    positions: Dict[Tuple[int, str], Pos] = defaultdict(Pos)
    realized = Decimal("0")

    for typ, ts, _id, obj in events:
        if ts >= cutoff_ts:
            break

        if typ == "trade":
            key = (obj.market_id or -1, obj.outcome or "")
            price = D(obj.price)
            size = D(obj.size)
            if obj.side == "BUY":
                positions[key].buy(size, price)
            else:
                realized += positions[key].sell(size, price)
        else:
            if obj.activity_type == "REDEEM" and obj.market_id:
                size = D(obj.size)
                usdc = D(obj.usdc_size)
                if usdc > 0:
                    # winner redeem at $1
                    candidates = [(k, v) for k, v in positions.items() if k[0] == obj.market_id and v.shares > 0]
                    # try exact share match first
                    matched = False
                    for k, p in candidates:
                        if abs(p.shares - size) <= Decimal("0.000001"):
                            realized += p.sell(size, Decimal("1"))
                            matched = True
                            break
                    if not matched:
                        rem = size
                        for k, p in sorted(candidates, key=lambda kv: kv[1].shares, reverse=True):
                            if rem <= 0:
                                break
                            q = min(rem, p.shares)
                            realized += p.sell(q, Decimal("1"))
                            rem -= q
                else:
                    # loser redeem -> zero out
                    for k, p in list(positions.items()):
                        if k[0] == obj.market_id and p.shares > 0:
                            realized += p.zero_out()

    return positions, realized


def main():
    print_header("WEEKLY PNL FINAL INVESTIGATION")
    print(f"Wallet: {WALLET_ADDRESS} (db id={WALLET_ID})")
    print(f"Cutoff: {CUTOFF_DT.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Target weekly values observed: was ${TARGET_BEFORE}, now ${TARGET_NOW}, change {TARGET_DROP:+.2f}")

    wallet = Wallet.objects.get(id=WALLET_ID)
    trades, activities, events = load_events(wallet)

    print_header("1) API /v1/pnl window=all timeseries + recent deltas")
    candidate_urls = [
        (f"https://data-api.polymarket.com/v1/pnl/{WALLET_ADDRESS}", {"window": "all"}),
        ("https://data-api.polymarket.com/v1/pnl", {"address": WALLET_ADDRESS, "window": "all"}),
        (f"https://data-api.polymarket.com/pnl/{WALLET_ADDRESS}", {"window": "all"}),
        ("https://data-api.polymarket.com/pnl", {"address": WALLET_ADDRESS, "window": "all"}),
    ]

    points: List[dict] = []
    used = None
    for pnl_url, params in candidate_urls:
        status, data, raw = fetch_json(pnl_url, params=params)
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        print(f"GET {pnl_url}?{qs} -> HTTP {status}")

        candidate_points: List[dict] = []
        if isinstance(data, list):
            candidate_points = data
        elif isinstance(data, dict):
            for k in ("data", "points", "history", "results"):
                if isinstance(data.get(k), list):
                    candidate_points = data[k]
                    break

        if candidate_points:
            points = candidate_points
            used = (pnl_url, params)
            break

        if status != 200:
            print(f"  body head: {raw[:180]!r}")

    print(f"Timeseries points parsed: {len(points)}")
    if used:
        print(f"Using timeseries source: {used[0]} params={used[1]}")
    if not points:
        print("Could not parse list-like points from any candidate endpoint.")
    else:
        print("\nLast 15 raw points:")
        for p in points[-15:]:
            print(p)

        parsed = []
        for p in points:
            if isinstance(p, dict):
                ts = ts_from_point(p)
                v = val_from_point(p)
                if ts is not None and v is not None:
                    parsed.append((ts, v, p))

        print(f"\nParsed points with timestamp+value: {len(parsed)}")
        if parsed:
            print("Last 15 parsed points:")
            for ts, v, _ in parsed[-15:]:
                print(f"  {fmt_ts(ts)} -> {v}")

            print("\nConsecutive deltas for last 14 steps:")
            for i in range(max(1, len(parsed) - 14), len(parsed)):
                ts0, v0, _ = parsed[i - 1]
                ts1, v1, _ = parsed[i]
                dv = v1 - v0
                print(f"  {fmt_ts(ts0)} -> {fmt_ts(ts1)} | {v0} -> {v1} | delta {dv:+.6f}")

            # closest points to observed values
            by_669 = sorted(parsed, key=lambda x: abs(x[1] - TARGET_NOW))[:5]
            by_756 = sorted(parsed, key=lambda x: abs(x[1] - TARGET_BEFORE))[:5]
            print("\nClosest points to 6.69:")
            for ts, v, _ in by_669:
                print(f"  {fmt_ts(ts)} value={v} diff={(v - TARGET_NOW):+.6f}")
            print("\nClosest points to 7.56:")
            for ts, v, _ in by_756:
                print(f"  {fmt_ts(ts)} value={v} diff={(v - TARGET_BEFORE):+.6f}")

            # best matching consecutive drop to -0.87
            step_deltas = []
            for i in range(1, len(parsed)):
                ts0, v0, _ = parsed[i - 1]
                ts1, v1, _ = parsed[i]
                step_deltas.append((abs((v1 - v0) - TARGET_DROP), ts0, ts1, v0, v1, v1 - v0))
            step_deltas.sort(key=lambda x: x[0])
            print("\nClosest consecutive changes to -0.87:")
            for row in step_deltas[:8]:
                _, ts0, ts1, v0, v1, dv = row
                print(f"  {fmt_ts(ts0)} -> {fmt_ts(ts1)} | {v0} -> {v1} | delta {dv:+.6f}")

            # delta from first point >= cutoff to latest
            after = [(ts, v) for ts, v, _ in parsed if ts >= CUTOFF_TS]
            if after:
                st_ts, st_v = after[0]
                en_ts, en_v = after[-1]
                print("\nDelta in /v1/pnl values from first point >= cutoff to latest:")
                print(f"  start {fmt_ts(st_ts)} value={st_v}")
                print(f"  end   {fmt_ts(en_ts)} value={en_v}")
                print(f"  delta {en_v - st_v:+.6f}")

    print_header("2) ALL DB events AFTER exact cutoff (>= 2026-02-09 16:00 UTC)")
    trades_after = [t for t in trades if int(t.timestamp) >= CUTOFF_TS]
    acts_after = [a for a in activities if int(a.timestamp) >= CUTOFF_TS]
    print(f"Trades after cutoff: {len(trades_after)}")
    print(f"Activities after cutoff: {len(acts_after)}")

    print("\nTRADES:")
    for t in trades_after:
        print(json.dumps({
            "id": t.id,
            "ts": int(t.timestamp),
            "ts_utc": fmt_ts(t.timestamp),
            "side": t.side,
            "market_id": t.market_id,
            "condition_id": t.market.condition_id if t.market else None,
            "title": t.market.title if t.market else None,
            "outcome": t.outcome,
            "price": str(t.price),
            "size": str(t.size),
            "total_value": str(t.total_value),
            "tx": t.transaction_hash,
            "asset": t.asset,
        }, ensure_ascii=False))

    print("\nACTIVITIES:")
    for a in acts_after:
        print(json.dumps({
            "id": a.id,
            "ts": int(a.timestamp),
            "ts_utc": fmt_ts(a.timestamp),
            "activity_type": a.activity_type,
            "market_id": a.market_id,
            "condition_id": a.market.condition_id if a.market else None,
            "title": a.title or (a.market.title if a.market else None),
            "outcome": a.outcome,
            "size": str(a.size),
            "usdc_size": str(a.usdc_size),
            "tx": a.transaction_hash,
            "asset": a.asset,
        }, ensure_ascii=False))

    print_header("3) Weekly PnL interpretations for events after cutoff")
    # Interpretation A: simple cashflow
    sell_cash = sum(D(t.total_value) for t in trades_after if t.side == "SELL")
    buy_cash = sum(D(t.total_value) for t in trades_after if t.side == "BUY")
    redeem_cash = sum(D(a.usdc_size) for a in acts_after if a.activity_type == "REDEEM")
    reward_cash = sum(D(a.usdc_size) for a in acts_after if a.activity_type == "REWARD")
    simple_cash = sell_cash - buy_cash + redeem_cash + reward_cash

    print(f"Simple cash components:")
    print(f"  SELL inflow:  +{sell_cash:.6f}")
    print(f"  BUY outflow:  -{buy_cash:.6f}")
    print(f"  REDEEM flow:  +{redeem_cash:.6f}")
    print(f"  REWARD flow:  +{reward_cash:.6f}")
    print(f"  SIMPLE_CASH:   {simple_cash:+.6f}")

    # Interpretation B: avg-cost realized (seeded with full history before cutoff)
    pos0, realized_before = replay_until(events, CUTOFF_TS)
    print(f"\nReplay seeded through history BEFORE cutoff: realized cumulative before cutoff={realized_before:+.6f}")

    positions: Dict[Tuple[int, str], Pos] = defaultdict(Pos)
    for k, p in pos0.items():
        positions[k] = Pos(shares=p.shares, avg_cost=p.avg_cost)

    realized_window = Decimal("0")
    trade_realized_window = Decimal("0")
    redeem_realized_window = Decimal("0")

    print("\nEvent-by-event avg-cost realized AFTER cutoff:")
    for typ, ts, _id, obj in events:
        if ts < CUTOFF_TS:
            continue

        if typ == "trade":
            key = (obj.market_id or -1, obj.outcome or "")
            px = D(obj.price)
            sz = D(obj.size)
            if obj.side == "BUY":
                positions[key].buy(sz, px)
                realized_evt = Decimal("0")
            else:
                realized_evt = positions[key].sell(sz, px)
                trade_realized_window += realized_evt
                realized_window += realized_evt

            print(f"  {fmt_ts(ts)} TRADE {obj.side:4s} mkt={obj.market_id} outcome={obj.outcome:>6s} size={sz} px={px} realized={realized_evt:+.6f}")

        else:
            if obj.activity_type == "REWARD":
                realized_evt = D(obj.usdc_size)
                realized_window += realized_evt
                print(f"  {fmt_ts(ts)} ACT   REWARD usdc={D(obj.usdc_size)} realized={realized_evt:+.6f}")
                continue

            if obj.activity_type != "REDEEM" or not obj.market_id:
                print(f"  {fmt_ts(ts)} ACT   {obj.activity_type} (ignored for realized calc)")
                continue

            size = D(obj.size)
            usdc = D(obj.usdc_size)
            realized_evt = Decimal("0")

            if usdc > 0:
                candidates = [(k, p) for k, p in positions.items() if k[0] == obj.market_id and p.shares > 0]
                matched = False
                for k, p in candidates:
                    if abs(p.shares - size) <= Decimal("0.000001"):
                        realized_evt += p.sell(size, Decimal("1"))
                        matched = True
                        break
                if not matched:
                    rem = size
                    for k, p in sorted(candidates, key=lambda kv: kv[1].shares, reverse=True):
                        if rem <= 0:
                            break
                        q = min(rem, p.shares)
                        realized_evt += p.sell(q, Decimal("1"))
                        rem -= q
            else:
                for k, p in list(positions.items()):
                    if k[0] == obj.market_id and p.shares > 0:
                        realized_evt += p.zero_out()

            redeem_realized_window += realized_evt
            realized_window += realized_evt
            print(f"  {fmt_ts(ts)} ACT   REDEEM mkt={obj.market_id} size={size} usdc={usdc} realized={realized_evt:+.6f}")

    print("\nAvg-cost realized summary (after cutoff):")
    print(f"  trade realized:  {trade_realized_window:+.6f}")
    print(f"  redeem realized: {redeem_realized_window:+.6f}")
    print(f"  total realized:  {realized_window:+.6f}")

    print_header("4) Check dynamic/live component clue (7.56 -> 6.69 = -0.87)")
    print(f"Observed profile change: {TARGET_BEFORE} -> {TARGET_NOW} ({TARGET_DROP:+.6f})")
    print("Comparisons:")
    print(f"  simple_cash  - 6.69 = {(simple_cash - TARGET_NOW):+.6f}")
    print(f"  realized_win - 6.69 = {(realized_window - TARGET_NOW):+.6f}")
    print(f"  simple_cash  - 7.56 = {(simple_cash - TARGET_BEFORE):+.6f}")
    print(f"  realized_win - 7.56 = {(realized_window - TARGET_BEFORE):+.6f}")

    print_header("5) Positions API and open-position live valuation")
    pos_url = "https://data-api.polymarket.com/v1/positions"
    st, pos_data, pos_raw = fetch_json(pos_url, params={"user": WALLET_ADDRESS})
    print(f"GET {pos_url}?user=... -> HTTP {st}")

    rows = pos_data if isinstance(pos_data, list) else []
    print(f"Rows: {len(rows)}")
    if not rows:
        print(pos_raw[:1500])
    else:
        # print everything
        for i, r in enumerate(rows, 1):
            print(f"\nPosition #{i}")
            print(json.dumps(r, ensure_ascii=False, indent=2))

        sum_current = Decimal("0")
        sum_initial = Decimal("0")
        sum_cash_pnl = Decimal("0")
        sum_realized = Decimal("0")
        sum_unrealized = Decimal("0")

        for r in rows:
            cur = D(r.get("currentValue"))
            init = D(r.get("initialValue"))
            cash = D(r.get("cashPnl"))
            rpnl = D(r.get("realizedPnl"))
            size = D(r.get("size"))
            avg = D(r.get("avgPrice"))
            curpx = D(r.get("curPrice"))
            unr = size * (curpx - avg)

            sum_current += cur
            sum_initial += init
            sum_cash_pnl += cash
            sum_realized += rpnl
            sum_unrealized += unr

        print("\nAggregates from positions API:")
        print(f"  sum(currentValue): {sum_current:+.6f}")
        print(f"  sum(initialValue): {sum_initial:+.6f}")
        print(f"  sum(cashPnl):      {sum_cash_pnl:+.6f}")
        print(f"  sum(realizedPnl):  {sum_realized:+.6f}")
        print(f"  sum(size*(cur-avg)) proxy unrealized: {sum_unrealized:+.6f}")

    print_header("6) Combined hypotheses")
    if isinstance(rows, list) and rows:
        print(f"realized_window + unrealized_proxy = {(realized_window + sum_unrealized):+.6f}")
        print(f"simple_cash    + unrealized_proxy = {(simple_cash + sum_unrealized):+.6f}")
        print(f"(realized+unrealized) - 6.69 = {(realized_window + sum_unrealized - TARGET_NOW):+.6f}")
        print(f"(realized+unrealized) - 7.56 = {(realized_window + sum_unrealized - TARGET_BEFORE):+.6f}")

    print("\nFINAL NOTES")
    print("- If weekly PnL visibly changes intraday with no new trades/redeems, it must include a live MTM (unrealized) component.")
    print("- Use the printed /v1/pnl consecutive deltas and timestamp alignment to verify exactly when the -0.87 move occurred.")
    print("- Compare that timestamp against market price changes in open positions to identify the precise driver.")


if __name__ == "__main__":
    main()
