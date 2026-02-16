"""
V5: Fetch PM activity API and compare to our DB to find data discrepancies.
Then use PM's own activity data to compute monthly PnL.
"""
import sqlite3, json, urllib.request, time
from collections import defaultdict
from datetime import datetime

WALLET_ID = 7
ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
PERIOD_START = datetime(2026, 1, 16)
PERIOD_END = datetime(2026, 2, 16)

# ── Fetch all PM activity ──
def fetch_all_activity():
    all_acts = []
    offset = 0
    limit = 100
    while True:
        url = f"https://data-api.polymarket.com/activity?user={ADDR}&limit={limit}&offset={offset}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            if not data:
                break
            all_acts.extend(data)
            offset += limit
            if len(data) < limit:
                break
            time.sleep(0.2)
        except Exception as e:
            print(f"Error at offset {offset}: {e}")
            break
    return all_acts

print("Fetching PM activity API...")
pm_acts = fetch_all_activity()
print(f"Fetched {len(pm_acts)} activities from PM API")

if pm_acts:
    # Show a sample
    print(f"\nSample activity:")
    print(json.dumps(pm_acts[0], indent=2)[:500])
    
    # Date range
    dates = [a.get("timestamp") or a.get("createdAt") or "" for a in pm_acts]
    dates = [d for d in dates if d]
    if dates:
        print(f"\nDate range: {min(dates)} to {max(dates)}")
    
    # Group by type
    type_counts = defaultdict(lambda: {"count": 0, "usdc": 0})
    for a in pm_acts:
        atype = a.get("type", "UNKNOWN")
        # Figure out USDC amount
        usdc = 0
        if atype == "TRADE":
            usdc = float(a.get("usdcSize", 0))
        elif atype in ("REDEEM", "MERGE", "SPLIT", "CONVERSION"):
            usdc = float(a.get("usdcSize", 0))
        type_counts[atype]["count"] += 1
        type_counts[atype]["usdc"] += usdc
    
    print(f"\nPM Activity summary:")
    for t, d in sorted(type_counts.items()):
        print(f"  {t:15s}: count={d['count']:5d}  usdc=${d['usdc']:12.2f}")
    
    # Compute PM cashflow
    buy_usdc = 0
    sell_usdc = 0
    redeem_usdc = 0
    merge_usdc = 0
    split_usdc = 0
    conv_usdc = 0
    
    for a in pm_acts:
        atype = a.get("type", "")
        usdc = float(a.get("usdcSize", 0))
        if atype == "TRADE":
            side = a.get("side", "")
            if side == "BUY":
                buy_usdc += usdc
            elif side == "SELL":
                sell_usdc += usdc
        elif atype == "REDEEM":
            redeem_usdc += usdc
        elif atype == "MERGE":
            merge_usdc += usdc
        elif atype == "SPLIT":
            split_usdc += usdc
        elif atype == "CONVERSION":
            conv_usdc += usdc
    
    print(f"\nPM API Cashflow:")
    print(f"  Buy: ${buy_usdc:,.2f}")
    print(f"  Sell: ${sell_usdc:,.2f}")
    print(f"  Redeem: ${redeem_usdc:,.2f}")
    print(f"  Merge: ${merge_usdc:,.2f}")
    print(f"  Split: ${split_usdc:,.2f}")
    print(f"  Conversion: ${conv_usdc:,.2f}")
    cf = sell_usdc + redeem_usdc + merge_usdc - buy_usdc - split_usdc
    print(f"  Cashflow (excl conv): ${cf:,.2f}")
    cf2 = sell_usdc + redeem_usdc + merge_usdc - buy_usdc
    print(f"  Cashflow (no split, no conv): ${cf2:,.2f}")
    print(f"  Target monthly: $710.14")

# ── Compare with our DB ──
conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row

print(f"\n=== Our DB for same period ===")
# Count trades in period
db_trades = conn.execute("""
    SELECT side, COUNT(*), SUM(total_value), SUM(size) 
    FROM wallet_analysis_trade WHERE wallet_id=? 
    AND datetime >= '2026-01-16' AND datetime < '2026-02-16'
    GROUP BY side
""", (WALLET_ID,)).fetchall()
for t in db_trades:
    print(f"  {t[0]}: {t[1]} trades, ${float(t[2]):,.2f}, {float(t[3]):,.2f} size")

db_acts = conn.execute("""
    SELECT activity_type, COUNT(*), SUM(usdc_size), SUM(size)
    FROM wallet_analysis_activity WHERE wallet_id=?
    AND datetime >= '2026-01-16' AND datetime < '2026-02-16'
    GROUP BY activity_type
""", (WALLET_ID,)).fetchall()
for a in db_acts:
    print(f"  {a[0]}: {a[1]} acts, usdc=${float(a[2] or 0):,.2f}, size={float(a[3] or 0):,.2f}")

# ── Check: does PM API have different trade data? ──
# PM API trades include asset token_id, side, price, size
if pm_acts:
    pm_trades = [a for a in pm_acts if a.get("type") == "TRADE"]
    pm_buys = [a for a in pm_trades if a.get("side") == "BUY"]
    pm_sells = [a for a in pm_trades if a.get("side") == "SELL"]
    print(f"\nPM API trades: {len(pm_trades)} ({len(pm_buys)} buys, {len(pm_sells)} sells)")
    
    # Compare totals
    pm_buy_total = sum(float(a.get("usdcSize", 0)) for a in pm_buys)
    pm_sell_total = sum(float(a.get("usdcSize", 0)) for a in pm_sells)
    print(f"PM buy total: ${pm_buy_total:,.2f}")
    print(f"PM sell total: ${pm_sell_total:,.2f}")

conn.close()
