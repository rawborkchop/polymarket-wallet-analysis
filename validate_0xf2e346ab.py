"""Validate avg-cost realized PnL against Polymarket user @0xf2e346ab."""
import requests
from datetime import datetime, timezone, timedelta
from decimal import Decimal, getcontext
from collections import defaultdict

getcontext().prec = 28

DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
USER = "0xf2e346ab"


def D(x):
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")


def parse_ts(a):
    ts = a.get("timestamp")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    for k in ("createdAt", "updatedAt", "time", "date"):
        v = a.get(k)
        if isinstance(v, str) and v:
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.fromtimestamp(0, tz=timezone.utc)


def find_wallet():
    print("STEP 1 — Find wallet")
    # Required checks
    for period in ["all", "month", "week"]:
        r = requests.get(f"{DATA_API}/v1/leaderboard", params={"timePeriod": period, "limit": 5, "orderBy": "PNL", "user": USER}, timeout=30)
        print(f"{period}: {r.status_code} {r.text[:200]}")
    r = requests.get(f"https://polymarket.com/api/profile/{USER}", timeout=30)
    print(f"profile: {r.status_code} {r.text[:200]}")

    # Reliable mapping via Gamma profile search
    s = requests.get(f"{GAMMA_API}/public-search", params={"q": USER, "search_profiles": "true", "limit_per_type": 20}, timeout=30)
    s.raise_for_status()
    data = s.json() if s.content else {}
    profiles = data.get("profiles", []) if isinstance(data, dict) else []
    for p in profiles:
        if str(p.get("name", "")).lower() == USER.lower() and str(p.get("proxyWallet", "")).startswith("0x"):
            return p["proxyWallet"].lower()
    for p in profiles:
        w = str(p.get("proxyWallet", ""))
        if w.startswith("0x") and len(w) == 42:
            return w.lower()
    raise RuntimeError("Could not resolve wallet")


def official_pnl(wallet):
    print("\nSTEP 2 — Official PnL from leaderboard API")
    out = {}
    for period in ["all", "month", "week"]:
        r = requests.get(f"{DATA_API}/v1/leaderboard", params={"timePeriod": period, "orderBy": "PNL", "limit": 500, "user": wallet}, timeout=30)
        r.raise_for_status()
        data = r.json()
        pnl = None
        rows = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
        if not isinstance(rows, list):
            rows = []
        # prefer exact wallet row
        row = None
        for x in rows:
            if str(x.get("proxyWallet", "")).lower() == wallet.lower():
                row = x
                break
        if row is None and rows:
            row = rows[0]
        if isinstance(row, dict):
            pnl = row.get("pnl")
        out[period] = float(pnl) if pnl is not None else None
        print(f"official {period}: {out[period]}")
    return out


def fetch_activities(wallet):
    print("\nSTEP 3 — Fetch all activities (paginated)")
    all_rows = []
    offset = 0
    limit = 500
    while True:
        r = requests.get(f"{DATA_API}/activity", params={"user": wallet, "limit": limit, "offset": offset}, timeout=60)
        if r.status_code == 400:
            print(f"offset={offset} -> 400 (end)")
            break
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
        if not isinstance(rows, list) or not rows:
            break
        all_rows.extend(rows)
        print(f"offset={offset} got={len(rows)} total={len(all_rows)}")
        if len(rows) < limit:
            break
        offset += limit
    return all_rows


def simulate(activities, since=None):
    # position key = asset token id
    pos = defaultdict(lambda: {"size": Decimal("0"), "avg": Decimal("0")})
    realized = Decimal("0")

    acts = sorted(activities, key=parse_ts)
    for a in acts:
        if since and parse_ts(a) < since:
            continue
        t = str(a.get("type", "")).upper()
        side = str(a.get("side", "")).upper()
        asset = str(a.get("asset") or a.get("assetId") or "")
        size = D(a.get("size") or a.get("shares") or a.get("amount") or 0)
        price = D(a.get("price") or 0)
        usdc = D(a.get("usdcSize") or a.get("usdc") or a.get("value") or 0)

        if not asset:
            continue
        p = pos[asset]

        is_buy = (t == "TRADE" and side == "BUY") or t == "BUY"
        is_sell = (t == "TRADE" and side == "SELL") or t == "SELL"

        if is_buy:
            if size <= 0:
                continue
            new_size = p["size"] + size
            p["avg"] = (p["avg"] * p["size"] + price * size) / new_size if new_size > 0 else p["avg"]
            p["size"] = new_size

        elif is_sell:
            if size <= 0:
                continue
            sell_size = min(size, p["size"]) if p["size"] > 0 else size
            realized += sell_size * (price - p["avg"])
            p["size"] = max(Decimal("0"), p["size"] - sell_size)

        elif t == "REDEEM":
            # winner: usdc>0; loser redeem skip (size=0/usdc=0)
            if usdc <= 0:
                continue
            if size > 0:
                redeem_size = min(size, p["size"]) if p["size"] > 0 else size
                realized += usdc - (redeem_size * p["avg"])
                p["size"] = max(Decimal("0"), p["size"] - redeem_size)
            else:
                realized += usdc

        elif t in ("SPLIT", "CONVERSION"):
            continue

    return float(realized)


def fmt(x):
    return "N/A" if x is None else f"{x:,.2f}"


def main():
    wallet = find_wallet()
    print(f"\nResolved wallet: {wallet}")

    pm = official_pnl(wallet)
    activities = fetch_activities(wallet)
    print(f"Total activities fetched: {len(activities)}")

    print("\nSTEP 4/5/6 — Avg cost simulation and comparison")
    now = datetime.now(timezone.utc)

    rows = []
    rows.append(("all", pm.get("all"), simulate(activities, None)))
    for d in [30, 31, 32]:
        rows.append((f"month({d}d)", pm.get("month"), simulate(activities, now - timedelta(days=d))))
    for d in [7, 8, 9]:
        rows.append((f"week({d}d)", pm.get("week"), simulate(activities, now - timedelta(days=d))))

    print("Period | PM Official | Our Sim | Gap | %Match")
    print("-" * 72)
    for period, off, sim in rows:
        gap = None if off is None else (sim - off)
        if off is None:
            match = None
        else:
            denom = abs(off) if abs(off) > 1e-9 else 1.0
            match = max(0.0, (1 - abs(sim - off) / denom) * 100)
        print(f"{period:10s} | {fmt(off):>11s} | {fmt(sim):>11s} | {fmt(gap):>11s} | {(f'{match:.2f}%' if match is not None else 'N/A'):>8s}")


if __name__ == "__main__":
    main()
