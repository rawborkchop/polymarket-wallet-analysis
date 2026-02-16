"""
Manual weekly PnL reconstruction for wallet id=7.

Goal: investigate how Polymarket profile weekly PnL = $7.56 could be computed.
Date context: Feb 16, 2026.
"""

import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from itertools import combinations
from typing import Dict, List, Optional, Set, Tuple

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

from wallet_analysis.models import Activity, Trade, Wallet  # noqa: E402


WALLET_ID = 7
TARGET = Decimal("7.56")
EPS = Decimal("0.000001")
ZERO = Decimal("0")
ONE = Decimal("1")

# "Today" fixed by task prompt.
ASOF_TS = int(datetime(2026, 2, 16, 23, 59, 59, tzinfo=timezone.utc).timestamp())
CUTOFF_7D_TS = int(datetime(2026, 2, 9, 0, 0, 0, tzinfo=timezone.utc).timestamp())
CUTOFF_10D_TS = int(datetime(2026, 2, 6, 0, 0, 0, tzinfo=timezone.utc).timestamp())


def D(x) -> Decimal:
    return Decimal(str(x))


@dataclass
class Pos:
    shares: Decimal = ZERO
    avg_cost: Decimal = ZERO

    def buy(self, qty: Decimal, price: Decimal) -> Decimal:
        old_cost = self.shares * self.avg_cost
        self.shares += qty
        if self.shares > EPS:
            self.avg_cost = (old_cost + qty * price) / self.shares
        return ZERO

    def sell(self, qty: Decimal, price: Decimal) -> Decimal:
        if self.shares <= EPS:
            return ZERO
        close_qty = min(qty, self.shares)
        pnl = close_qty * (price - self.avg_cost)
        self.shares -= close_qty
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
class EventRow:
    idx: int
    ts: int
    dt: datetime
    source: str
    etype: str
    market_id: Optional[int]
    market_tag: str
    outcome: str
    asset: str
    side: str
    size: Decimal
    price: Decimal
    gross: Decimal
    cashflow: Decimal
    realized_avg_cost: Decimal = ZERO
    reward_component: Decimal = ZERO
    raw_amount: Decimal = ZERO


@dataclass
class ReplayState:
    positions: Dict[Tuple[int, str], Pos] = field(default_factory=lambda: defaultdict(Pos))
    market_outcomes: Dict[int, Set[str]] = field(default_factory=lambda: defaultdict(set))
    market_resolution: Dict[int, Tuple[int, str]] = field(default_factory=dict)
    last_wallet_trade_price: Dict[Tuple[int, str], Decimal] = field(default_factory=dict)
    realized_total: Decimal = ZERO
    rewards_total: Decimal = ZERO


def sort_key(event_type, obj):
    # Keep order deterministic and friendly to split/merge/redeem handling.
    if event_type == "trade":
        return (obj.timestamp, 0, obj.id)

    if obj.activity_type == "REDEEM":
        # positive redeem before negative redeem at same timestamp
        rank = 1 if D(obj.usdc_size) > 0 else 3
        return (obj.timestamp, rank, obj.id)

    if obj.activity_type in ("SPLIT", "CONVERSION", "MERGE"):
        return (obj.timestamp, 0, obj.id)

    return (obj.timestamp, 2, obj.id)


def market_tag_for(obj) -> str:
    if getattr(obj, "market", None):
        m = obj.market
        if m.slug:
            return m.slug
        if m.condition_id:
            return m.condition_id[:10]
    return "none"


def collect_all_events(wallet):
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
    all_events = [("trade", t) for t in trades] + [("activity", a) for a in activities]
    all_events.sort(key=lambda x: sort_key(x[0], x[1]))
    return trades, activities, all_events


def preload(state: ReplayState, trades: List[Trade], activities: List[Activity]):
    for t in trades:
        if t.market_id:
            state.market_outcomes[t.market_id].add(t.outcome)
            if t.market and t.market.resolved and t.market.resolution_timestamp:
                state.market_resolution[t.market_id] = (
                    int(t.market.resolution_timestamp),
                    t.market.winning_outcome,
                )
    for a in activities:
        if a.market_id and a.market and a.market.resolved and a.market.resolution_timestamp:
            state.market_resolution[a.market_id] = (
                int(a.market.resolution_timestamp),
                a.market.winning_outcome,
            )


