import os
import json
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Iterable, Set

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

from wallet_analysis.models import Wallet, Trade, Activity  # noqa: E402


WALLET_ID = 7
WALLET_ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
TARGET_PROFILE_WEEK = Decimal("7.56")
TARGET_LEADERBOARD_WEEK = Decimal("0.04")

ASOF_END_DT = datetime(2026, 2, 16, 23, 59, 59, tzinfo=timezone.utc)
ASOF_END_TS = int(ASOF_END_DT.timestamp())
FEB9_START_TS = int(datetime(2026, 2, 9, 0, 0, 0, tzinfo=timezone.utc).timestamp())

EPS = Decimal("0.0000001")
ONE = Decimal("1")
ZERO = Decimal("0")


def D(x) -> Decimal:
    return Decimal(str(x))


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


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
        if self.shares <= EPS:
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
class EventDelta:
    ts: int
    realized: Decimal = ZERO
    rewards: Decimal = ZERO


@dataclass
class ReplayState:
    positions: Dict[Tuple[int, str], Pos] = field(default_factory=lambda: defaultdict(Pos))
    market_outcomes: Dict[int, Set[str]] = field(default_factory=lambda: defaultdict(set))
    market_resolution: Dict[int, Tuple[int, str]] = field(default_factory=dict)
    last_trade_price: Dict[Tuple[int, str], Decimal] = field(default_factory=dict)
    realized_total: Decimal = ZERO
    rewards_total: Decimal = ZERO


def sort_key(event_type: str, obj):
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
    events.sort(key=lambda x: sort_key(x[0], x[1]))
    return trades, activities, events


def preload_market_data(state: ReplayState, trades: Iterable[Trade], activities: Iterable[Activity]):
    for t in trades:
        if t.market_id:
            state.market_outcomes[t.market_id].add(t.outcome)
            if t.market and t.market.resolved and t.market.resolution_timestamp:
                state.market_resolution[t.market_id] = (int(t.market.resolution_timestamp), t.market.winning_outcome)

    for a in activities:
        if a.market_id and a.market and a.market.resolved and a.market.resolution_timestamp:
            state.market_resolution[a.market_id] = (int(a.market.resolution_timestamp), a.market.winning_outcome)


def apply_event(state: ReplayState, event_type: str, obj) -> EventDelta:
    ts = int(obj.timestamp)
    d = EventDelta(ts=ts)

    if event_type == "trade":
        t = obj
        if not t.market_id:
            return d

        key = (t.market_id, t.outcome)
        state.market_outcomes[t.market_id].add(t.outcome)

        price = D(t.price)
        size = D(t.size)
        state.last_trade_price[key] = price

        pos = state.positions[key]
        if t.side == "BUY":
            d.realized += pos.buy(size, price)
        else:
            d.realized += pos.sell(size, price)

        state.realized_total += d.realized
        return d

    a = obj
    if a.activity_type == "REWARD":
        d.rewards += D(a.usdc_size)
        state.rewards_total += d.rewards
        return d

    if not a.market_id:
        return d

    size = D(a.size)
    usdc = D(a.usdc_size)

    # Keep replay aligned with prior experiments
    if a.activity_type in ("SPLIT", "CONVERSION"):
        return d

    if a.activity_type == "MERGE":
        outcomes = state.market_outcomes.get(a.market_id, {"Yes", "No"})
        n = len(outcomes)
        if size > 0 and n > 0:
            rev_per_share = usdc / (size * n)
            for outcome in outcomes:
                key = (a.market_id, outcome)
                pos = state.positions[key]
                if pos.shares > EPS:
                    d.realized += pos.sell(min(size, pos.shares), rev_per_share)

    elif a.activity_type == "REDEEM":
        if usdc > 0:
            market_pos = [(k, v) for k, v in state.positions.items() if k[0] == a.market_id and v.shares > EPS]
            matched = False
            for key, pos in market_pos:
                if abs(pos.shares - size) < Decimal("0.5"):
                    d.realized += pos.sell(size, ONE)
                    matched = True
                    break
            if not matched:
                remaining = size
                for key, pos in sorted(market_pos, key=lambda x: x[1].shares, reverse=True):
                    if remaining <= EPS:
                        break
                    qty = min(remaining, pos.shares)
                    d.realized += pos.sell(qty, ONE)
                    remaining -= qty
        else:
            for key, pos in list(state.positions.items()):
                if key[0] == a.market_id and pos.shares > EPS:
                    d.realized += pos.zero_out()

    state.realized_total += d.realized
    return d


