"""Fetch ALL positions (open+resolved) and sum cashPnl to compare with official."""
import requests
import json

ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
OFFICIAL_PNL = 20172.77
s = requests.Session()
s.headers.update({"Accept": "application/json", "User-Agent": "Mozilla/5.0"})

all_positions = []
offset = 0
while True:
    resp = s.get(
        "https://data-api.polymarket.com/positions",
        params={"user": ADDRESS, "limit": 500, "offset": offset, "status": "all"},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Error at offset {offset}: {resp.status_code}")
        break
    data = resp.json()
    if not data:
        break
    all_positions.extend(data)
    print(f"  Fetched {len(data)} at offset {offset} (total: {len(all_positions)})")
    if len(data) < 500:
        break
    offset += 500

print(f"\nTotal positions: {len(all_positions)}")

# Sum key fields
total_cash_pnl = sum(float(p.get('cashPnl') or 0) for p in all_positions)
total_realized = sum(float(p.get('realizedPnl') or 0) for p in all_positions)
total_initial = sum(float(p.get('initialValue') or 0) for p in all_positions)
total_current = sum(float(p.get('currentValue') or 0) for p in all_positions)
total_bought = sum(float(p.get('totalBought') or 0) for p in all_positions)

print(f"\nSum cashPnl: {total_cash_pnl:.2f}")
print(f"Sum realizedPnl: {total_realized:.2f}")
print(f"Sum initialValue: {total_initial:.2f}")
print(f"Sum currentValue: {total_current:.2f}")
print(f"Sum totalBought: {total_bought:.2f}")
print(f"currentValue - initialValue: {total_current - total_initial:.2f}")
print(f"cashPnl + currentValue: {total_cash_pnl + total_current:.2f}")

# What does PM show as PnL? It might be cashPnl + currentValue or realized + unrealized
# cashPnl = realized cash in/out per position
# The profile shows "Profit" = sum of all position PnLs
# Position PnL = cashPnl + currentValue - initialValue... no, cashPnl already accounts for that
# Let's check: for a closed resolved position, cashPnl should = realizedPnl?

print(f"\n=== Checking if cashPnl relates to official PnL ===")
print(f"Official: {OFFICIAL_PNL}")
print(f"cashPnl: {total_cash_pnl:.2f}")
print(f"Gap: {OFFICIAL_PNL - total_cash_pnl:.2f}")

# Maybe PM PnL = sum(cashPnl) + sum(currentValue)?
combo = total_cash_pnl + total_current
print(f"cashPnl + currentValue: {combo:.2f}")
print(f"Gap: {OFFICIAL_PNL - combo:.2f}")

# Or maybe PM PnL = sum(realizedPnl) + unrealized
# unrealized = currentValue - initialValue + cashPnl?
# Actually: PnL per position = (value received back) - (value put in)
#   = (cash from sells + redeem value + current holding value) - (cash spent on buys)
#   cashPnl might = cash_out - cash_in for that position
#   total PnL = cashPnl + currentValue

# Count by status
redeemable = [p for p in all_positions if p.get('redeemable')]
open_pos = [p for p in all_positions if float(p.get('size') or 0) > 0 and not p.get('redeemable')]
print(f"\nRedeemable: {len(redeemable)}")
print(f"Open (non-redeemable): {len(open_pos)}")
print(f"Redeemable cashPnl: {sum(float(p.get('cashPnl') or 0) for p in redeemable):.2f}")
print(f"Redeemable currentValue: {sum(float(p.get('currentValue') or 0) for p in redeemable):.2f}")

# Check negativeRisk positions
neg_risk = [p for p in all_positions if p.get('negativeRisk')]
print(f"\nnegativeRisk positions: {len(neg_risk)}")
print(f"negativeRisk cashPnl: {sum(float(p.get('cashPnl') or 0) for p in neg_risk):.2f}")