def apply_event(state: ReplayState, etype: str, obj) -> Tuple[Decimal, Decimal]:
    realized = ZERO
    reward = ZERO

    if etype == "trade":
        if not obj.market_id:
            return realized, reward

        key = (obj.market_id, obj.outcome)
        qty = D(obj.size)
        px = D(obj.price)
        state.market_outcomes[obj.market_id].add(obj.outcome)
        state.last_wallet_trade_price[key] = px

        if obj.side == "BUY":
            realized += state.positions[key].buy(qty, px)
        else:
            realized += state.positions[key].sell(qty, px)
        return realized, reward

    a = obj
    if a.activity_type == "REWARD":
        reward += D(a.usdc_size)
        return realized, reward

    if not a.market_id:
        return realized, reward

    qty = D(a.size)
    usdc = D(a.usdc_size)

    if a.activity_type in ("SPLIT", "CONVERSION"):
        outcomes = state.market_outcomes.get(a.market_id, {"Yes", "No"})
        n = len(outcomes) if outcomes else 2
        if qty > 0 and n > 0:
            cost = usdc / (qty * n)
            for out in outcomes:
                state.positions[(a.market_id, out)].buy(qty, cost)

    elif a.activity_type == "MERGE":
        outcomes = state.market_outcomes.get(a.market_id, {"Yes", "No"})
        n = len(outcomes) if outcomes else 2
        if qty > 0 and n > 0:
            rev = usdc / (qty * n)
            for out in outcomes:
                realized += state.positions[(a.market_id, out)].sell(qty, rev)

    elif a.activity_type == "REDEEM":
        if usdc > 0:
            market_pos = [
                (k, p)
                for k, p in state.positions.items()
                if k[0] == a.market_id and p.shares > EPS
            ]

            # winner-first redeem ordering (if known); then by largest shares.
            winner = None
            resolved = state.market_resolution.get(a.market_id)
            if resolved:
                winner = resolved[1]

            ordered = []
            if winner:
                ordered.extend([x for x in market_pos if x[0][1] == winner])
                ordered.extend([x for x in market_pos if x[0][1] != winner])
            else:
                ordered = list(market_pos)
            ordered.sort(key=lambda x: x[1].shares, reverse=True)

            remaining = qty
            for _, p in ordered:
                if remaining <= EPS:
                    break
                close_qty = min(remaining, p.shares)
                realized += p.sell(close_qty, ONE)
                remaining -= close_qty

        else:
            for key, p in list(state.positions.items()):
                if key[0] == a.market_id:
                    realized += p.zero_out()

    return realized, reward


def calc_unrealized(state: ReplayState, asof_ts: int, mtm: bool) -> Decimal:
    total = ZERO
    for (market_id, outcome), p in state.positions.items():
        if p.shares <= EPS:
            continue

        mark = None
        if mtm:
            res = state.market_resolution.get(market_id)
            if res and asof_ts >= res[0]:
                mark = ONE if outcome == res[1] else ZERO
            else:
                mark = state.last_wallet_trade_price.get((market_id, outcome))

        if mark is None:
            mark = p.avg_cost

        total += p.shares * (mark - p.avg_cost)

    return total


def event_row_from_obj(idx: int, etype: str, obj) -> EventRow:
    if etype == "trade":
        side = obj.side
        gross = D(obj.total_value)
        cashflow = -gross if side == "BUY" else gross
        raw = gross
        return EventRow(
            idx=idx,
            ts=int(obj.timestamp),
            dt=obj.datetime,
            source="TRADE",
            etype=obj.side,
            market_id=obj.market_id,
            market_tag=market_tag_for(obj),
            outcome=obj.outcome,
            asset=obj.asset,
            side=obj.side,
            size=D(obj.size),
            price=D(obj.price),
            gross=gross,
            cashflow=cashflow,
            raw_amount=raw,
        )

    a = obj
    gross = D(a.usdc_size)
    if a.activity_type in ("SPLIT", "CONVERSION"):
        cashflow = -gross
    else:
        cashflow = gross

    return EventRow(
        idx=idx,
        ts=int(a.timestamp),
        dt=a.datetime,
        source="ACTIVITY",
        etype=a.activity_type,
        market_id=a.market_id,
        market_tag=market_tag_for(a),
        outcome=a.outcome,
        asset=a.asset,
        side="",
        size=D(a.size),
        price=ZERO,
        gross=gross,
        cashflow=cashflow,
        raw_amount=gross,
    )


def search_subsets(rows: List[EventRow], attr: str, target: Decimal, tolerance: Decimal = Decimal("0.02"), max_hits: int = 40):
    vals = [getattr(r, attr) for r in rows]
    n = len(rows)
    hits = []

    # Exhaustive if manageable.
    if n <= 24:
        for r in range(1, n + 1):
            for idxs in combinations(range(n), r):
                s = sum(vals[i] for i in idxs)
                if abs(s - target) <= tolerance:
                    hits.append((s, idxs))
                    if len(hits) >= max_hits:
                        return hits
    else:
        # Fallback: try subset sizes up to 6 only.
        for r in range(1, 7):
            for idxs in combinations(range(n), r):
                s = sum(vals[i] for i in idxs)
                if abs(s - target) <= tolerance:
                    hits.append((s, idxs))
                    if len(hits) >= max_hits:
                        return hits

    return hits


