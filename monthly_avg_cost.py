"""
Monthly average-cost PnL test for Jan 17 to Feb 16, 2026.

Compares two approaches:
1) Snapshot diff: cumulative realized at Feb 16 minus cumulative realized at Jan 17
2) Period filter: sum realized deltas for events dated Jan 17..Feb 16
"""
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

import django
import requests


# Required by task; fallback keeps this runnable in current repo layout.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
try:
    django.setup()
except ModuleNotFoundError as exc:
    if exc.name == "config":
        os.environ["DJANGO_SETTINGS_MODULE"] = "polymarket_project.settings"
        django.setup()
    else:
        raise

from wallet_analysis.models import Activity, Trade, Wallet


WALLET_ID = 7
WALLET_ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
START_DATE = date(2026, 1, 17)
END_DATE = date(2026, 2, 16)
EPS = Decimal("0.000001")
ONE = Decimal("1")
ZERO = Decimal("0")


def D(value):
    return Decimal(str(value))


@dataclass
class Pos:
    shares: Decimal = ZERO
    avg_cost: Decimal = ZERO

    def buy(self, size: Decimal, price: Decimal) -> Decimal:
        old_cost = self.shares * self.avg_cost
        self.shares += size
        if self.shares > EPS:
            self.avg_cost = (old_cost + size * price) / self.shares
        return ZERO

    def sell(self, size: Decimal, price: Decimal) -> Decimal:
        if self.shares <= EPS:
            return ZERO
        qty = min(size, self.shares)
        pnl = qty * (price - self.avg_cost)
        self.shares -= size
        if self.shares < EPS:
            self.shares = ZERO
            self.avg_cost = ZERO
        return pnl

    def zero_out(self) -> Decimal:
        if self.shares <= EPS:
            return ZERO
        pnl = -self.shares * self.avg_cost
        self.shares = ZERO
        self.avg_cost = ZERO
        return pnl


def event_date_from_ts(timestamp: int) -> date:
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date()


def make_sort_key(etype, obj):
    if etype == "trade":
        return (obj.timestamp, 0, obj.id)

    if obj.activity_type == "REDEEM":
        if D(obj.usdc_size) > 0:
            return (obj.timestamp, 1, obj.id)  # winner redeem
        return (obj.timestamp, 3, obj.id)      # loser redeem last

    if obj.activity_type in ("SPLIT", "CONVERSION", "MERGE"):
        return (obj.timestamp, 0, obj.id)

    return (obj.timestamp, 2, obj.id)