def replay_to(ts_cutoff: int, trades, activities, events) -> ReplayState:
    state = ReplayState()
    preload_market_data(state, trades, activities)
    for etype, obj in events:
        if int(obj.timestamp) > ts_cutoff:
            break
        apply_event(state, etype, obj)
    return state


def replay_all_deltas(trades, activities, events) -> List[EventDelta]:
    state = ReplayState()
    preload_market_data(state, trades, activities)
    out = []
    for etype, obj in events:
        out.append(apply_event(state, etype, obj))
    return out


def cumulative_realized_rewards_at(deltas: List[EventDelta], ts: int) -> Decimal:
    total = ZERO
    for d in deltas:
        if d.ts <= ts:
            total += d.realized + d.rewards
        else:
            break
    return total


def calc_unrealized(state: ReplayState, asof_ts: int, mtm=True) -> Decimal:
    unreal = ZERO
    for (market_id, outcome), pos in state.positions.items():
        if pos.shares <= EPS:
            continue

        mark = None
        if mtm:
            resolved = state.market_resolution.get(market_id)
            if resolved and asof_ts >= resolved[0]:
                mark = ONE if outcome == resolved[1] else ZERO
            else:
                mark = state.last_trade_price.get((market_id, outcome))

        if mark is None:
            mark = pos.avg_cost

        unreal += pos.shares * (mark - pos.avg_cost)

    return unreal


def calc_position_value(state: ReplayState, asof_ts: int) -> Decimal:
    val = ZERO
    for (market_id, outcome), pos in state.positions.items():
        if pos.shares <= EPS:
            continue
        resolved = state.market_resolution.get(market_id)
        if resolved and asof_ts >= resolved[0]:
            mark = ONE if outcome == resolved[1] else ZERO
        else:
            mark = state.last_trade_price.get((market_id, outcome), pos.avg_cost)
        val += pos.shares * mark
    return val


def fetch_json(url: str, timeout=30):
    r = requests.get(url, timeout=timeout)
    status = r.status_code
    text = r.text
    try:
        data = r.json()
    except Exception:
        data = None
    return status, data, text


def pick_numeric(d: dict) -> Optional[Decimal]:
    for k in ("pnl", "value", "y", "p", "totalPnl", "profit", "amount"):
        if k in d and d[k] is not None:
            try:
                return D(d[k])
            except Exception:
                pass
    return None


def parse_timeseries_delta(payload) -> Optional[Decimal]:
    if isinstance(payload, dict):
        # Sometimes wrapped
        for k in ("data", "points", "history", "results"):
            if k in payload and isinstance(payload[k], list):
                payload = payload[k]
                break
    if not isinstance(payload, list) or len(payload) < 2:
        return None
    first = pick_numeric(payload[0]) if isinstance(payload[0], dict) else None
    last = pick_numeric(payload[-1]) if isinstance(payload[-1], dict) else None
    if first is None or last is None:
        return None
    return last - first


def fetch_rewards_from_api(since_ts: int, until_ts: int) -> Tuple[int, Decimal, int]:
    session = requests.Session()
    offset = 0
    limit = 500
    total_rewards = ZERO
    reward_count = 0
    total_rows = 0

    while True:
        params = {
            "user": WALLET_ADDRESS,
            "limit": limit,
            "offset": offset,
        }
        resp = session.get("https://data-api.polymarket.com/activity", params=params, timeout=30)
        if resp.status_code != 200:
            break
        rows = resp.json()
        if not isinstance(rows, list) or not rows:
            break

        total_rows += len(rows)
        for r in rows:
            ts = int(r.get("timestamp", 0) or 0)
            if ts < since_ts:
                continue
            if ts > until_ts:
                continue
            typ = str(r.get("type") or r.get("activityType") or "").upper()
            if typ == "REWARD":
                reward_count += 1
                total_rewards += D(r.get("usdcSize", r.get("amount", 0)))

        oldest = min(int(x.get("timestamp", 0) or 0) for x in rows)
        if oldest < since_ts or len(rows) < limit:
            break
        offset += limit

    return total_rows, total_rewards, reward_count


def nearest_combos(target: Decimal, pieces: List[Tuple[str, Decimal]], max_terms=4, topn=12):
    from itertools import combinations

    out = []
    n = len(pieces)
    for r in range(1, min(max_terms, n) + 1):
        for idxs in combinations(range(n), r):
            s = sum(pieces[i][1] for i in idxs)
            labels = [pieces[i][0] for i in idxs]
            out.append((abs(s - target), s, labels))
    out.sort(key=lambda x: (x[0], abs(x[1])))
    return out[:topn]