def fmt_money(x: Decimal) -> str:
    return f"${x:,.4f}"


def main():
    wallet = Wallet.objects.get(id=WALLET_ID)
    trades, activities, all_events = collect_all_events(wallet)

    print("=" * 140)
    print("WEEKLY MANUAL ANALYSIS")
    print("=" * 140)
    print(f"Wallet id={wallet.id} address={wallet.address}")
    print(f"As-of: {datetime.fromtimestamp(ASOF_TS, tz=timezone.utc)} UTC")
    print(f"Target profile weekly PnL: {fmt_money(TARGET)}")
    print(f"Data counts: trades={len(trades)} activities={len(activities)} total_events={len(all_events)}")

    state = ReplayState()
    preload(state, trades, activities)

    rows_7d: List[EventRow] = []
    rows_10d: List[EventRow] = []

    realized_at_7d_start = ZERO
    rewards_at_7d_start = ZERO
    unreal_no_mtm_at_7d_start = ZERO
    unreal_mtm_at_7d_start = ZERO

    checkpoint_taken = False

    for idx, (etype, obj) in enumerate(all_events, start=1):
        ts = int(obj.timestamp)

        if (not checkpoint_taken) and ts >= CUTOFF_7D_TS:
            realized_at_7d_start = state.realized_total
            rewards_at_7d_start = state.rewards_total
            unreal_no_mtm_at_7d_start = calc_unrealized(state, CUTOFF_7D_TS, mtm=False)
            unreal_mtm_at_7d_start = calc_unrealized(state, CUTOFF_7D_TS, mtm=True)
            checkpoint_taken = True

        row = event_row_from_obj(idx, etype, obj)
        realized_delta, reward_delta = apply_event(state, etype, obj)
        state.realized_total += realized_delta
        state.rewards_total += reward_delta

        row.realized_avg_cost = realized_delta
        row.reward_component = reward_delta

        if ts >= CUTOFF_7D_TS:
            rows_7d.append(row)
        if ts >= CUTOFF_10D_TS:
            rows_10d.append(row)

    if not checkpoint_taken:
        realized_at_7d_start = state.realized_total
        rewards_at_7d_start = state.rewards_total
        unreal_no_mtm_at_7d_start = calc_unrealized(state, CUTOFF_7D_TS, mtm=False)
        unreal_mtm_at_7d_start = calc_unrealized(state, CUTOFF_7D_TS, mtm=True)

    realized_at_end = state.realized_total
    rewards_at_end = state.rewards_total
    unreal_no_mtm_at_end = calc_unrealized(state, ASOF_TS, mtm=False)
    unreal_mtm_at_end = calc_unrealized(state, ASOF_TS, mtm=True)

    print("\n" + "=" * 140)
    print("1) ALL EVENTS IN LAST 10 DAYS")
    print("=" * 140)
    for r in rows_10d:
        print(
            f"[{r.idx:04d}] {r.dt} ts={r.ts} {r.source}:{r.etype:<10} market={r.market_tag:<28} "
            f"outcome={r.outcome[:12]:<12} size={r.size:>12,.6f} price={r.price:>9,.6f} "
            f"gross={fmt_money(r.gross):>14} cashflow={fmt_money(r.cashflow):>14} "
            f"realized={fmt_money(r.realized_avg_cost):>14} reward={fmt_money(r.reward_component):>12}"
        )

    print("\n" + "=" * 140)
    print("2) EVENTS IN LAST 7 DAYS (used for weekly hypotheses)")
    print("=" * 140)
    for r in rows_7d:
        print(
            f"[{r.idx:04d}] {r.dt} {r.source}:{r.etype:<10} market={r.market_tag:<28} "
            f"cashflow={fmt_money(r.cashflow):>12} realized={fmt_money(r.realized_avg_cost):>12} reward={fmt_money(r.reward_component):>12}"
        )

    # Totals by interpretation over 7d events
    cf_7d = sum(r.cashflow for r in rows_7d)
    realized_7d = sum(r.realized_avg_cost for r in rows_7d)
    rewards_7d = sum(r.reward_component for r in rows_7d)
    raw_7d = sum(r.raw_amount for r in rows_7d)

    sells_only_7d = sum(r.cashflow for r in rows_7d if r.source == "TRADE" and r.etype == "SELL")
    buys_only_7d = sum(-r.cashflow for r in rows_7d if r.source == "TRADE" and r.etype == "BUY")
    redeems_only_7d = sum(r.cashflow for r in rows_7d if r.source == "ACTIVITY" and r.etype == "REDEEM")
    rewards_only_7d = sum(r.reward_component for r in rows_7d)

    total_no_mtm_start = realized_at_7d_start + rewards_at_7d_start + unreal_no_mtm_at_7d_start
    total_no_mtm_end = realized_at_end + rewards_at_end + unreal_no_mtm_at_end
    snapshot_delta_no_mtm = total_no_mtm_end - total_no_mtm_start

    total_mtm_start = realized_at_7d_start + rewards_at_7d_start + unreal_mtm_at_7d_start
    total_mtm_end = realized_at_end + rewards_at_end + unreal_mtm_at_end
    snapshot_delta_mtm = total_mtm_end - total_mtm_start

    realized_delta_checkpoint = realized_at_end - realized_at_7d_start
    rewards_delta_checkpoint = rewards_at_end - rewards_at_7d_start
    unreal_change_no_mtm = unreal_no_mtm_at_end - unreal_no_mtm_at_7d_start
    unreal_change_mtm = unreal_mtm_at_end - unreal_mtm_at_7d_start

    print("\n" + "=" * 140)
    print("3) 7D INTERPRETATION TOTALS")
    print("=" * 140)
    rows = [
        ("Cashflow sum (all in/out)", cf_7d),
        ("Avg-cost realized sum", realized_7d),
        ("Rewards sum", rewards_7d),
        ("Avg-cost realized + rewards", realized_7d + rewards_7d),
        ("Raw amount sum (unsigned semantics)", raw_7d),
        ("Sell revenue only", sells_only_7d),
        ("Buy cost only", buys_only_7d),
        ("Redeem inflow only", redeems_only_7d),
        ("Reward inflow only", rewards_only_7d),
        ("Sell revenue - buy cost", sells_only_7d - buys_only_7d),
        ("Checkpoint realized delta", realized_delta_checkpoint),
        ("Checkpoint rewards delta", rewards_delta_checkpoint),
        ("Checkpoint unrealized change (no MTM)", unreal_change_no_mtm),
        ("Checkpoint unrealized change (MTM)", unreal_change_mtm),
        ("Checkpoint snapshot delta total PnL (no MTM)", snapshot_delta_no_mtm),
        ("Checkpoint snapshot delta total PnL (MTM)", snapshot_delta_mtm),
    ]
    for label, v in rows:
        print(f"{label:<54} {fmt_money(v):>16}   gap_to_$7.56={fmt_money(v - TARGET):>12}")

    print("\n" + "=" * 140)
    print("4) PER-EVENT COST BASIS CONTEXT (7D events)")
    print("=" * 140)
    for r in rows_7d:
        per_event = (r.realized_avg_cost + r.reward_component)
        print(
            f"[{r.idx:04d}] {r.source}:{r.etype:<10} market={r.market_tag:<28} "
            f"event_pnl(realized+reward)={fmt_money(per_event):>12} "
            f"cashflow={fmt_money(r.cashflow):>12}"
        )

    if rows_7d:
        ratio = TARGET / Decimal(len(rows_7d))
        print(f"\n$7.56 / number_of_7d_events ({len(rows_7d)}) = {fmt_money(ratio)} per event")

    print("\n" + "=" * 140)
    print("5) SUBSET SEARCHES CLOSE TO $7.56 (within $0.02)")
    print("=" * 140)

    searches = [
        ("cashflow", "cashflow"),
        ("realized_avg_cost", "realized_avg_cost"),
        ("reward_component", "reward_component"),
    ]

    # Derived vector: realized+reward per event
    derived_rows = []
    for r in rows_7d:
        rr = EventRow(**{**r.__dict__})
        rr.raw_amount = r.realized_avg_cost + r.reward_component
        derived_rows.append(rr)

    for name, attr in searches:
        hits = search_subsets(rows_7d, attr, TARGET)
        print(f"\nSubset metric: {name} | hits={len(hits)}")
        for s, idxs in hits[:15]:
            event_ids = [rows_7d[i].idx for i in idxs]
            print(f"  sum={fmt_money(s)}  idxs={event_ids}")
        if not hits:
            print("  (no subsets near target)")

    hits_rr = search_subsets(derived_rows, "raw_amount", TARGET)
    print(f"\nSubset metric: realized_plus_reward_per_event | hits={len(hits_rr)}")
    for s, idxs in hits_rr[:15]:
        event_ids = [rows_7d[i].idx for i in idxs]
        print(f"  sum={fmt_money(s)}  idxs={event_ids}")
    if not hits_rr:
        print("  (no subsets near target)")

    print("\nDone.")


if __name__ == "__main__":
    main()
