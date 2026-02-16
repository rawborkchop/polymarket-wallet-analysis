import sqlite3
conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row

# Check if splits/merges correspond to trades or are separate
# Look at a specific split transaction
splits = conn.execute("""
    SELECT * FROM wallet_analysis_activity
    WHERE wallet_id=7 AND activity_type='SPLIT'
    ORDER BY datetime LIMIT 5
""").fetchall()

for s in splits:
    print(f"\nSPLIT: tx={s['transaction_hash'][:20]}... market={s['market_id']} usdc={s['usdc_size']} dt={s['datetime']}")
    # Check if there are trades with the same tx hash
    trades = conn.execute("""
        SELECT * FROM wallet_analysis_trade
        WHERE wallet_id=7 AND transaction_hash=?
    """, (s['transaction_hash'],)).fetchall()
    if trades:
        for t in trades:
            print(f"  TRADE: side={t['side']} asset={t['asset'][:20]}... size={t['size']} price={t['price']} total={t['total_value']}")
    else:
        print("  No matching trades")

# Same for conversions
convs = conn.execute("""
    SELECT * FROM wallet_analysis_activity
    WHERE wallet_id=7 AND activity_type='CONVERSION'
    ORDER BY datetime LIMIT 5
""").fetchall()

for c in convs:
    print(f"\nCONVERSION: tx={c['transaction_hash'][:20]}... market={c['market_id']} usdc={c['usdc_size']} dt={c['datetime']}")
    trades = conn.execute("""
        SELECT * FROM wallet_analysis_trade
        WHERE wallet_id=7 AND transaction_hash=?
    """, (c['transaction_hash'],)).fetchall()
    if trades:
        for t in trades:
            print(f"  TRADE: side={t['side']} asset={t['asset'][:20]}... size={t['size']} price={t['price']} total={t['total_value']}")
    else:
        print("  No matching trades")

# Merges
merges = conn.execute("""
    SELECT * FROM wallet_analysis_activity
    WHERE wallet_id=7 AND activity_type='MERGE'
    ORDER BY datetime LIMIT 5
""").fetchall()

for m in merges:
    print(f"\nMERGE: tx={m['transaction_hash'][:20]}... market={m['market_id']} usdc={m['usdc_size']} dt={m['datetime']}")
    trades = conn.execute("""
        SELECT * FROM wallet_analysis_trade
        WHERE wallet_id=7 AND transaction_hash=?
    """, (m['transaction_hash'],)).fetchall()
    if trades:
        for t in trades:
            print(f"  TRADE: side={t['side']} asset={t['asset'][:20]}... size={t['size']} price={t['price']} total={t['total_value']}")
    else:
        print("  No matching trades")
