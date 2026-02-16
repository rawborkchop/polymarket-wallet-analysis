"""
Validate avg-cost basis PnL simulation for a different Polymarket user (@absolutefocus).

Requirements from task:
- No Django / DB usage
- Fetch directly from APIs
- Trades-only simulation (no split-created positions)
- Winner-first redeem ordering
- Compare ALL / MONTH (~31d) / WEEK (7,8,9d)
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Any, Dict, List, Optional, Tuple

import requests

getcontext().prec = 28
D = lambda x: Decimal(str(x))
ZERO = Decimal("0")
ONE = Decimal("1")
EPS = Decimal("0.0000001")

USERNAME = "absolutefocus"


@dataclass
class Pos:
    shares: Decimal = ZERO
    avg_cost: Decimal = ZERO
    realized_pnl: Decimal = ZERO

    def buy(self, size: Decimal, price: Decimal) -> None:
        old_cost = self.shares * self.avg_cost
        self.shares += size
        if self.shares > EPS:
            self.avg_cost = (old_cost + size * price) / self.shares

    def sell(self, size: Decimal, price: Decimal) -> None:
        if self.shares <= EPS:
            return
        qty = min(size, self.shares)
        pnl = qty * (price - self.avg_cost)
        self.realized_pnl += pnl
        self.shares -= qty
        if self.shares < EPS:
            self.shares = ZERO
            self.avg_cost = ZERO

    def zero_out(self) -> None:
        if self.shares > EPS:
            self.realized_pnl -= self.shares * self.avg_cost
            self.shares = ZERO
            self.avg_cost = ZERO


def get_json(url: str, params: Optional[dict] = None, timeout: int = 30) -> Any:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def find_wallet(username: str) -> str:
    probes = []

    url1 = "https://data-api.polymarket.com/v1/leaderboard"
    p1 = {"timePeriod": "all", "userName": username}
    try:
        data = get_json(url1, p1)
        probes.append((url1, p1, data))
        if isinstance(data, list) and data and data[0].get("proxyWallet"):
            return data[0]["proxyWallet"]
    except Exception as e:
        probes.append((url1, p1, {"error": str(e)}))

    url2 = "https://gamma-api.polymarket.com/users"
    p2 = {"username": username}
    try:
        data = get_json(url2, p2)
        probes.append((url2, p2, data))
        if isinstance(data, list) and data:
            for u in data:
                if isinstance(u, dict) and u.get("proxyWallet"):
                    return u["proxyWallet"]
    except Exception as e:
        probes.append((url2, p2, {"error": str(e)}))

    raise RuntimeError(f"Could not find wallet for user={username}. Probe results: {probes}")


def fetch_official(wallet: str, period: str, username: Optional[str] = None) -> Dict[str, Any]:
    url = "https://data-api.polymarket.com/v1/leaderboard"

    # Primary: by wallet
    data = get_json(url, {"timePeriod": period, "user": wallet})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict) and data:
        return data

    # Fallback: by username (some periods may return [] for wallet lookup)
    if username:
        data2 = get_json(url, {"timePeriod": period, "userName": username})
        if isinstance(data2, list) and data2:
            return data2[0]
        if isinstance(data2, dict) and data2:
            return data2
        return {"raw": data2}

    return {"raw": data}


def fetch_clob_trades(wallet: str, side_param: str) -> Tuple[List[dict], Optional[str]]:
    """Try CLOB /trades pagination with maker_address or taker_address.
    Returns (trades, error_string_or_none)
    """
    trades: List[dict] = []
    cursor = None
    err = None
    while True:
        params = {side_param: wallet, "limit": 500}
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get("https://clob.polymarket.com/trades", params=params, timeout=30)
            if r.status_code != 200:
                err = f"HTTP {r.status_code}: {r.text[:300]}"
                break
            data = r.json()
            batch = data.get("data") or []
            if not batch:
                break
            trades.extend(batch)
            cursor = data.get("next_cursor")
            if not cursor or cursor == "LTE=":
                break
        except Exception as e:
            err = str(e)
            break
    return trades, err


def fetch_activities(wallet: str) -> List[dict]:
    acts: List[dict] = []
    offset = 0
    while True:
        url = "https://data-api.polymarket.com/activity"
        try:
            data = get_json(url, {"user": wallet, "limit": 500, "offset": offset})
        except requests.HTTPError as e:
            # Observed behavior: API may return 400 once offset passes available range.
            if e.response is not None and e.response.status_code == 400:
                break
            raise
        if not data:
            break
        acts.extend(data)
        offset += len(data)
        if len(data) < 500:
            break
    return acts


def epoch_now() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def safe_ts(x: Any) -> int:
    try:
        return int(float(x))
    except Exception:
        return 0


def build_trade_records_from_activities(activities: List[dict]) -> List[dict]:
    # Use activity feed TRADE rows as trade source for simulation.
    trades = [a for a in activities if a.get("type") == "TRADE"]
    trades.sort(key=lambda t: (safe_ts(t.get("timestamp")), str(t.get("transactionHash", ""))))
    return trades


def simulate_avg_cost_trades_only(
    trades: List[dict],
    activities: List[dict],
    start_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Simulate avg-cost realized PnL:
      - trades build/close positions
      - no SPLIT/CONVERSION/MERGE position creation
      - winner-first redeem ordering
      - rewards are added to realized pnl
    """

    positions: Dict[Tuple[str, str], Pos] = defaultdict(Pos)
    market_outcomes = defaultdict(set)

    for t in trades:
        cid = str(t.get("conditionId") or "")
        out = str(t.get("outcome") or f"outcome_{t.get('outcomeIndex', '')}")
        if cid:
            market_outcomes[cid].add(out)

    events: List[Tuple[Tuple[int, int, int], str, dict]] = []

    # trades priority 0
    for i, t in enumerate(trades):
        ts = safe_ts(t.get("timestamp"))
        if start_ts is not None and ts < start_ts:
            continue
        events.append(((ts, 0, i), "trade", t))

    # activities for redeem/reward only
    for i, a in enumerate(activities):
        at = str(a.get("type") or "")
        if at not in ("REDEEM", "REWARD"):
            continue
        ts = safe_ts(a.get("timestamp"))
        if start_ts is not None and ts < start_ts:
            continue
        usdc = D(a.get("usdcSize", 0))
        if at == "REDEEM":
            prio = 1 if usdc > 0 else 3  # winner first, loser last
        else:
            prio = 2
        events.append(((ts, prio, i), "activity", a))

    events.sort(key=lambda x: x[0])

    total_rewards = ZERO
    stats = Counter()

    for _, etype, obj in events:
        if etype == "trade":
            cid = str(obj.get("conditionId") or "")
            if not cid:
                continue
            out = str(obj.get("outcome") or f"outcome_{obj.get('outcomeIndex', '')}")
            key = (cid, out)
            side = str(obj.get("side") or "").upper()
            size = D(obj.get("size", 0))
            price = D(obj.get("price", 0))
            if price <= 0 and size > 0:
                price = D(obj.get("usdcSize", 0)) / size

            if side == "BUY":
                positions[key].buy(size, price)
            elif side == "SELL":
                positions[key].sell(size, price)

        else:
            at = str(obj.get("type") or "")
            if at == "REWARD":
                total_rewards += D(obj.get("usdcSize", 0))
                continue
            if at != "REDEEM":
                continue

            cid = str(obj.get("conditionId") or "")
            if not cid:
                continue
            size = D(obj.get("size", 0))
            usdc = D(obj.get("usdcSize", 0))

            is_winner = usdc > 0
            if is_winner:
                stats["winner_redeems"] += 1
                market_pos = [(k, v) for k, v in positions.items() if k[0] == cid and v.shares > EPS]
                if not market_pos:
                    stats["unmatched_winner_redeems"] += 1
                    continue

                matched = False
                for key, pos in market_pos:
                    if abs(pos.shares - size) < Decimal("0.5"):
                        pos.sell(size, ONE)
                        matched = True
                        break

                if not matched:
                    remaining = size
                    for key, pos in sorted(market_pos, key=lambda kv: kv[1].shares, reverse=True):
                        if remaining <= EPS:
                            break
                        amt = min(remaining, pos.shares)
                        if amt > EPS:
                            pos.sell(amt, ONE)
                            remaining -= amt
                    if remaining > Decimal("0.5"):
                        stats["partial_unmatched_winner_shares"] += float(remaining)
            else:
                stats["loser_redeems"] += 1
                for key, pos in positions.items():
                    if key[0] == cid:
                        pos.zero_out()

    realized = sum(p.realized_pnl for p in positions.values()) + total_rewards
    open_cost = sum(p.shares * p.avg_cost for p in positions.values() if p.shares > EPS)
    open_count = sum(1 for p in positions.values() if p.shares > EPS)

    return {
        "realized": realized,
        "rewards": total_rewards,
        "open_cost": open_cost,
        "open_count": open_count,
        "stats": dict(stats),
    }


