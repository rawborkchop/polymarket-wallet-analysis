"""
Monthly Avg Cost PnL v3 - Jan 17 to Feb 16 window analysis.

Task goals:
- Build full position state from ALL historical trades/activities.
- Compute requested monthly-logic variants and compare against profile target $1,280.
- Fetch and print full JSON from Polymarket PnL endpoints.
"""
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Set, Tuple

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


WALLET_ID = 7
WALLET_ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
TARGET_PROFILE_VALUE = Decimal("1280")

WINDOW_START_TS = int(datetime(2026, 1, 17, 0, 0, 0, tzinfo=timezone.utc).timestamp())
WINDOW_END_TS = int(datetime(2026, 2, 16, 23, 59, 59, tzinfo=timezone.utc).timestamp())

JAN16_235959_TS = int(datetime(2026, 1, 16, 23, 59, 59, tzinfo=timezone.utc).timestamp())
JAN17_000000_TS = WINDOW_START_TS
FEB16_235959_TS = WINDOW_END_TS

EPS = Decimal("0.000001")
ONE = Decimal("1")
ZERO = Decimal("0")


def D(value) -> Decimal:
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


@dataclass
class ReplayState:
    positions: Dict[Tuple[int, str], Pos] = field(default_factory=lambda: defaultdict(Pos))
    market_outcomes: Dict[int, Set[str]] = field(default_factory=lambda: defaultdict(set))
    market_resolution: Dict[int, Tuple[int, str]] = field(default_factory=dict)
    last_wallet_trade_price: Dict[Tuple[int, str], Decimal] = field(default_factory=dict)
    realized: Decimal = ZERO
    rewards: Decimal = ZERO


def make_sort_key(event_type: str, obj):
    if event_type == "trade":
        return (obj.timestamp, 0, obj.id)

    if obj.activity_type == "REDEEM":
        if D(obj.usdc_size) > 0:
            return (obj.timestamp, 1, obj.id)
        return (obj.timestamp, 3, obj.id)

    if obj.activity_type in ("SPLIT", "CONVERSION", "MERGE"):
        return (obj.timestamp, 0, obj.id)

    return (obj.timestamp, 2, obj.id)


def print_requested_api_json():
    urls = [
        f"https://data-api.polymarket.com/v1/pnl/{WALLET_ADDRESS}?window=month",
        f"https://data-api.polymarket.com/v1/pnl/{WALLET_ADDRESS}?window=all",
    ]

    print("=" * 120)
    print("RAW API RESPONSES (REQUESTED)")
    print("=" * 120)
    for url in urls:
        print(f"\nGET {url}")
        try:
            resp = requests.get(url, timeout=45)
            print(f"HTTP {resp.status_code}")
            try:
                payload = resp.json()
                print(json.dumps(payload, indent=2, sort_keys=True))
            except ValueError:
                print(resp.text.encode("unicode_escape").decode("ascii"))
        except Exception as exc:
            print(f"REQUEST FAILED: {exc}")


def collect_events():
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
    events = [("trade", t) for t in trades] + [("activity", a) for a in activities]
    events.sort(key=lambda x: make_sort_key(x[0], x[1]))
    return trades, activities, events


def preload_market_data(
    state: ReplayState,
    trades: Iterable[Trade],
    activities: Iterable[Activity],
):
    for t in trades:
        if t.market_id:
            state.market_outcomes[t.market_id].add(t.outcome)
            if t.market and t.market.resolved and t.market.resolution_timestamp:
                state.market_resolution[t.market_id] = (
                    int(t.market.resolution_timestamp),
                    t.market.winning_outcome,
                )
    for a in activities:
        if a.market and a.market_id and a.market.resolved and a.market.resolution_timestamp:
            state.market_resolution[a.market_id] = (
                int(a.market.resolution_timestamp),
                a.market.winning_outcome,
            )


