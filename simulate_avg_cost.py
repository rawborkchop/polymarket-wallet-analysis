"""
Position-level average cost basis PnL simulation for Polymarket.
Final version with correct redeem ordering and split handling.
"""
import django, os
from decimal import Decimal
from collections import defaultdict
from dataclasses import dataclass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market

WALLET_ID = 7
OFFICIAL_PNL = Decimal('20172.77')
CASHFLOW_PNL = Decimal('19283.18')
D = lambda x: Decimal(str(x))
ZERO = Decimal('0')
ONE = Decimal('1')
EPS = Decimal('0.000001')


@dataclass
class Pos:
    shares: Decimal = ZERO
    avg_cost: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    title: str = ''

    def buy(self, size, price):
        old = self.shares * self.avg_cost
        self.shares += size
        if self.shares > EPS:
            self.avg_cost = (old + size * price) / self.shares

    def sell(self, size, price):
        if self.shares > EPS:
            pnl = min(size, self.shares) * (price - self.avg_cost)
            self.realized_pnl += pnl
            self.shares -= size
            if self.shares < EPS:
                self.shares = ZERO
                self.avg_cost = ZERO

    def zero_out(self):
        """Loser redeem: lose all shares."""
        if self.shares > EPS:
            self.realized_pnl -= self.shares * self.avg_cost
            self.shares = ZERO
            self.avg_cost = ZERO


def make_sort_key(etype, obj):
    """Sort key: (timestamp, type_priority, id).
    Winner redeems (usdc>0) sort BEFORE loser redeems (usdc=0) at same timestamp.
    Trades sort before activities at same timestamp.
    """
    if etype == 'trade':
        return (obj.timestamp, 0, obj.id)
    else:
        a = obj
        if a.activity_type == 'REDEEM':
            if D(a.usdc_size) > 0:
                return (a.timestamp, 1, a.id)  # winner redeem
            else:
                return (a.timestamp, 3, a.id)  # loser redeem LAST
        elif a.activity_type in ('SPLIT', 'CONVERSION', 'MERGE'):
            return (a.timestamp, 0, a.id)  # before redeems
        else:
            return (a.timestamp, 2, a.id)


def simulate(include_rewards=True, include_conversions=True,
             split_mode='both', redeem_order='winner_first'):
    """
    split_mode:
      'both' - splits add shares to all known outcomes
      'none' - splits don't create positions
      'traded_only' - splits add shares only to outcomes with existing positions
    redeem_order:
      'winner_first' - process winner redeems before loser redeems at same timestamp
      'id' - process by id order (original)
    """
    w = Wallet.objects.get(id=WALLET_ID)
    trades = list(Trade.objects.filter(wallet=w).select_related('market').order_by('timestamp', 'id'))
    activities = list(Activity.objects.filter(wallet=w).select_related('market').order_by('timestamp', 'id'))

    events = []
    for t in trades:
        events.append(('trade', t))
    for a in activities:
        if a.activity_type == 'REWARD' and not include_rewards:
            continue
        if a.activity_type == 'CONVERSION' and not include_conversions:
            continue
        events.append(('activity', a))

    if redeem_order == 'winner_first':
        events.sort(key=lambda x: make_sort_key(x[0], x[1]))
    else:
        events.sort(key=lambda x: (x[1].timestamp, 0 if x[0] == 'trade' else 1, x[1].id))

    positions = defaultdict(Pos)
    market_outcomes = defaultdict(set)
    market_titles = {}
    total_rewards = ZERO
    stats = defaultdict(int)

    for t in trades:
        if t.market_id:
            market_outcomes[t.market_id].add(t.outcome)
            if t.market_id not in market_titles:
                market_titles[t.market_id] = t.market.title[:80] if t.market else ''
    for a in activities:
        if a.market_id and a.market_id not in market_titles:
            market_titles[a.market_id] = a.market.title[:80] if a.market else ''

    for etype, obj in events:
        if etype == 'trade':
            t = obj
            if not t.market_id:
                continue
            key = (t.market_id, t.outcome)
            pos = positions[key]
            pos.title = market_titles.get(t.market_id, '')
            price, size = D(t.price), D(t.size)
            if t.side == 'BUY':
                pos.buy(size, price)
            else:
                pos.sell(size, price)

        else:
            a = obj
            if not a.market_id:
                continue
            size = D(a.size)
            usdc = D(a.usdc_size)

            if a.activity_type == 'REWARD':
                total_rewards += usdc
                continue

            if a.activity_type in ('SPLIT', 'CONVERSION'):
                if split_mode == 'none':
                    continue
                outcomes = market_outcomes.get(a.market_id, {'Yes', 'No'})
                n = len(outcomes)
                cost_per_share = usdc / (size * n) if size > 0 and n > 0 else ZERO

                if split_mode == 'traded_only':
                    # Only add to outcomes with existing positions
                    for outcome in outcomes:
                        key = (a.market_id, outcome)
                        if key in positions and positions[key].shares > EPS:
                            positions[key].buy(size, cost_per_share)
                else:
                    for outcome in outcomes:
                        key = (a.market_id, outcome)
                        pos = positions[key]
                        pos.title = market_titles.get(a.market_id, '')
                        pos.buy(size, cost_per_share)

            elif a.activity_type == 'MERGE':
                outcomes = market_outcomes.get(a.market_id, {'Yes', 'No'})
                n = len(outcomes)
                rev_per_share = usdc / (size * n) if size > 0 and n > 0 else ZERO
                for outcome in outcomes:
                    key = (a.market_id, outcome)
                    pos = positions[key]
                    if pos.shares > EPS:
                        pos.sell(min(size, pos.shares), rev_per_share)

            elif a.activity_type == 'REDEEM':
                is_winner = usdc > 0
                if is_winner:
                    stats['winner_redeems'] += 1
                    market_pos = [(k, v) for k, v in positions.items()
                                  if k[0] == a.market_id and v.shares > EPS]
                    if not market_pos:
                        stats['unmatched_winners'] += 1
                        stats['unmatched_usdc'] += float(usdc)
                        continue
                    # Exact match first
                    matched = False
                    for key, pos in market_pos:
                        if abs(pos.shares - size) < Decimal('0.5'):
                            pos.sell(size, ONE)
                            matched = True
                            break
                    if not matched:
                        remaining = size
                        for key, pos in sorted(market_pos, key=lambda x: x[1].shares, reverse=True):
                            if pos.shares > EPS and remaining > EPS:
                                amt = min(remaining, pos.shares)
                                pos.sell(amt, ONE)
                                remaining -= amt
                        if remaining > Decimal('0.5'):
                            stats['partial_unmatched'] += 1
                            stats['partial_unmatched_shares'] += float(remaining)
                else:
                    stats['loser_redeems'] += 1
                    for key, pos in positions.items():
                        if key[0] == a.market_id:
                            pos.zero_out()

    total_realized = sum(p.realized_pnl for p in positions.values()) + total_rewards
    open_pos = [(k, p) for k, p in positions.items() if p.shares > EPS]
    open_cost = sum(p.shares * p.avg_cost for _, p in open_pos)
    open_shares = sum(p.shares for _, p in open_pos)

    # Market-level PnL
    market_pnls = {}
    for (mid, outcome), pos in positions.items():
        if mid not in market_pnls:
            market_pnls[mid] = {'title': pos.title or market_titles.get(mid, ''), 'pnl': ZERO, 'open': ZERO}
        market_pnls[mid]['pnl'] += pos.realized_pnl
        market_pnls[mid]['open'] += pos.shares

    return {
        'realized': total_realized,
        'rewards': total_rewards,
        'stats': dict(stats),
        'open_count': len(open_pos),
        'open_cost': open_cost,
        'open_shares': open_shares,
        'market_pnls': market_pnls,
    }


