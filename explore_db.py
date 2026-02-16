import sqlite3
conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

# Tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("Tables:", tables)

# Look at trade-related tables
for t in tables:
    if 'trade' in t.lower() or 'redeem' in t.lower() or 'wallet' in t.lower() or 'pnl' in t.lower():
        c.execute(f"PRAGMA table_info({t})")
        cols = [(r[1], r[2]) for r in c.fetchall()]
        c.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = c.fetchone()[0]
        print(f"\n{t} ({cnt} rows): {cols}")
        if cnt > 0:
            c.execute(f"SELECT * FROM {t} LIMIT 2")
            for row in c.fetchall():
                print("  ", row)