def apply_event(state: ReplayState, event_type: str, obj) -> Tuple[Decimal, Decimal]:
    realized_delta = ZERO
    rewards_delta = ZERO

    if event_type == "trade":
        t = obj
        if not t.market_id:
            return ZERO, ZERO
        key = (t.market_id, t.outcome)
        size = D(t.size)
        price = D(t.price)
        state.market_outcomes[t.market_id].add(t.outcome)
        state.last_wallet_trade_price[key] = price
        pos = state.positions[key]
        if t.side == "BUY":
            realized_delta += pos.buy(size, price)
        else:
            realized_delta += pos.sell(size, price)
        return realized_delta, rewards_delta

    a = obj
    if a.activity_type == "REWARD":
        rewards_delta += D(a.usdc_size)
        return realized_delta, rewards_delta

    if not a.market_id:
        return ZERO, ZERO

    size = D(a.size)
    usdc = D(a.usdc_size)

    if a.activity_type in ("SPLIT", "CONVERSION"):
        outcomes = state.market_outcomes.get(a.market_id, {"Yes", "No"})
        n = len(outcomes)
        if size > 0 and n > 0:
            cost_per_share = usdc / (size * n)
            for outcome in outcomes:
                state.positions[(a.market_id, outcome)].buy(size, cost_per_share)

    elif a.activity_type == "MERGE":
        outcomes = state.market_outcomes.get(a.market_id, {"Yes", "No"})
        n = len(outcomes)
        if size > 0 and n > 0:
            rev_per_share = usdc / (size * n)
            for outcome in outcomes:
                realized_delta += state.positions[(a.market_id, outcome)].sell(size, rev_per_share)

    elif a.activity_type == "REDEEM":
        if usdc > 0:
            market_pos = [
                (k, v)
                for k, v in state.positions.items()
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
            for key, pos in state.positions.items():
                if key[0] == a.market_id:
                    realized_delta += pos.zero_out()

    return realized_delta, rewards_delta


def calc_unrealized(state: ReplayState, asof_ts: int, mtm: bool) -> Decimal:
    unrealized = ZERO
    for (market_id, outcome), pos in state.positions.items():
        if pos.shares <= EPS:
            continue

        mark: Optional[Decimal] = None

        if mtm:
            resolved = state.market_resolution.get(market_id)
            if resolved and asof_ts >= resolved[0]:
                mark = ONE if outcome == resolved[1] else ZERO
            else:
                mark = state.last_wallet_trade_price.get((market_id, outcome))

        if mark is None:
            mark = pos.avg_cost

        unrealized += pos.shares * (mark - pos.avg_cost)

    return unrealized


def run_replay(events, trades, activities):
    state = ReplayState()
    preload_market_data(state, trades, activities)

    cp_ts = sorted({JAN16_235959_TS, JAN17_000000_TS, FEB16_235959_TS})
    cp_realized = {}
    cp_rewards = {}
    cp_unrealized_nomtm = {}
    cp_unrealized_mtm = {}

    realized_period = ZERO
    rewards_period = ZERO

    cp_idx = 0

    for event_type, obj in events:
        ts = int(obj.timestamp)

        while cp_idx < len(cp_ts) and ts > cp_ts[cp_idx]:
            ts_cp = cp_ts[cp_idx]
            cp_realized[ts_cp] = state.realized
            cp_rewards[ts_cp] = state.rewards
            cp_unrealized_nomtm[ts_cp] = calc_unrealized(state, ts_cp, mtm=False)
            cp_unrealized_mtm[ts_cp] = calc_unrealized(state, ts_cp, mtm=True)
            cp_idx += 1

        realized_delta, rewards_delta = apply_event(state, event_type, obj)
        state.realized += realized_delta
        state.rewards += rewards_delta

        if WINDOW_START_TS <= ts <= WINDOW_END_TS:
            realized_period += realized_delta
            rewards_period += rewards_delta

    while cp_idx < len(cp_ts):
        ts_cp = cp_ts[cp_idx]
        cp_realized[ts_cp] = state.realized
        cp_rewards[ts_cp] = state.rewards
        cp_unrealized_nomtm[ts_cp] = calc_unrealized(state, ts_cp, mtm=False)
        cp_unrealized_mtm[ts_cp] = calc_unrealized(state, ts_cp, mtm=True)
        cp_idx += 1

    total_nomtm = {
        ts: cp_realized[ts] + cp_rewards[ts] + cp_unrealized_nomtm[ts]
        for ts in cp_ts
    }
    total_mtm = {
        ts: cp_realized[ts] + cp_rewards[ts] + cp_unrealized_mtm[ts]
        for ts in cp_ts
    }

    rows = []

    # a) Period realized PnL only
    a_val = realized_period
    rows.append(("a) Realized in period (excl rewards)", a_val))

    # b) Snapshot diff Feb16 - Jan16
    b_val = total_nomtm[FEB16_235959_TS] - total_nomtm[JAN16_235959_TS]
    rows.append(("b) Snapshot total_pnl(Feb16) - total_pnl(Jan16)", b_val))

    # c) Snapshot diff Feb16 - Jan17
    c_val = total_nomtm[FEB16_235959_TS] - total_nomtm[JAN17_000000_TS]
    rows.append(("c) Snapshot total_pnl(Feb16) - total_pnl(Jan17)", c_val))

    # d) realized + unrealized change (Jan17->Feb16)
    d_val = realized_period + (cp_unrealized_nomtm[FEB16_235959_TS] - cp_unrealized_nomtm[JAN17_000000_TS])
    rows.append(("d) Realized + unrealized change (no MTM)", d_val))

    # e) include rewards in period
    e_val = realized_period + rewards_period
    rows.append(("e) Realized in period + rewards in period", e_val))

    # f) MTM boundary variant(s)
    f1_val = realized_period + (cp_unrealized_mtm[FEB16_235959_TS] - cp_unrealized_mtm[JAN17_000000_TS])
    f2_val = total_mtm[FEB16_235959_TS] - total_mtm[JAN17_000000_TS]
    rows.append(("f1) Realized + unrealized change (MTM boundaries)", f1_val))
    rows.append(("f2) Snapshot total_pnl diff with MTM", f2_val))

    return {
        "rows": rows,
        "checkpoints": {
            "jan16_235959": {
                "ts": JAN16_235959_TS,
                "realized": cp_realized[JAN16_235959_TS],
                "rewards": cp_rewards[JAN16_235959_TS],
                "unrealized_nomtm": cp_unrealized_nomtm[JAN16_235959_TS],
                "unrealized_mtm": cp_unrealized_mtm[JAN16_235959_TS],
                "total_nomtm": total_nomtm[JAN16_235959_TS],
                "total_mtm": total_mtm[JAN16_235959_TS],
            },
            "jan17_000000": {
                "ts": JAN17_000000_TS,
                "realized": cp_realized[JAN17_000000_TS],
                "rewards": cp_rewards[JAN17_000000_TS],
                "unrealized_nomtm": cp_unrealized_nomtm[JAN17_000000_TS],
                "unrealized_mtm": cp_unrealized_mtm[JAN17_000000_TS],
                "total_nomtm": total_nomtm[JAN17_000000_TS],
                "total_mtm": total_mtm[JAN17_000000_TS],
            },
            "feb16_235959": {
                "ts": FEB16_235959_TS,
                "realized": cp_realized[FEB16_235959_TS],
                "rewards": cp_rewards[FEB16_235959_TS],
                "unrealized_nomtm": cp_unrealized_nomtm[FEB16_235959_TS],
                "unrealized_mtm": cp_unrealized_mtm[FEB16_235959_TS],
                "total_nomtm": total_nomtm[FEB16_235959_TS],
                "total_mtm": total_mtm[FEB16_235959_TS],
            },
        },
        "realized_period": realized_period,
        "rewards_period": rewards_period,
    }


def print_results_table(result):
    print("\n" + "=" * 120)
    print("MONTHLY AVG COST V3 RESULTS")
    print("Window: 2026-01-17 00:00:00 UTC -> 2026-02-16 23:59:59 UTC")
    print("Target profile value: $1,280.00")
    print("=" * 120)
    print(f"{'Variant':<66} {'PnL':>16} {'Gap vs $1,280':>18}")
    print("-" * 120)
    for label, value in result["rows"]:
        gap = value - TARGET_PROFILE_VALUE
        print(f"{label:<66} ${value:>15,.2f} ${gap:>+17,.2f}")
    print("-" * 120)

    print("\nCheckpoint states used:")
    for key, data in result["checkpoints"].items():
        print(
            f"{key:<14} ts={data['ts']} realized=${data['realized']:,.2f} rewards=${data['rewards']:,.2f} "
            f"unrl_no_mtm=${data['unrealized_nomtm']:,.2f} unrl_mtm=${data['unrealized_mtm']:,.2f} "
            f"total_no_mtm=${data['total_nomtm']:,.2f} total_mtm=${data['total_mtm']:,.2f}"
        )


def main():
    print_requested_api_json()
    trades, activities, events = collect_events()
    result = run_replay(events, trades, activities)
    print_results_table(result)


if __name__ == "__main__":
    main()