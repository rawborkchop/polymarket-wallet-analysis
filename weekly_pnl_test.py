"""
Weekly PnL validation for wallet id=7 using avg-cost replay.

Task goals:
1) Reuse the same all-time replay approach as simulate_avg_cost.py:
   - position-level average cost
   - trades-only position creation (no split-created positions)
   - winner-first redeem ordering
2) Compare multiple weekly windows (7/8/9/10 days back from Feb 16, 2026)
3) For each window, compute:
   - realized-only PnL in period (incl rewards)
   - snapshot diff: total_pnl(end) - total_pnl(start)
4) Compare against Polymarket weekly reference values.
"""

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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

# As requested: "Today: Feb 16, 2026"
ASOF_END_DT = datetime(2026, 2, 16, 23, 59, 59, tzinfo=timezone.utc)
WINDOW_DAYS = [7, 8, 9, 10]

# Optional profile reference from manual web UI check (1W tab on profile page).
# Set to None if you want to disable comparison.
PROFILE_WEEKLY_REFERENCE = Decimal("7.56")

EPS = Decimal("0.000001")
ONE = Decimal("1")
ZERO = Decimal("0")


def D(x) -> Decimal:
    return Decimal(str(x))


@dataclass
class Pos:
    shares: Decimal = ZERO
    avg_cost: Decimal = ZERO

    def buy(self, size: Decimal, price: Decimal) -> Decimal:
        old = self.shares * self.avg_cost
        self.shares += size
        if self.shares > EPS:
            self.avg_cost = (old + size * price) / self.shares
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
    last_trade_price: Dict[Tuple[int, str], Decimal] = field(default_factory=dict)

    realized_total: Decimal = ZERO
    rewards_total: Decimal = ZERO


@dataclass
class EventDelta:
    ts: int
    realized: Decimal = ZERO
    rewards: Decimal = ZERO



def make_sort_key(event_type: str, obj):
    """Winner redeems before loser redeems at same timestamp, trades first."""
    if event_type == "trade":
        return (obj.timestamp, 0, obj.id)

    if obj.activity_type == "REDEEM":
        if D(obj.usdc_size) > 0:
            return (obj.timestamp, 1, obj.id)  # winner first
        return (obj.timestamp, 3, obj.id)      # loser last

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


def apply_event(state: ReplayState, event_type: str, obj) -> EventDelta:
    ts = int(obj.timestamp)
    delta = EventDelta(ts=ts)

    if event_type == "trade":
        t = obj
        if not t.market_id:
            return delta

        key = (t.market_id, t.outcome)
        state.market_outcomes[t.market_id].add(t.outcome)

        price = D(t.price)
        size = D(t.size)
        state.last_trade_price[key] = price

        pos = state.positions[key]
        if t.side == "BUY":
            delta.realized += pos.buy(size, price)
        else:
            delta.realized += pos.sell(size, price)

        state.realized_total += delta.realized
        return delta

    a = obj
    if a.activity_type == "REWARD":
        delta.rewards += D(a.usdc_size)
        state.rewards_total += delta.rewards
        return delta

    if not a.market_id:
        return delta

    size = D(a.size)
    usdc = D(a.usdc_size)

    # trades-only position creation: ignore SPLIT/CONVERSION additions
    if a.activity_type in ("SPLIT", "CONVERSION"):
        return delta

    if a.activity_type == "MERGE":
        outcomes = state.market_outcomes.get(a.market_id, {"Yes", "No"})
        n = len(outcomes)
        if size > 0 and n > 0:
            rev_per_share = usdc / (size * n)
            for outcome in outcomes:
                key = (a.market_id, outcome)
                pos = state.positions[key]
                if pos.shares > EPS:
                    delta.realized += pos.sell(min(size, pos.shares), rev_per_share)

    elif a.activity_type == "REDEEM":
        if usdc > 0:
            market_pos = [(k, v) for k, v in state.positions.items() if k[0] == a.market_id and v.shares > EPS]
            matched = False
            for key, pos in market_pos:
                if abs(pos.shares - size) < Decimal("0.5"):
                    delta.realized += pos.sell(size, ONE)
                    matched = True
                    break
            if not matched:
                remaining = size
                for key, pos in sorted(market_pos, key=lambda x: x[1].shares, reverse=True):
                    if remaining <= EPS:
                        break
                    qty = min(remaining, pos.shares)
                    delta.realized += pos.sell(qty, ONE)
                    remaining -= qty
        else:
            for key, pos in list(state.positions.items()):
                if key[0] == a.market_id and pos.shares > EPS:
                    delta.realized += pos.zero_out()

    state.realized_total += delta.realized
    return delta


def calc_unrealized(state: ReplayState, asof_ts: int, mtm: bool = True) -> Decimal:
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


def replay_all() -> Tuple[ReplayState, List[EventDelta]]:
    trades, activities, events = collect_events()
    state = ReplayState()
    preload_market_data(state, trades, activities)

    deltas: List[EventDelta] = []
    for etype, obj in events:
        d = apply_event(state, etype, obj)
        deltas.append(d)

    return state, deltas


def cumulative_realized_rewards_at(deltas: List[EventDelta], cutoff_ts: int) -> Decimal:
    total = ZERO
    for d in deltas:
        if d.ts <= cutoff_ts:
            total += d.realized + d.rewards
        else:
            break
    return total


def replay_to_timestamp(end_ts: int) -> ReplayState:
    trades, activities, events = collect_events()
    state = ReplayState()
    preload_market_data(state, trades, activities)

    for etype, obj in events:
        if int(obj.timestamp) > end_ts:
            break
        apply_event(state, etype, obj)

    return state