def pct_match(sim: Decimal, official: Decimal) -> Decimal:
    if official == 0:
        return Decimal("100") if sim == 0 else Decimal("0")
    val = (ONE - (abs(sim - official) / abs(official))) * D(100)
    if val < 0:
        return Decimal("0")
    if val > 100:
        return Decimal("100")
    return val


def fmt_money(x: Decimal) -> str:
    return f"${x:,.2f}"


def main() -> None:
    print("=" * 90)
    print("Validate avg-cost simulation vs Polymarket official for @absolutefocus")
    print("=" * 90)

    wallet = find_wallet(USERNAME)
    print(f"\n1) Resolved wallet for @{USERNAME}: {wallet}")

    # Official PM numbers
    official_all = fetch_official(wallet, "all", USERNAME)
    official_month = fetch_official(wallet, "month", USERNAME)
    official_week = fetch_official(wallet, "week", USERNAME)

    print("\n2) PM Official leaderboard responses (pnl, vol):")
    print(f"   ALL   -> pnl={official_all.get('pnl')} ; vol={official_all.get('vol')} ; raw={official_all}")
    print(f"   MONTH -> pnl={official_month.get('pnl')} ; vol={official_month.get('vol')} ; raw={official_month}")
    print(f"   WEEK  -> pnl={official_week.get('pnl')} ; vol={official_week.get('vol')} ; raw={official_week}")

    # CLOB trades
    maker_trades, maker_err = fetch_clob_trades(wallet, "maker_address")
    taker_trades, taker_err = fetch_clob_trades(wallet, "taker_address")

    print("\n3) CLOB /trades fetch counts:")
    print(f"   maker_address count: {len(maker_trades)}")
    if maker_err:
        print(f"   maker_address error: {maker_err}")
    print(f"   taker_address count: {len(taker_trades)}")
    if taker_err:
        print(f"   taker_address error: {taker_err}")

    # Activities
    activities = fetch_activities(wallet)
    type_counts = Counter(a.get("type", "UNKNOWN") for a in activities)
    print("\n4) Activities summary:")
    print(f"   total activities: {len(activities)}")
    for k, v in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"   - {k}: {v}")
    if activities:
        min_ts = min(safe_ts(a.get("timestamp")) for a in activities)
        max_ts = max(safe_ts(a.get("timestamp")) for a in activities)
        min_dt = dt.datetime.fromtimestamp(min_ts, tz=dt.timezone.utc)
        max_dt = dt.datetime.fromtimestamp(max_ts, tz=dt.timezone.utc)
        print(f"   timestamp range (UTC): {min_dt.isoformat()} -> {max_dt.isoformat()}")
        if len(activities) >= 3500:
            print("   NOTE: activity endpoint appears capped/truncated around 3500 rows for this wallet.")

    # Trade source for simulation
    trades_for_sim = build_trade_records_from_activities(activities)
    print(f"\n   trades used for simulation (from activity type=TRADE): {len(trades_for_sim)}")

    # Simulations
    now_ts = epoch_now()
    month_31_start = now_ts - 31 * 24 * 3600
    week7_start = now_ts - 7 * 24 * 3600
    week8_start = now_ts - 8 * 24 * 3600
    week9_start = now_ts - 9 * 24 * 3600

    sim_all = simulate_avg_cost_trades_only(trades_for_sim, activities, start_ts=None)
    sim_m31 = simulate_avg_cost_trades_only(trades_for_sim, activities, start_ts=month_31_start)
    sim_w7 = simulate_avg_cost_trades_only(trades_for_sim, activities, start_ts=week7_start)
    sim_w8 = simulate_avg_cost_trades_only(trades_for_sim, activities, start_ts=week8_start)
    sim_w9 = simulate_avg_cost_trades_only(trades_for_sim, activities, start_ts=week9_start)

    off_all = D(official_all.get("pnl", 0))
    off_month = D(official_month.get("pnl", 0))
    off_week = D(official_week.get("pnl", 0))

    rows = [
        ("ALL", off_all, sim_all["realized"]),
        ("MONTH(31d)", off_month, sim_m31["realized"]),
        ("WEEK(7d)", off_week, sim_w7["realized"]),
        ("WEEK(8d)", off_week, sim_w8["realized"]),
        ("WEEK(9d)", off_week, sim_w9["realized"]),
    ]

    print("\n5-7) Comparison table")
    print("| Period | PM Official | Our Sim | Gap | % Match |")
    print("|---|---:|---:|---:|---:|")
    for period, official_pnl, sim_pnl in rows:
        gap = sim_pnl - official_pnl
        match = pct_match(sim_pnl, official_pnl)
        print(
            f"| {period} | {fmt_money(official_pnl)} | {fmt_money(sim_pnl)} | {fmt_money(gap)} | {match:.2f}% |"
        )

    print("\nSimulation diagnostics:")
    print(f"   ALL stats: {sim_all['stats']} ; open_count={sim_all['open_count']} ; open_cost={fmt_money(sim_all['open_cost'])}")
    print(f"   MONTH(31d) stats: {sim_m31['stats']} ; open_count={sim_m31['open_count']} ; open_cost={fmt_money(sim_m31['open_cost'])}")
    print(f"   WEEK(7d) stats: {sim_w7['stats']} ; open_count={sim_w7['open_count']} ; open_cost={fmt_money(sim_w7['open_cost'])}")
    print(f"   WEEK(8d) stats: {sim_w8['stats']} ; open_count={sim_w8['open_count']} ; open_cost={fmt_money(sim_w8['open_cost'])}")
    print(f"   WEEK(9d) stats: {sim_w9['stats']} ; open_count={sim_w9['open_count']} ; open_cost={fmt_money(sim_w9['open_cost'])}")


if __name__ == "__main__":
    main()