def show(label, r):
    print(f'\n{"="*70}')
    print(f'  {label}')
    print(f'{"="*70}')
    print(f'  Realized PnL:     ${r["realized"]:>12,.2f}')
    print(f'  Rewards:          ${r["rewards"]:>12,.2f}')
    print(f'  Open:             {r["open_count"]} pos ({r["open_shares"]:,.1f} shares, ${r["open_cost"]:,.2f} cost)')
    print(f'  Stats:            {r["stats"]}')
    print(f'  Gap vs Official:  ${r["realized"] - OFFICIAL_PNL:>+12,.2f}')
    print(f'  Gap vs CashFlow:  ${r["realized"] - CASHFLOW_PNL:>+12,.2f}')

    sorted_m = sorted(r['market_pnls'].items(), key=lambda x: x[1]['pnl'], reverse=True)
    print(f'\n  Top 10:')
    for mid, d in sorted_m[:10]:
        o = f' [OPEN {d["open"]:.0f}]' if d['open'] > 0.01 else ''
        print(f'    ${d["pnl"]:>+10,.2f}  {d["title"][:55]}{o}')
    print(f'  Bottom 10:')
    for mid, d in sorted_m[-10:]:
        o = f' [OPEN {d["open"]:.0f}]' if d['open'] > 0.01 else ''
        print(f'    ${d["pnl"]:>+10,.2f}  {d["title"][:55]}{o}')


if __name__ == '__main__':
    print('='*70)
    print('  Polymarket Avg Cost Basis PnL Simulation')
    print(f'  Official: ${OFFICIAL_PNL:,.2f} | CashFlow: ${CASHFLOW_PNL:,.2f} | Gap: ${OFFICIAL_PNL-CASHFLOW_PNL:,.2f}')
    print('='*70)

    configs = [
        ('1. Trades only, winner-first redeems',
         dict(split_mode='none', redeem_order='winner_first')),
        ('2. Trades only, id-order redeems',
         dict(split_mode='none', redeem_order='id')),
        ('3. Splits=both outcomes, winner-first',
         dict(split_mode='both', redeem_order='winner_first')),
        ('4. Splits=both outcomes, id-order',
         dict(split_mode='both', redeem_order='id')),
        ('5. Splits=traded only, winner-first',
         dict(split_mode='traded_only', redeem_order='winner_first')),
        ('6. No conversions, splits=both, winner-first',
         dict(split_mode='both', redeem_order='winner_first', include_conversions=False)),
        ('7. No rewards, splits=none, winner-first',
         dict(split_mode='none', redeem_order='winner_first', include_rewards=False)),
    ]

    results = []
    for label, kwargs in configs:
        r = simulate(**kwargs)
        show(label, r)
        results.append((label, r))

    print(f'\n{"="*70}')
    print('  SUMMARY')
    print(f'{"="*70}')
    print(f'  {"Config":<50} {"PnL":>10} {"Gap":>10} {"Open":>5}')
    print(f'  {"-"*50} {"-"*10} {"-"*10} {"-"*5}')
    for label, r in results:
        gap = r['realized'] - OFFICIAL_PNL
        print(f'  {label:<50} ${r["realized"]:>8,.2f} ${gap:>+8,.2f} {r["open_count"]:>4}')
    print(f'  {"Cash flow method":<50} ${CASHFLOW_PNL:>8,.2f} ${CASHFLOW_PNL-OFFICIAL_PNL:>+8,.2f}    -')