def fetch_weekly_refs() -> Dict[str, Optional[Decimal]]:
    refs: Dict[str, Optional[Decimal]] = {
        "leaderboard_week": None,
        "timeseries_week_delta": None,
    }

    lb_url = f"https://data-api.polymarket.com/v1/leaderboard?timePeriod=week&user={WALLET_ADDRESS}"
    pnl_url = f"https://data-api.polymarket.com/v1/pnl/{WALLET_ADDRESS}?window=week"

    print("=" * 110)
    print("STEP A: POLYMARKET WEEKLY API CHECKS")
    print("=" * 110)

    try:
        r = requests.get(lb_url, timeout=30)
        print(f"Leaderboard URL: {lb_url}")
        print(f"HTTP {r.status_code}")
        payload = r.json()
        print("Body:")
        print(json.dumps(payload, indent=2))
        if isinstance(payload, list) and payload:
            refs["leaderboard_week"] = D(payload[0].get("pnl", 0))
    except Exception as exc:
        print(f"Leaderboard request failed: {exc}")

    print("-" * 110)

    try:
        r = requests.get(pnl_url, timeout=30)
        print(f"PnL timeseries URL: {pnl_url}")
        print(f"HTTP {r.status_code}")
        try:
            payload = r.json()
            kind = type(payload).__name__
            ln = len(payload) if isinstance(payload, list) else "n/a"
            print(f"Parsed JSON type={kind}, len={ln}")
            if isinstance(payload, list) and len(payload) >= 2:
                def pick_val(row):
                    if not isinstance(row, dict):
                        return None
                    for k in ("pnl", "value", "y", "p", "totalPnl"):
                        if k in row and row[k] is not None:
                            return D(row[k])
                    return None

                first = pick_val(payload[0])
                last = pick_val(payload[-1])
                if first is not None and last is not None:
                    refs["timeseries_week_delta"] = last - first
                print("First:", payload[0])
                print("Last:", payload[-1])
            else:
                print("Body:", payload)
        except Exception:
            print("Body (non-JSON):")
            print(r.text[:400].encode("unicode_escape").decode())
    except Exception as exc:
        print(f"Timeseries request failed: {exc}")

    return refs


def fmt_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def main():
    refs = fetch_weekly_refs()

    print("\n" + "=" * 110)
    print("STEP B: AVG-COST WEEKLY WINDOW TESTS (7/8/9/10 days back from 2026-02-16)")
    print("=" * 110)

    # One full replay to obtain event-level realized/reward deltas.
    _, all_deltas = replay_all()

    # Sort just in case (collect_events already sorted).
    all_deltas.sort(key=lambda x: x.ts)

    lb = refs.get("leaderboard_week")
    profile_ref = PROFILE_WEEKLY_REFERENCE

    header = (
        f"{'Days':>4}  {'Window Start (UTC)':<20}  {'Window End (UTC)':<20}  "
        f"{'RealizedSum':>12}  {'SnapDiff(total)':>15}"
    )
    if lb is not None:
        header += f"  {'Diff vs LB':>11}"
    if profile_ref is not None:
        header += f"  {'Diff vs Profile':>15}"

    print(header)
    print("-" * len(header))

    end_ts = int(ASOF_END_DT.timestamp())

    for days in WINDOW_DAYS:
        # Inclusive day window, e.g. 7D => Feb10 00:00:00 .. Feb16 23:59:59
        start_dt = (ASOF_END_DT - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0)
        start_ts = int(start_dt.timestamp())

        # Method 1: realized in window (incl rewards)
        start_cum = cumulative_realized_rewards_at(all_deltas, start_ts - 1)
        end_cum = cumulative_realized_rewards_at(all_deltas, end_ts)
        realized_sum = end_cum - start_cum

        # Method 2: snapshot diff of total_pnl = realized+rewards+unrealized(MTM)
        start_state = replay_to_timestamp(start_ts - 1)
        end_state = replay_to_timestamp(end_ts)

        start_total = (start_state.realized_total + start_state.rewards_total + calc_unrealized(start_state, start_ts - 1, mtm=True))
        end_total = (end_state.realized_total + end_state.rewards_total + calc_unrealized(end_state, end_ts, mtm=True))
        snap_diff = end_total - start_total

        row = (
            f"{days:>4}  {fmt_dt(start_ts):<20}  {fmt_dt(end_ts):<20}  "
            f"${realized_sum:>11,.2f}  ${snap_diff:>14,.2f}"
        )
        if lb is not None:
            row += f"  ${realized_sum - lb:>+10,.2f}"
        if profile_ref is not None:
            row += f"  ${realized_sum - profile_ref:>+14,.2f}"
        print(row)

    print("\n" + "=" * 110)
    print("STEP C: REFERENCES")
    print("=" * 110)
    print(f"Leaderboard weekly pnl: {('$' + format(lb, ',.2f')) if lb is not None else 'N/A'}")
    print(
        "PnL timeseries weekly delta: "
        f"{('$' + format(refs['timeseries_week_delta'], ',.2f')) if refs['timeseries_week_delta'] is not None else 'N/A (endpoint unavailable or non-timeseries)'}"
    )
    print(
        "Profile weekly pnl (manual UI check): "
        f"{('$' + format(profile_ref, ',.2f')) if profile_ref is not None else 'N/A'}"
    )


if __name__ == "__main__":
    main()
