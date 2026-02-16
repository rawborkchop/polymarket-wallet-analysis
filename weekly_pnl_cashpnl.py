import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from typing import Dict, List, Optional, Tuple

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
try:
    django.setup()
except ModuleNotFoundError as exc:
    if exc.name == "config":
        os.environ["DJANGO_SETTINGS_MODULE"] = "polymarket_project.settings"
        django.setup()
    else:
        raise

from wallet_analysis.models import Activity, Trade, Wallet  # noqa: E402


getcontext().prec = 28

WALLET_ID = 7
WALLET_ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
CUTOFF_DT = datetime(2026, 2, 9, 16, 0, 0, tzinfo=timezone.utc)
CUTOFF_TS = int(CUTOFF_DT.timestamp())
TARGET_WEEKLY = Decimal("6.69")


def D(x) -> Decimal:
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def fmt_dt(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fetch_positions_all(user: str, limit: int = 500, endpoint: str = "https://data-api.polymarket.com/v1/positions", include_closed: bool = False) -> List[dict]:
    out: List[dict] = []
    offset = 0
    while True:
        params = {"user": user, "limit": limit, "offset": offset}
        if include_closed:
            params["sizeThreshold"] = 0

        r = requests.get(endpoint, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            print(f"Positions API returned non-list at offset={offset}: {type(data).__name__}")
            break

        out.extend(data)
        print(f"Fetched from {endpoint}: batch={len(data)} offset={offset} total={len(out)} include_closed={include_closed}")

        if len(data) < limit:
            break
        offset += limit

    return out


def summarize_positions(positions: List[dict], label: str):
    sum_cash = Decimal("0")
    sum_realized = Decimal("0")
    sum_current = Decimal("0")
    sum_initial = Decimal("0")
    sum_current_minus_initial = Decimal("0")
    sum_cash_plus_current_minus_initial = Decimal("0")
    sum_cash_plus_current = Decimal("0")

    for p in positions:
        cash = D(p.get("cashPnl"))
        rpnl = D(p.get("realizedPnl"))
        cur = D(p.get("currentValue"))
        init = D(p.get("initialValue"))
        mtm = cur - init

        sum_cash += cash
        sum_realized += rpnl
        sum_current += cur
        sum_initial += init
        sum_current_minus_initial += mtm
        sum_cash_plus_current_minus_initial += cash + mtm
        sum_cash_plus_current += cash + cur

    print(f"\n--- {label} ---")
    print(f"positions_count = {len(positions)}")
    print(f"sum(cashPnl) = {sum_cash:.8f}")
    print(f"sum(realizedPnl) = {sum_realized:.8f}")
    print(f"sum(currentValue) = {sum_current:.8f}")
    print(f"sum(initialValue) = {sum_initial:.8f}")
    print(f"sum(currentValue - initialValue) = {sum_current_minus_initial:.8f}")
    print(f"sum(cashPnl + (currentValue - initialValue)) = {sum_cash_plus_current_minus_initial:.8f}")
    print(f"sum(cashPnl + currentValue) = {sum_cash_plus_current:.8f}")

    return {
        "sum_cash": sum_cash,
        "sum_realized": sum_realized,
        "sum_current": sum_current,
        "sum_initial": sum_initial,
        "sum_current_minus_initial": sum_current_minus_initial,
        "sum_cash_plus_current_minus_initial": sum_cash_plus_current_minus_initial,
        "sum_cash_plus_current": sum_cash_plus_current,
    }


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


def load_events(wallet: Wallet):
    trades = list(Trade.objects.filter(wallet=wallet).select_related("market").order_by("timestamp", "id"))
    activities = list(Activity.objects.filter(wallet=wallet).select_related("market").order_by("timestamp", "id"))
    events = [("trade", t.timestamp, t.id, t) for t in trades] + [("activity", a.timestamp, a.id, a) for a in activities]
    events.sort(key=lambda x: (x[1], 0 if x[0] == "trade" else 1, x[2]))
    return trades, activities, events


def simulated_cash_pnl_at_cutoff(events, cutoff_ts: int) -> Decimal:
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
            continue

        # activities
        if obj.activity_type == "REWARD":
            realized += D(obj.usdc_size)
            continue

        if obj.activity_type != "REDEEM" or not obj.market_id:
            continue

        size = D(obj.size)
        usdc = D(obj.usdc_size)

        if usdc > 0:
            # winning redeem at $1
            candidates = [(k, p) for k, p in positions.items() if k[0] == obj.market_id and p.shares > 0]
            matched = False
            for _k, p in candidates:
                if abs(p.shares - size) <= Decimal("0.000001"):
                    realized += p.sell(size, Decimal("1"))
                    matched = True
                    break
            if not matched:
                rem = size
                for _k, p in sorted(candidates, key=lambda kv: kv[1].shares, reverse=True):
                    if rem <= 0:
                        break
                    q = min(rem, p.shares)
                    realized += p.sell(q, Decimal("1"))
                    rem -= q
        else:
            # losing redeem => worthless
            for _k, p in list(positions.items()):
                if _k[0] == obj.market_id and p.shares > 0:
                    realized += p.zero_out()

    return realized


def try_pnl_endpoints(wallet: str):
    print("\n=== Try profile PnL endpoints (chart source hunt) ===")
    endpoints = [
        ("https://data-api.polymarket.com/pnl", ["user", "address", "wallet"]),
        ("https://data-api.polymarket.com/v1/pnl", ["user", "address", "wallet"]),
        (f"https://data-api.polymarket.com/pnl/{wallet}", [None]),
        (f"https://data-api.polymarket.com/v1/pnl/{wallet}", [None]),
    ]

    for base, keys in endpoints:
        for key in keys:
            params = {} if key is None else {key: wallet}
            try:
                r = requests.get(base, params=params, timeout=45)
                ct = r.headers.get("content-type", "")
                try:
                    payload = r.json()
                    jtype = type(payload).__name__
                    if isinstance(payload, list):
                        preview = payload[:2]
                        size = len(payload)
                    elif isinstance(payload, dict):
                        preview = {k: payload[k] for k in list(payload.keys())[:6]}
                        size = len(payload)
                    else:
                        preview = str(payload)[:250]
                        size = None
                    print(f"GET {r.url} -> HTTP {r.status_code}, json={jtype}, size={size}, ct={ct}")
                    print(f"  preview: {preview}")
                except Exception:
                    print(f"GET {r.url} -> HTTP {r.status_code}, non-json ct={ct}, body={r.text[:300]!r}")
            except Exception as e:
                print(f"GET {base} params={params} -> ERROR {e}")


def main():
    print("=" * 110)
    print("WEEKLY PNL CASHPNL TEST")
    print("=" * 110)
    print(f"Wallet: {WALLET_ADDRESS} (db id={WALLET_ID})")
    print(f"Cutoff: {CUTOFF_DT.strftime('%Y-%m-%d %H:%M:%S UTC')} ({CUTOFF_TS})")
    print(f"Reference weekly shown by profile: ${TARGET_WEEKLY}")

    print("\n=== 1) Fetch ALL current positions from API ===")
    # Requested endpoint
    positions_v1 = fetch_positions_all(
        WALLET_ADDRESS,
        limit=500,
        endpoint="https://data-api.polymarket.com/v1/positions",
        include_closed=False,
    )
    sums_v1 = summarize_positions(positions_v1, "v1/positions (default params)")

    # Extra check (often needed to include closed/zero-size rows)
    positions_plain_all = fetch_positions_all(
        WALLET_ADDRESS,
        limit=500,
        endpoint="https://data-api.polymarket.com/positions",
        include_closed=True,
    )
    sums_plain_all = summarize_positions(positions_plain_all, "positions + sizeThreshold=0 (includes closed)")

    # Use the all-positions view for X if available, otherwise fall back to v1 default
    use_all = len(positions_plain_all) > len(positions_v1)
    chosen = sums_plain_all if use_all else sums_v1
    chosen_label = "positions+sizeThreshold=0" if use_all else "v1/positions default"
    print(f"\nChosen dataset for X (sum cashPnl now): {chosen_label}")

    print("\n=== 2-4) Simulate cashPnl at cutoff via avg cost from DB events ===")
    wallet = Wallet.objects.get(id=WALLET_ID)
    trades, activities, events = load_events(wallet)
    y_cutoff = simulated_cash_pnl_at_cutoff(events, CUTOFF_TS)

    print(f"db_trade_count = {len(trades)}")
    print(f"db_activity_count = {len(activities)}")
    print(f"simulated_cashpnl_at_cutoff (Y, {fmt_dt(CUTOFF_TS)}) = {y_cutoff:.8f}")

    x_now = chosen["sum_cash"]
    weekly_cash_delta = x_now - y_cutoff
    print(f"total_pnl_api_now_X = sum(cashPnl) = {x_now:.8f}")
    print(f"weekly_candidate_cash = X - Y = {weekly_cash_delta:.8f}")
    print(f"difference_vs_target_6.69 = {(weekly_cash_delta - TARGET_WEEKLY):+.8f}")

    # Also print alternative "includes unrealized" live formulas with same cutoff baseline
    alt_now = chosen["sum_cash_plus_current_minus_initial"]
    weekly_alt_delta = alt_now - y_cutoff
    print(f"alt_now = sum(cashPnl + currentValue - initialValue) = {alt_now:.8f}")
    print(f"weekly_candidate_alt = alt_now - Y = {weekly_alt_delta:.8f}")
    print(f"difference_alt_vs_target_6.69 = {(weekly_alt_delta - TARGET_WEEKLY):+.8f}")

    print("\n=== 5) Probe possible profile chart PnL endpoints ===")
    try_pnl_endpoints(WALLET_ADDRESS)

    print("\n=== 6) KEY IDEA recap ===")
    print(f"X (sum cashPnl now) = {x_now:.8f}")
    print(f"Y (simulated cashPnl at cutoff) = {y_cutoff:.8f}")
    print(f"X - Y = {weekly_cash_delta:.8f}")
    print(f"Target profile weekly PnL reference = {TARGET_WEEKLY:.2f}")


if __name__ == "__main__":
    main()