def fetch_official_month_pnl(wallet_address: str) -> Decimal:
    url = (
        "https://data-api.polymarket.com/v1/leaderboard"
        f"?timePeriod=month&user={wallet_address}"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if not payload:
        return ZERO
    return D(payload[0].get("pnl", 0))


def compute_monthly_avg_cost():
    wallet = Wallet.objects.get(id=WALLET_ID)

    trades = list(
        Trade.objects.filter(wallet=wallet)
        .select_related("market")
        .order_by("timestamp", "id")
    )
    activities = list(
        Activity.objects.filter(wallet=wallet)
        .select_related("market")
        .order_by("timestamp", "id")
    )

    # Build known outcomes from full history.
    market_outcomes = defaultdict(set)
    for t in trades:
        if t.market_id:
            market_outcomes[t.market_id].add(t.outcome)

    events = [("trade", t) for t in trades] + [("activity", a) for a in activities]
    events.sort(key=lambda x: make_sort_key(x[0], x[1]))

    positions = defaultdict(Pos)
    cumulative_realized = ZERO
    realized_up_to_start = ZERO
    realized_up_to_end = ZERO
    period_filtered_realized = ZERO

    for etype, obj in events:
        realized_delta = ZERO

        if etype == "trade":
            t = obj
            if not t.market_id:
                continue
            key = (t.market_id, t.outcome)
            pos = positions[key]
            size = D(t.size)
            price = D(t.price)
            if t.side == "BUY":
                realized_delta += pos.buy(size, price)
            else:
                realized_delta += pos.sell(size, price)

        else:
            a = obj
            if a.activity_type == "REWARD":
                realized_delta += D(a.usdc_size)
            elif not a.market_id:
                continue
            else:
                size = D(a.size)
                usdc = D(a.usdc_size)

                if a.activity_type in ("SPLIT", "CONVERSION"):
                    outcomes = market_outcomes.get(a.market_id, {"Yes", "No"})
                    n = len(outcomes)
                    if size > 0 and n > 0:
                        cost_per_share = usdc / (size * n)
                        for outcome in outcomes:
                            positions[(a.market_id, outcome)].buy(size, cost_per_share)

                elif a.activity_type == "MERGE":
                    outcomes = market_outcomes.get(a.market_id, {"Yes", "No"})
                    n = len(outcomes)
                    if size > 0 and n > 0:
                        rev_per_share = usdc / (size * n)
                        for outcome in outcomes:
                            key = (a.market_id, outcome)
                            realized_delta += positions[key].sell(size, rev_per_share)

                elif a.activity_type == "REDEEM":
                    if usdc > 0:
                        market_pos = [
                            (k, v)
                            for k, v in positions.items()
                            if k[0] == a.market_id and v.shares > EPS
                        ]
                        matched = False
                        for _, pos in market_pos:
                            if abs(pos.shares - size) < Decimal("0.5"):
                                realized_delta += pos.sell(size, ONE)
                                matched = True
                                break
                        if not matched:
                            remaining = size
                            for _, pos in sorted(market_pos, key=lambda x: x[1].shares, reverse=True):
                                if remaining <= EPS:
                                    break
                                qty = min(remaining, pos.shares)
                                realized_delta += pos.sell(qty, ONE)
                                remaining -= qty
                    else:
                        for key, pos in positions.items():
                            if key[0] == a.market_id:
                                realized_delta += pos.zero_out()

        event_date = event_date_from_ts(obj.timestamp)
        cumulative_realized += realized_delta

        if event_date <= START_DATE:
            realized_up_to_start = cumulative_realized
        if event_date <= END_DATE:
            realized_up_to_end = cumulative_realized
        if START_DATE <= event_date <= END_DATE:
            period_filtered_realized += realized_delta

    return {
        "snapshot_diff": realized_up_to_end - realized_up_to_start,
        "period_filter": period_filtered_realized,
        "realized_up_to_start": realized_up_to_start,
        "realized_up_to_end": realized_up_to_end,
    }


def print_comparison(result, official_month_pnl: Decimal):
    rows = [
        ("PM official month (API)", official_month_pnl, Decimal("0")),
        ("Avg cost: snapshot diff", result["snapshot_diff"], result["snapshot_diff"] - official_month_pnl),
        ("Avg cost: period filter", result["period_filter"], result["period_filter"] - official_month_pnl),
    ]

    print("=" * 90)
    print("Monthly Avg Cost PnL Comparison (Jan 17 to Feb 16, 2026)")
    print("Snapshot method: realized up to 2026-02-16 minus realized up to 2026-01-17")
    print("=" * 90)
    print(f"{'Method':<35} {'PnL (USD)':>15} {'Diff vs PM':>15}")
    print("-" * 90)
    for label, pnl, diff in rows:
        print(f"{label:<35} ${pnl:>14,.2f} ${diff:>+14,.2f}")
    print("-" * 90)
    print(f"Realized up to 2026-01-17: ${result['realized_up_to_start']:,.2f}")
    print(f"Realized up to 2026-02-16: ${result['realized_up_to_end']:,.2f}")


if __name__ == "__main__":
    official_month = fetch_official_month_pnl(WALLET_ADDRESS)
    monthly = compute_monthly_avg_cost()
    print_comparison(monthly, official_month)
