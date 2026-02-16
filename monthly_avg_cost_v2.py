"""
Monthly Avg Cost PnL v2 - fixed-window investigation.

Required window:
  2026-01-17 00:00 UTC -> 2026-02-16 23:59 UTC

This script:
1) Prints raw responses from requested Polymarket APIs.
2) Replays full wallet history with average-cost accounting.
3) Computes:
   - Realized-only PnL inside fixed window
   - Snapshot diffs for total_pnl(Feb 16) - total_pnl(Jan 17)
   - Snapshot diffs for total_pnl(Feb 16) - total_pnl(Jan 16)
   - Variants including unrealized PnL change
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

JAN16_2359_TS = int(datetime(2026, 1, 16, 23, 59, 59, tzinfo=timezone.utc).timestamp())
JAN17_0000_TS = WINDOW_START_TS
JAN17_2359_TS = int(datetime(2026, 1, 17, 23, 59, 59, tzinfo=timezone.utc).timestamp())
FEB16_2359_TS = WINDOW_END_TS

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


def print_api_responses():
    urls = [
        (
            "Leaderboard month",
            f"https://data-api.polymarket.com/v1/leaderboard?timePeriod=month&user={WALLET_ADDRESS}",
        ),
        (
            "PnL timeseries month",
            f"https://data-api.polymarket.com/v1/pnl/{WALLET_ADDRESS}?window=month",
        ),
        (
            "Profile volume endpoint",
            f"https://polymarket.com/api/profile/volume?address={WALLET_ADDRESS}",
        ),
    ]
    print("=" * 120)
    print("STEP 1: RAW API RESPONSES")
    print("=" * 120)
    for label, url in urls:
        print(f"\n[{label}]")
        print(f"URL: {url}")
        try:
            resp = requests.get(url, timeout=45)
            print(f"HTTP {resp.status_code}")
            print("BODY:")
            try:
                payload = resp.json()
                print(json.dumps(payload, indent=2, sort_keys=True))
            except ValueError:
                # Escape non-console-safe unicode while preserving exact content.
                print(resp.text.encode("unicode_escape").decode("ascii"))
        except Exception as exc:
            print(f"REQUEST FAILED: {exc}")


def collect_events():
    wallet = Wallet.objects.get(id=WALLET_ID)
    trades = list(
        Trade.objects.filter(wallet=wallet).select_related("market").order_by("timestamp", "id")
    )
    activities = list(
        Activity.objects.filter(wallet=wallet).select_related("market").order_by("timestamp", "id")
    )
    events = [("trade", t) for t in trades] + [("activity", a) for a in activities]
    events.sort(key=lambda x: make_sort_key(x[0], x[1]))
    return trades, activities, events


def preload_market_data(state: ReplayState, trades: Iterable[Trade], activities: Iterable[Activity]):
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


def current_unrealized(state: ReplayState, asof_ts: int) -> Decimal:
    unrealized = ZERO
    for (market_id, outcome), pos in state.positions.items():
        if pos.shares <= EPS:
            continue
        mark: Optional[Decimal] = None

        resolved = state.market_resolution.get(market_id)
        if resolved and asof_ts >= resolved[0]:
            winning_outcome = resolved[1]
            mark = ONE if outcome == winning_outcome else ZERO
        else:
            mark = state.last_wallet_trade_price.get((market_id, outcome))

        if mark is None:
            mark = pos.avg_cost

        unrealized += pos.shares * (mark - pos.avg_cost)

    return unrealized


def replay_with_checkpoints(events, checkpoints: List[int]):
    state = ReplayState()
    checkpoint_totals = {}
    checkpoint_unrealized = {}

    realized_window_ex_rewards = ZERO
    realized_window_inc_rewards = ZERO

    sorted_cp = sorted(checkpoints)
    cp_idx = 0

    for event_type, obj in events:
        ts = int(obj.timestamp)

        while cp_idx < len(sorted_cp) and ts > sorted_cp[cp_idx]:
            cp_ts = sorted_cp[cp_idx]
            cp_unrealized = current_unrealized(state, cp_ts)
            checkpoint_unrealized[cp_ts] = cp_unrealized
            checkpoint_totals[cp_ts] = state.realized + state.rewards + cp_unrealized
            cp_idx += 1

        realized_delta, rewards_delta = apply_event(state, event_type, obj)
        state.realized += realized_delta
        state.rewards += rewards_delta

        if WINDOW_START_TS <= ts <= WINDOW_END_TS:
            realized_window_ex_rewards += realized_delta
            realized_window_inc_rewards += realized_delta + rewards_delta

    while cp_idx < len(sorted_cp):
        cp_ts = sorted_cp[cp_idx]
        cp_unrealized = current_unrealized(state, cp_ts)
        checkpoint_unrealized[cp_ts] = cp_unrealized
        checkpoint_totals[cp_ts] = state.realized + state.rewards + cp_unrealized
        cp_idx += 1

    return {
        "checkpoint_totals": checkpoint_totals,
        "checkpoint_unrealized": checkpoint_unrealized,
        "realized_window_ex_rewards": realized_window_ex_rewards,
        "realized_window_inc_rewards": realized_window_inc_rewards,
    }


def print_results(result):
    totals = result["checkpoint_totals"]
    unrl = result["checkpoint_unrealized"]

    variants = []

    total_diff_jan17_0000 = totals[FEB16_2359_TS] - totals[JAN17_0000_TS]
    total_diff_jan17_2359 = totals[FEB16_2359_TS] - totals[JAN17_2359_TS]
    total_diff_jan16_2359 = totals[FEB16_2359_TS] - totals[JAN16_2359_TS]

    unrealized_delta_jan17_0000 = unrl[FEB16_2359_TS] - unrl[JAN17_0000_TS]
    unrealized_delta_jan17_2359 = unrl[FEB16_2359_TS] - unrl[JAN17_2359_TS]
    unrealized_delta_jan16_2359 = unrl[FEB16_2359_TS] - unrl[JAN16_2359_TS]

    variants.append(("Realized only (window, excl rewards)", result["realized_window_ex_rewards"]))
    variants.append(("Realized only (window, incl rewards)", result["realized_window_inc_rewards"]))
    variants.append(("Snapshot total_pnl Feb16 - Jan17 00:00", total_diff_jan17_0000))
    variants.append(("Snapshot total_pnl Feb16 - Jan17 23:59", total_diff_jan17_2359))
    variants.append(("Snapshot total_pnl Feb16 - Jan16 23:59", total_diff_jan16_2359))
    variants.append(
        (
            "Realized(window, excl rewards) + unrealized change (Jan17 00:00->Feb16)",
            result["realized_window_ex_rewards"] + unrealized_delta_jan17_0000,
        )
    )
    variants.append(
        (
            "Realized(window, incl rewards) + unrealized change (Jan17 00:00->Feb16)",
            result["realized_window_inc_rewards"] + unrealized_delta_jan17_0000,
        )
    )
    variants.append(
        (
            "Realized(window, excl rewards) + unrealized change (Jan16 23:59->Feb16)",
            result["realized_window_ex_rewards"] + unrealized_delta_jan16_2359,
        )
    )
    variants.append(
        (
            "Realized(window, incl rewards) + unrealized change (Jan16 23:59->Feb16)",
            result["realized_window_inc_rewards"] + unrealized_delta_jan16_2359,
        )
    )

    print("\n" + "=" * 120)
    print("STEP 3: MONTHLY AVG COST V2 VARIATIONS")
    print("=" * 120)
    print("Window (inclusive): 2026-01-17 00:00:00 UTC -> 2026-02-16 23:59:59 UTC")
    print(
        f"{'Variant':<78} {'PnL':>14} {'Diff vs $1,280':>18}"
    )
    print("-" * 120)
    for label, value in variants:
        diff = value - TARGET_PROFILE_VALUE
        print(f"{label:<78} ${value:>13,.2f} ${diff:>+17,.2f}")
    print("-" * 120)

    print("\nCheckpoint totals/unrealized used for snapshot diffs:")
    cp_rows = [
        ("Jan 16 23:59", JAN16_2359_TS),
        ("Jan 17 00:00", JAN17_0000_TS),
        ("Jan 17 23:59", JAN17_2359_TS),
        ("Feb 16 23:59", FEB16_2359_TS),
    ]
    for label, ts in cp_rows:
        print(
            f"{label:<14} ts={ts} total_pnl=${totals[ts]:,.2f} unrealized=${unrl[ts]:,.2f}"
        )

    closest = min(variants, key=lambda x: abs(x[1] - TARGET_PROFILE_VALUE))
    print("\nClosest to $1,280:")
    print(
        f"{closest[0]} => ${closest[1]:,.2f} (diff ${closest[1] - TARGET_PROFILE_VALUE:+,.2f})"
    )


def main():
    print_api_responses()
    trades, activities, events = collect_events()
    checkpoints = [JAN16_2359_TS, JAN17_0000_TS, JAN17_2359_TS, FEB16_2359_TS]
    state_result = replay_with_checkpoints(events, checkpoints)
    print_results(state_result)


if __name__ == "__main__":
    main()
