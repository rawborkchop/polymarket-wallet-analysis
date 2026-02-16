"""
Monthly PnL v3 investigation for wallet id=7.

Window: 2026-01-17 00:00:00 UTC -> 2026-02-16 23:59:59 UTC
Target profile value: $1,280

Variants tested:
  A) CLOSED POSITION PnL (cycle fully closed inside window; include full cycle lifetime PnL)
  B) DELTA PnL from PM timeseries endpoint (if available)
  C) HYBRID: realized in period + change in unrealized
  D) Additional combinations for comparison
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
TARGET = Decimal("1280")

WINDOW_START_TS = int(datetime(2026, 1, 17, 0, 0, 0, tzinfo=timezone.utc).timestamp())
WINDOW_END_TS = int(datetime(2026, 2, 16, 23, 59, 59, tzinfo=timezone.utc).timestamp())

EPS = Decimal("0.000001")
ONE = Decimal("1")
ZERO = Decimal("0")


def D(x) -> Decimal:
    return Decimal(str(x))


@dataclass
class Pos:
    shares: Decimal = ZERO
    avg_cost: Decimal = ZERO
    cycle_realized: Decimal = ZERO  # realized PnL for current open->close cycle

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
        self.cycle_realized += pnl
        return pnl

    def zero_out(self) -> Decimal:
        if self.shares <= EPS:
            return ZERO
        pnl = -self.shares * self.avg_cost
        self.shares = ZERO
        self.avg_cost = ZERO
        self.cycle_realized += pnl
        return pnl


@dataclass
class ReplayState:
    positions: Dict[Tuple[int, str], Pos] = field(default_factory=lambda: defaultdict(Pos))
    market_outcomes: Dict[int, Set[str]] = field(default_factory=lambda: defaultdict(set))
    market_resolution: Dict[int, Tuple[int, str]] = field(default_factory=dict)
    last_trade_price: Dict[Tuple[int, str], Decimal] = field(default_factory=dict)

    realized_total: Decimal = ZERO
    rewards_total: Decimal = ZERO

    realized_in_window: Decimal = ZERO
    rewards_in_window: Decimal = ZERO
    closed_cycle_pnl_in_window: Decimal = ZERO
    closed_cycle_count_in_window: int = 0

    market_cycle_realized: Dict[int, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    market_closed_cycle_pnl_in_window: Decimal = ZERO
    market_closed_cycle_count_in_window: int = 0


def make_sort_key(event_type: str, obj):
    if event_type == "trade":
        return (obj.timestamp, 0, obj.id)

    if obj.activity_type == "REDEEM":
        if D(obj.usdc_size) > 0:
            return (obj.timestamp, 1, obj.id)  # winner redeem first
        return (obj.timestamp, 3, obj.id)      # loser redeem last

    if obj.activity_type in ("SPLIT", "CONVERSION", "MERGE"):
        return (obj.timestamp, 0, obj.id)

    return (obj.timestamp, 2, obj.id)


def collect_events():
    wallet = Wallet.objects.get(id=WALLET_ID)
    trades = list(Trade.objects.filter(wallet=wallet).select_related("market").order_by("timestamp", "id"))
    activities = list(Activity.objects.filter(wallet=wallet).select_related("market").order_by("timestamp", "id"))

    events = [("trade", t) for t in trades] + [("activity", a) for a in activities]
    events.sort(key=lambda x: make_sort_key(x[0], x[1]))
    return trades, activities, events


def preload_market_data(state: ReplayState, trades: Iterable[Trade], activities: Iterable[Activity]):
    for t in trades:
        if t.market_id:
            state.market_outcomes[t.market_id].add(t.outcome)
            if t.market and t.market.resolved and t.market.resolution_timestamp:
                state.market_resolution[t.market_id] = (int(t.market.resolution_timestamp), t.market.winning_outcome)
    for a in activities:
        if a.market and a.market_id and a.market.resolved and a.market.resolution_timestamp:
            state.market_resolution[a.market_id] = (int(a.market.resolution_timestamp), a.market.winning_outcome)


def market_total_shares(state: ReplayState, market_id: int) -> Decimal:
    total = ZERO
    for (mid, _), pos in state.positions.items():
        if mid == market_id and pos.shares > EPS:
            total += pos.shares
    return total


def maybe_record_closed_cycle(state: ReplayState, key: Tuple[int, str], ts: int, shares_before: Decimal, shares_after: Decimal):
    if shares_before > EPS and shares_after <= EPS and WINDOW_START_TS <= ts <= WINDOW_END_TS:
        pos = state.positions[key]
        state.closed_cycle_pnl_in_window += pos.cycle_realized
        state.closed_cycle_count_in_window += 1
        pos.cycle_realized = ZERO


def maybe_record_market_cycle(state: ReplayState, market_id: int, ts: int, market_before: Decimal, market_after: Decimal):
    if market_before <= EPS and market_after > EPS:
        state.market_cycle_realized[market_id] = ZERO
    if market_before > EPS and market_after <= EPS and WINDOW_START_TS <= ts <= WINDOW_END_TS:
        state.market_closed_cycle_pnl_in_window += state.market_cycle_realized[market_id]
        state.market_closed_cycle_count_in_window += 1
        state.market_cycle_realized[market_id] = ZERO


def apply_event(state: ReplayState, event_type: str, obj):
    ts = int(obj.timestamp)

    if event_type == "trade":
        t = obj
        if not t.market_id:
            return
        market_before = market_total_shares(state, t.market_id)

        key = (t.market_id, t.outcome)
        state.market_outcomes[t.market_id].add(t.outcome)
        state.last_trade_price[key] = D(t.price)

        pos = state.positions[key]
        before = pos.shares

        if t.side == "BUY":
            delta = pos.buy(D(t.size), D(t.price))
        else:
            delta = pos.sell(D(t.size), D(t.price))

        state.realized_total += delta
        state.market_cycle_realized[t.market_id] += delta
        if WINDOW_START_TS <= ts <= WINDOW_END_TS:
            state.realized_in_window += delta

        maybe_record_closed_cycle(state, key, ts, before, pos.shares)
        market_after = market_total_shares(state, t.market_id)
        maybe_record_market_cycle(state, t.market_id, ts, market_before, market_after)
        return

    a = obj
    if a.activity_type == "REWARD":
        r = D(a.usdc_size)
        state.rewards_total += r
        if WINDOW_START_TS <= ts <= WINDOW_END_TS:
            state.rewards_in_window += r
        return

    if not a.market_id:
        return

    market_before = market_total_shares(state, a.market_id)
    size = D(a.size)
    usdc = D(a.usdc_size)

    if a.activity_type in ("SPLIT", "CONVERSION"):
        outcomes = state.market_outcomes.get(a.market_id, {"Yes", "No"})
        n = len(outcomes)
        if size > 0 and n > 0:
            cost_per_share = usdc / (size * n)
            for outcome in outcomes:
                key = (a.market_id, outcome)
                state.positions[key].buy(size, cost_per_share)

    elif a.activity_type == "MERGE":
        outcomes = state.market_outcomes.get(a.market_id, {"Yes", "No"})
        n = len(outcomes)
        if size > 0 and n > 0:
            rev_per_share = usdc / (size * n)
            for outcome in outcomes:
                key = (a.market_id, outcome)
                pos = state.positions[key]
                before = pos.shares
                delta = pos.sell(size, rev_per_share)
                state.realized_total += delta
                state.market_cycle_realized[a.market_id] += delta
                if WINDOW_START_TS <= ts <= WINDOW_END_TS:
                    state.realized_in_window += delta
                maybe_record_closed_cycle(state, key, ts, before, pos.shares)

    elif a.activity_type == "REDEEM":
        if usdc > 0:
            market_pos = [(k, v) for k, v in state.positions.items() if k[0] == a.market_id and v.shares > EPS]
            matched = False
            for key, pos in market_pos:
                if abs(pos.shares - size) < Decimal("0.5"):
                    before = pos.shares
                    delta = pos.sell(size, ONE)
                    state.realized_total += delta
                    state.market_cycle_realized[a.market_id] += delta
                    if WINDOW_START_TS <= ts <= WINDOW_END_TS:
                        state.realized_in_window += delta
                    maybe_record_closed_cycle(state, key, ts, before, pos.shares)
                    matched = True
                    break

            if not matched:
                remaining = size
                for key, pos in sorted(market_pos, key=lambda x: x[1].shares, reverse=True):
                    if remaining <= EPS:
                        break
                    before = pos.shares
                    qty = min(remaining, pos.shares)
                    delta = pos.sell(qty, ONE)
                    state.realized_total += delta
                    state.market_cycle_realized[a.market_id] += delta
                    if WINDOW_START_TS <= ts <= WINDOW_END_TS:
                        state.realized_in_window += delta
                    maybe_record_closed_cycle(state, key, ts, before, pos.shares)
                    remaining -= qty
        else:
            for key, pos in list(state.positions.items()):
                if key[0] == a.market_id and pos.shares > EPS:
                    before = pos.shares
                    delta = pos.zero_out()
                    state.realized_total += delta
                    state.market_cycle_realized[a.market_id] += delta
                    if WINDOW_START_TS <= ts <= WINDOW_END_TS:
                        state.realized_in_window += delta
                    maybe_record_closed_cycle(state, key, ts, before, pos.shares)

    market_after = market_total_shares(state, a.market_id)
    maybe_record_market_cycle(state, a.market_id, ts, market_before, market_after)


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
                mark = state.last_trade_price.get((market_id, outcome))

        if mark is None:
            mark = pos.avg_cost

        unrealized += pos.shares * (mark - pos.avg_cost)
    return unrealized


def fetch_timeseries_delta() -> Tuple[Optional[Decimal], str]:
    # Requested endpoint first (often 404 now), then one fallback variant.
    urls = [
        f"https://data-api.polymarket.com/v1/pnl/{WALLET_ADDRESS}?window=month",
        f"https://data-api.polymarket.com/pnl/{WALLET_ADDRESS}?window=month",
    ]

    for url in urls:
        try:
            r = requests.get(url, timeout=30)
            if r.status_code != 200:
                continue
            data = r.json()
            if not isinstance(data, list) or len(data) < 2:
                continue

            def pick_val(row):
                if not isinstance(row, dict):
                    return None
                for k in ("pnl", "value", "y", "p", "totalPnl"):
                    if k in row and row[k] is not None:
                        return D(row[k])
                return None

            first = pick_val(data[0])
            last = pick_val(data[-1])
            if first is None or last is None:
                continue

            return last - first, f"ok from {url}"
        except Exception:
            continue

    return None, "timeseries endpoint unavailable (all attempted URLs failed/non-JSON/non-list)"


def fetch_leaderboard_month() -> Optional[Decimal]:
    url = f"https://data-api.polymarket.com/v1/leaderboard?timePeriod=month&user={WALLET_ADDRESS}"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data and isinstance(data, list):
            return D(data[0].get("pnl", 0))
    except Exception:
        pass
    return None


def main():
    # Step 3 requested API call (print exact fields requested).
    print("=" * 100)
    print("Step 3: Requested PM month PnL timeseries API check")
    print("=" * 100)
    requested_url = f"https://data-api.polymarket.com/v1/pnl/{WALLET_ADDRESS}?window=month"
    try:
        r = requests.get(requested_url, timeout=30)
        data = r.json()
        print(f"Points: {len(data)}")
        print("First:", data[0] if data else "empty")
        print("Last:", data[-1] if data else "empty")
    except Exception as exc:
        print("Points: N/A")
        print("First: endpoint unavailable")
        print("Last: endpoint unavailable")
        print(f"Error: {exc}")

    trades, activities, events = collect_events()
    state = ReplayState()
    preload_market_data(state, trades, activities)

    # Snapshot unrealized at window boundaries (before/after replay crossing boundary).
    unrealized_start_no_mtm = ZERO
    unrealized_start_mtm = ZERO
    start_captured = False

    for etype, obj in events:
        ts = int(obj.timestamp)
        if (not start_captured) and ts > WINDOW_START_TS:
            unrealized_start_no_mtm = calc_unrealized(state, WINDOW_START_TS, mtm=False)
            unrealized_start_mtm = calc_unrealized(state, WINDOW_START_TS, mtm=True)
            start_captured = True
        apply_event(state, etype, obj)

    if not start_captured:
        unrealized_start_no_mtm = calc_unrealized(state, WINDOW_START_TS, mtm=False)
        unrealized_start_mtm = calc_unrealized(state, WINDOW_START_TS, mtm=True)

    unrealized_end_no_mtm = calc_unrealized(state, WINDOW_END_TS, mtm=False)
    unrealized_end_mtm = calc_unrealized(state, WINDOW_END_TS, mtm=True)

    timeseries_delta, ts_note = fetch_timeseries_delta()
    leaderboard_month = fetch_leaderboard_month()

    realized_ex_rewards = state.realized_in_window
    realized_inc_rewards = state.realized_in_window + state.rewards_in_window

    rows = []
    if leaderboard_month is not None:
        rows.append(("PM leaderboard month (reference)", leaderboard_month))

    if timeseries_delta is not None:
        rows.append(("B) PM timeseries delta (first->last)", timeseries_delta))

    rows.extend([
        ("A) Closed-position cycle PnL (full cycle lifetime)", state.closed_cycle_pnl_in_window),
        ("A2) Closed-market cycle PnL (all outcomes in market cycle)", state.market_closed_cycle_pnl_in_window),
        ("Realized in window (excl rewards)", realized_ex_rewards),
        ("Realized in window (incl rewards)", realized_inc_rewards),
        ("C1) Hybrid = realized(ex rewards)+dUnrealized(no MTM)", realized_ex_rewards + (unrealized_end_no_mtm - unrealized_start_no_mtm)),
        ("C2) Hybrid = realized(inc rewards)+dUnrealized(no MTM)", realized_inc_rewards + (unrealized_end_no_mtm - unrealized_start_no_mtm)),
        ("C3) Hybrid = realized(ex rewards)+dUnrealized(MTM)", realized_ex_rewards + (unrealized_end_mtm - unrealized_start_mtm)),
        ("C4) Hybrid = realized(inc rewards)+dUnrealized(MTM)", realized_inc_rewards + (unrealized_end_mtm - unrealized_start_mtm)),
        ("D) Closed-cycle + rewards in window", state.closed_cycle_pnl_in_window + state.rewards_in_window),
    ])

    print("\n" + "=" * 100)
    print("Step 5: Comparison table vs target $1,280")
    print("=" * 100)
    print(f"{'Method':<62} {'PnL':>14} {'Diff vs 1280':>16}")
    print("-" * 100)
    for label, val in rows:
        print(f"{label:<62} ${val:>13,.2f} ${val - TARGET:>+15,.2f}")
    print("-" * 100)
    print(f"Closed position-cycles counted in window: {state.closed_cycle_count_in_window}")
    print(f"Closed market-cycles counted in window:   {state.market_closed_cycle_count_in_window}")
    print(f"Unrealized start(no MTM): ${unrealized_start_no_mtm:,.2f} | end(no MTM): ${unrealized_end_no_mtm:,.2f}")
    print(f"Unrealized start(MTM):    ${unrealized_start_mtm:,.2f} | end(MTM):    ${unrealized_end_mtm:,.2f}")
    print(f"Timeseries status: {ts_note}")


if __name__ == "__main__":
    main()