def main():
    print("=" * 120)
    print("WEEKLY PNL DEEP DIVE")
    print(f"Wallet: {WALLET_ADDRESS} (id={WALLET_ID})")
    print(f"As-of end: {fmt_ts(ASOF_END_TS)}")
    print("=" * 120)

    trades, activities, events = collect_events()
    deltas = replay_all_deltas(trades, activities, events)
    deltas.sort(key=lambda x: x.ts)

    print("\n[1] Polymarket API references")
    lb_url = f"https://data-api.polymarket.com/v1/leaderboard?timePeriod=week&orderBy=PNL&limit=1&offset=0&category=overall&user={WALLET_ADDRESS}"
    ts_urls = [
        f"https://data-api.polymarket.com/v1/pnl/{WALLET_ADDRESS}?window=week",
        f"https://data-api.polymarket.com/pnl/{WALLET_ADDRESS}?window=week",
        f"https://data-api.polymarket.com/pnl?address={WALLET_ADDRESS}&window=week",
    ]

    lb_val = None
    status, data, text = fetch_json(lb_url)
    print(f"- leaderboard URL: {lb_url}")
    print(f"  HTTP {status}")
    if isinstance(data, list) and data:
        lb_val = D(data[0].get("pnl", 0))
        print(f"  parsed weekly pnl = ${lb_val}")
        print(f"  row[0] = {json.dumps(data[0], ensure_ascii=False)}")
    else:
        print(f"  body(sample) = {text[:250]!r}")

    ts_delta = None
    ts_url_used = None
    for u in ts_urls:
        status, data, text = fetch_json(u)
        print(f"- timeseries URL: {u}")
        print(f"  HTTP {status}")
        if data is not None:
            d = parse_timeseries_delta(data)
            if d is not None:
                ts_delta = d
                ts_url_used = u
                arr = data
                if isinstance(arr, dict):
                    for k in ("data", "points", "history", "results"):
                        if isinstance(arr.get(k), list):
                            arr = arr[k]
                            break
                if isinstance(arr, list) and arr:
                    print(f"  points = {len(arr)}")
                    print(f"  first = {arr[0]}")
                    print(f"  last  = {arr[-1]}")
                break
            else:
                short = text[:250].replace("\n", " ")
                print(f"  no parseable delta; body(sample)={short!r}")
        else:
            short = text[:250].replace("\n", " ")
            print(f"  non-JSON body(sample)={short!r}")

    print("\n[2] Known Feb 9-16 event window from DB")
    t_window = [t for t in trades if FEB9_START_TS <= int(t.timestamp) <= ASOF_END_TS]
    a_window = [a for a in activities if FEB9_START_TS <= int(a.timestamp) <= ASOF_END_TS]

    sell_inflow = sum(D(t.total_value) for t in t_window if t.side == "SELL")
    buy_outflow = sum(D(t.total_value) for t in t_window if t.side == "BUY")
    redeem_usdc = sum(D(a.usdc_size) for a in a_window if a.activity_type == "REDEEM")
    reward_usdc = sum(D(a.usdc_size) for a in a_window if a.activity_type == "REWARD")

    start_cum = cumulative_realized_rewards_at(deltas, FEB9_START_TS - 1)
    end_cum = cumulative_realized_rewards_at(deltas, ASOF_END_TS)
    realized_rewards_window = end_cum - start_cum

    print(f"- trades in window: {len(t_window)} (BUY={sum(1 for t in t_window if t.side=='BUY')}, SELL={sum(1 for t in t_window if t.side=='SELL')})")
    print(f"- activities in window: {len(a_window)}")
    print(f"- sell inflow: ${sell_inflow:.4f}")
    print(f"- buy outflow: ${buy_outflow:.4f}")
    print(f"- redeem usdc flow: ${redeem_usdc:.4f}")
    print(f"- reward usdc flow: ${reward_usdc:.4f}")
    print(f"- replay realized+rewards over Feb9-16: ${realized_rewards_window:.6f}")

    print("\n[3] Hour-by-hour cutoff sweep (7-day windows)")
    sweep_start = datetime(2026, 2, 8, 0, 0, 0, tzinfo=timezone.utc)
    sweep_end = datetime(2026, 2, 10, 0, 0, 0, tzinfo=timezone.utc)

    best = []
    cur = sweep_start
    while cur <= sweep_end:
        st = int(cur.timestamp())
        en = st + 7 * 24 * 3600 - 1
        st_cum = cumulative_realized_rewards_at(deltas, st - 1)
        en_cum = cumulative_realized_rewards_at(deltas, en)
        v = en_cum - st_cum
        diff = abs(v - TARGET_PROFILE_WEEK)
        best.append((diff, st, en, v))
        cur += timedelta(hours=1)

    best.sort(key=lambda x: x[0])
    print("Top 10 closest windows to $7.56 by realized+rewards:")
    for diff, st, en, v in best[:10]:
        print(f"  {fmt_ts(st)} -> {fmt_ts(en)} | pnl=${v:.6f} | diff=${(v-TARGET_PROFILE_WEEK):+.6f}")

    print("\n[4] Unrealized-only change / net position value changes")
    week_start_ts = ASOF_END_TS - 7 * 24 * 3600 + 1
    state_start = replay_to(week_start_ts - 1, trades, activities, events)
    state_end = replay_to(ASOF_END_TS, trades, activities, events)

    u_start_mtm = calc_unrealized(state_start, week_start_ts - 1, mtm=True)
    u_end_mtm = calc_unrealized(state_end, ASOF_END_TS, mtm=True)
    du_mtm = u_end_mtm - u_start_mtm

    u_start_no = calc_unrealized(state_start, week_start_ts - 1, mtm=False)
    u_end_no = calc_unrealized(state_end, ASOF_END_TS, mtm=False)
    du_no = u_end_no - u_start_no

    v_start = calc_position_value(state_start, week_start_ts - 1)
    v_end = calc_position_value(state_end, ASOF_END_TS)
    dv = v_end - v_start

    realized_week = cumulative_realized_rewards_at(deltas, ASOF_END_TS) - cumulative_realized_rewards_at(deltas, week_start_ts - 1)

    print(f"- rolling week start used: {fmt_ts(week_start_ts)}")
    print(f"- dUnrealized (MTM) = ${du_mtm:.6f}")
    print(f"- dUnrealized (no MTM) = ${du_no:.6f}")
    print(f"- net position value change (all replayed positions) = ${dv:.6f}")
    print(f"- realized+rewards rolling week = ${realized_week:.6f}")
    print(f"- leaderboard + dUnrealized(MTM) = ${(TARGET_LEADERBOARD_WEEK + du_mtm):.6f}")

    print("\n[5] Rewards from activity API directly")
    total_rows, api_rewards, api_reward_count = fetch_rewards_from_api(week_start_ts, ASOF_END_TS)
    print(f"- scanned activity rows: {total_rows}")
    print(f"- reward count in rolling week: {api_reward_count}")
    print(f"- reward sum in rolling week: ${api_rewards:.6f}")

    print("\n[6] Work backwards from $7.56 (combos of candidate components)")
    candidates = [
        ("leaderboard_week", TARGET_LEADERBOARD_WEEK),
        ("timeseries_delta", ts_delta if ts_delta is not None else ZERO),
        ("realized_week", realized_week),
        ("realized_feb9_16", realized_rewards_window),
        ("dUnrealized_MTM", du_mtm),
        ("dUnrealized_noMTM", du_no),
        ("dPositionValue", dv),
        ("sell_inflow", sell_inflow),
        ("buy_outflow", -buy_outflow),
        ("redeem_usdc", redeem_usdc),
        ("api_rewards", api_rewards),
    ]
    top = nearest_combos(TARGET_PROFILE_WEEK, candidates, max_terms=4, topn=12)
    for _, s, labels in top:
        print(f"  sum=${s:.6f} diff=${(s-TARGET_PROFILE_WEEK):+.6f} <- {' + '.join(labels)}")

    print("\n[7] Summary")
    print(f"- Profile weekly target: ${TARGET_PROFILE_WEEK}")
    print(f"- Leaderboard weekly target: ${TARGET_LEADERBOARD_WEEK}")
    print(f"- API leaderboard weekly parsed: {('$'+str(lb_val)) if lb_val is not None else 'N/A'}")
    print(f"- API timeseries delta parsed: {('$'+str(ts_delta)) if ts_delta is not None else 'N/A'}")
    if ts_url_used:
        print(f"- timeseries source used: {ts_url_used}")


if __name__ == "__main__":
    main()
