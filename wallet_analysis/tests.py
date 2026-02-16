from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

from django.test import TestCase

from wallet_analysis.calculators.pnl_calculator import PnLCalculator
from wallet_analysis.calculators.interfaces import ICashFlowProvider


# -- Test helpers --

class MockTrade:
    """Minimal trade object matching the Django Trade model interface."""

    def __init__(self, market_id, asset, timestamp, side, outcome,
                 price, size, total_value, dt=None):
        self.market_id = market_id
        self.market = MagicMock(id=market_id) if market_id else None
        self.asset = asset
        self.timestamp = timestamp
        self.datetime = dt or datetime.utcfromtimestamp(timestamp)
        self.side = side
        self.outcome = outcome
        self.price = Decimal(str(price))
        self.size = Decimal(str(size))
        self.total_value = Decimal(str(total_value))


class MockActivity:
    """Minimal activity object matching the Django Activity model interface."""

    def __init__(self, market_id, activity_type, timestamp,
                 size, usdc_size, dt=None, market=None, asset='', outcome=''):
        self.market_id = market_id
        self.market = market or (MagicMock(id=market_id) if market_id else None)
        self.activity_type = activity_type
        self.timestamp = timestamp
        self.datetime = dt or datetime.utcfromtimestamp(timestamp)
        self.size = Decimal(str(size))
        self.usdc_size = Decimal(str(usdc_size))
        self.asset = asset
        self.outcome = outcome
        self.title = ''


class MockCashFlowProvider(ICashFlowProvider):
    """Test cash flow provider with injectable data."""

    def __init__(self, trades=None, activities=None):
        self._trades = trades or []
        self._activities = activities or []

    def get_trades(self, wallet):
        return self._trades

    def get_activities(self, wallet):
        return self._activities


# Timestamps: Dec 2024 (before period), Jan 2025 (in period)
TS_DEC_01 = int(datetime(2024, 12, 1).timestamp())
TS_DEC_15 = int(datetime(2024, 12, 15).timestamp())
TS_JAN_10 = int(datetime(2025, 1, 10).timestamp())
TS_JAN_15 = int(datetime(2025, 1, 15).timestamp())
TS_JAN_20 = int(datetime(2025, 1, 20).timestamp())

PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2025, 1, 31)

MARKET_A = 1
ASSET_YES = 'token_yes_123'
ASSET_NO = 'token_no_456'


# -- Tests: CashFlow full history --

class TestCashFlowFullHistory(TestCase):
    """Test cashflow calculator with full (unfiltered) history."""

    def test_basic_buy_sell(self):
        """BUY + SELL: P&L = sells - buys."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_DEC_01, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.70, 100, 70),
        ]
        provider = MockCashFlowProvider(trades=trades)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        # Cashflow: sells($70) - buys($50) = $20
        self.assertAlmostEqual(result['total_realized_pnl'], 20.0)
        self.assertAlmostEqual(result['totals']['total_buys'], 50.0)
        self.assertAlmostEqual(result['totals']['total_sells'], 70.0)

    def test_all_activity_types(self):
        """All activity types contribute to P&L correctly."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_DEC_01, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'SELL', 'Yes', 0.70, 100, 70),
        ]
        activities = [
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_15, 50, 50),
            MockActivity(MARKET_A, 'MERGE', TS_JAN_15, 30, 30),
            MockActivity(MARKET_A, 'SPLIT', TS_JAN_15, 20, 20),
            MockActivity(None, 'REWARD', TS_JAN_15, 0, 10),
            MockActivity(None, 'CONVERSION', TS_JAN_15, 0, 5),
        ]
        provider = MockCashFlowProvider(trades=trades, activities=activities)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        # inflows: sells(70) + redeems(50) + merges(30) + rewards(10) + conversions(5) = 165
        # outflows: buys(50) + splits(20) = 70
        # pnl: 165 - 70 = 95
        self.assertAlmostEqual(result['total_realized_pnl'], 95.0)
        self.assertAlmostEqual(result['totals']['total_redeems'], 50.0)
        self.assertAlmostEqual(result['totals']['total_merges'], 30.0)
        self.assertAlmostEqual(result['totals']['total_splits'], 20.0)
        self.assertAlmostEqual(result['totals']['total_rewards'], 10.0)
        self.assertAlmostEqual(result['totals']['total_conversions'], 5.0)

    def test_empty_wallet(self):
        """No trades or activities: P&L = 0."""
        provider = MockCashFlowProvider()
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        self.assertAlmostEqual(result['total_realized_pnl'], 0.0)
        self.assertEqual(len(result['daily_pnl']), 0)
        self.assertEqual(len(result['pnl_by_market']), 0)


# -- Tests: CashFlow filtered --

class TestCashFlowFiltered(TestCase):
    """Test cashflow calculator with date-range filtering."""

    def test_period_filter_only_includes_period_activity(self):
        """Only activity within the period is counted."""
        trades = [
            # Before period - excluded
            MockTrade(MARKET_A, ASSET_YES, TS_DEC_01, 'BUY', 'Yes', 0.50, 100, 50),
            # In period - included
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.70, 100, 70),
        ]
        provider = MockCashFlowProvider(trades=trades)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate_filtered(None, PERIOD_START, PERIOD_END)

        # Only the SELL is in period: P&L = 70 - 0 = 70
        self.assertAlmostEqual(result['total_realized_pnl'], 70.0)
        self.assertAlmostEqual(result['totals']['total_buys'], 0.0)
        self.assertAlmostEqual(result['totals']['total_sells'], 70.0)

    def test_no_activity_in_period(self):
        """All activity before period: P&L = 0."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_DEC_01, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_DEC_15, 'SELL', 'Yes', 0.70, 100, 70),
        ]
        provider = MockCashFlowProvider(trades=trades)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate_filtered(None, PERIOD_START, PERIOD_END)

        self.assertAlmostEqual(result['total_realized_pnl'], 0.0)
        self.assertEqual(len(result['daily_pnl']), 0)

    def test_start_only_filter(self):
        """Filter with start_date only (no end_date)."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_DEC_01, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.70, 100, 70),
        ]
        provider = MockCashFlowProvider(trades=trades)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate_filtered(None, PERIOD_START, None)

        # Only Jan 15 SELL included
        self.assertAlmostEqual(result['total_realized_pnl'], 70.0)

    def test_end_only_filter(self):
        """Filter with end_date only (no start_date)."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_DEC_01, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.70, 100, 70),
        ]
        provider = MockCashFlowProvider(trades=trades)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate_filtered(None, None, date(2024, 12, 31))

        # Only Dec BUY included: P&L = 0 - 50 = -50
        self.assertAlmostEqual(result['total_realized_pnl'], -50.0)


# -- Tests: CashFlow output structure --

class TestCashFlowOutputStructure(TestCase):
    """Test the shape and structure of calculator output."""

    def test_daily_pnl_format(self):
        """daily_pnl entries have date, daily_pnl, cumulative_pnl."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'SELL', 'Yes', 0.60, 50, 30),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_20, 'SELL', 'Yes', 0.80, 50, 40),
        ]
        provider = MockCashFlowProvider(trades=trades)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        daily = result['daily_pnl']
        self.assertEqual(len(daily), 2)

        # Jan 10: +30
        self.assertAlmostEqual(daily[0]['daily_pnl'], 30.0)
        self.assertAlmostEqual(daily[0]['cumulative_pnl'], 30.0)

        # Jan 20: +40, cumulative 70
        self.assertAlmostEqual(daily[1]['daily_pnl'], 40.0)
        self.assertAlmostEqual(daily[1]['cumulative_pnl'], 70.0)

    def test_pnl_by_market_sorted_by_abs_pnl(self):
        """pnl_by_market is sorted by absolute PnL descending."""
        market_b = 2
        asset_b_yes = 'token_b_yes'

        trades = [
            # Market A: sells $70 - buys $50 = +$20
            MockTrade(MARKET_A, ASSET_YES, TS_DEC_01, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.70, 100, 70),
            # Market B: sells $50 - buys $80 = -$30
            MockTrade(market_b, asset_b_yes, TS_DEC_01, 'BUY', 'Yes', 0.80, 100, 80),
            MockTrade(market_b, asset_b_yes, TS_JAN_15, 'SELL', 'Yes', 0.50, 100, 50),
        ]
        provider = MockCashFlowProvider(trades=trades)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        markets = result['pnl_by_market']
        self.assertEqual(len(markets), 2)
        # |Market B| = 30 > |Market A| = 20
        self.assertEqual(markets[0]['market_id'], market_b)
        self.assertAlmostEqual(markets[0]['pnl'], -30.0)
        self.assertEqual(markets[1]['market_id'], MARKET_A)
        self.assertAlmostEqual(markets[1]['pnl'], 20.0)

    def test_totals_breakdown(self):
        """Totals include inflows and outflows."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.70, 100, 70),
        ]
        activities = [
            MockActivity(MARKET_A, 'SPLIT', TS_JAN_15, 10, 10),
        ]
        provider = MockCashFlowProvider(trades=trades, activities=activities)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        totals = result['totals']
        self.assertAlmostEqual(totals['total_buys'], 50.0)
        self.assertAlmostEqual(totals['total_sells'], 70.0)
        self.assertAlmostEqual(totals['total_splits'], 10.0)
        # inflows: 70, outflows: 60, pnl: 10
        self.assertAlmostEqual(totals['total_inflows'], 70.0)
        self.assertAlmostEqual(totals['total_outflows'], 60.0)
        self.assertAlmostEqual(result['total_realized_pnl'], 10.0)


# -- Tests: Split, merge, reward, conversion --

class TestCashFlowSplitMergeReward(TestCase):
    """Test individual activity type contributions."""

    def test_split_as_outflow(self):
        """SPLIT is an outflow (reduces P&L)."""
        activities = [
            MockActivity(MARKET_A, 'SPLIT', TS_JAN_15, 100, 100),
        ]
        provider = MockCashFlowProvider(activities=activities)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        self.assertAlmostEqual(result['total_realized_pnl'], -100.0)
        self.assertAlmostEqual(result['totals']['total_splits'], 100.0)

    def test_merge_as_inflow(self):
        """MERGE is an inflow (increases P&L)."""
        activities = [
            MockActivity(MARKET_A, 'MERGE', TS_JAN_15, 100, 100),
        ]
        provider = MockCashFlowProvider(activities=activities)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        self.assertAlmostEqual(result['total_realized_pnl'], 100.0)
        self.assertAlmostEqual(result['totals']['total_merges'], 100.0)

    def test_reward_as_income(self):
        """REWARD is pure income."""
        activities = [
            MockActivity(None, 'REWARD', TS_JAN_15, 0, 50),
        ]
        provider = MockCashFlowProvider(activities=activities)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        self.assertAlmostEqual(result['total_realized_pnl'], 50.0)
        self.assertAlmostEqual(result['totals']['total_rewards'], 50.0)

    def test_conversion_as_income(self):
        """CONVERSION is pure income."""
        activities = [
            MockActivity(None, 'CONVERSION', TS_JAN_15, 0, 25),
        ]
        provider = MockCashFlowProvider(activities=activities)
        calc = PnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        self.assertAlmostEqual(result['total_realized_pnl'], 25.0)
        self.assertAlmostEqual(result['totals']['total_conversions'], 25.0)


# -- Tests: Position Tracker (Weighted Average Cost Basis) --

from wallet_analysis.calculators.position_tracker import PositionTracker


MARKET_B = 2
ASSET_B_YES = 'token_b_yes'
ASSET_B_NO = 'token_b_no'


class TestPositionTracker(TestCase):
    """Test the WACB position tracking engine."""

    def setUp(self):
        self.tracker = PositionTracker()

    def test_single_buy_sets_cost_basis(self):
        """A single BUY sets avg_price = buy_price."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 100, 50),
        ]
        positions, events = self.tracker.process_events(trades, [])

        pos = positions[ASSET_YES]
        self.assertAlmostEqual(float(pos.avg_price), 0.50)
        self.assertAlmostEqual(float(pos.quantity), 100)
        self.assertEqual(len(events), 0)  # No realized PnL from buys

    def test_multiple_buys_weighted_average(self):
        """Two buys at different prices produce weighted average cost."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'BUY', 'Yes', 0.70, 100, 70),
        ]
        positions, events = self.tracker.process_events(trades, [])

        pos = positions[ASSET_YES]
        # (0.50 * 100 + 0.70 * 100) / 200 = 0.60
        self.assertAlmostEqual(float(pos.avg_price), 0.60)
        self.assertAlmostEqual(float(pos.quantity), 200)

    def test_sell_calculates_realized_pnl(self):
        """BUY then SELL realizes PnL = (sell_price - avg_price) * size."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.70, 100, 70),
        ]
        positions, events = self.tracker.process_events(trades, [])

        pos = positions[ASSET_YES]
        # Realized: (0.70 - 0.50) * 100 = $20
        self.assertAlmostEqual(float(pos.realized_pnl), 20.0)
        self.assertAlmostEqual(float(pos.quantity), 0)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(float(events[0].amount), 20.0)

    def test_sell_below_cost_basis(self):
        """Sell below cost basis produces negative realized PnL."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.70, 100, 70),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.50, 100, 50),
        ]
        positions, events = self.tracker.process_events(trades, [])

        pos = positions[ASSET_YES]
        # Realized: (0.50 - 0.70) * 100 = -$20
        self.assertAlmostEqual(float(pos.realized_pnl), -20.0)
        self.assertAlmostEqual(float(events[0].amount), -20.0)

    def test_partial_sell_preserves_avg_price(self):
        """Selling part of position does NOT change avg_price."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.70, 50, 35),
        ]
        positions, events = self.tracker.process_events(trades, [])

        pos = positions[ASSET_YES]
        # avg_price unchanged after sell
        self.assertAlmostEqual(float(pos.avg_price), 0.50)
        self.assertAlmostEqual(float(pos.quantity), 50)
        # Realized: (0.70 - 0.50) * 50 = $10
        self.assertAlmostEqual(float(pos.realized_pnl), 10.0)

    def test_winning_redeem(self):
        """REDEEM on winning position: (1.0 - avg) * qty."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.60, 100, 60),
        ]
        activities = [
            # Winner: 100 USDC for 100 shares = $1/share
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset=ASSET_YES, outcome='Yes'),
        ]
        positions, events = self.tracker.process_events(trades, activities)

        pos = positions[ASSET_YES]
        # Realized: (1.0 - 0.60) * 100 = $40
        self.assertAlmostEqual(float(pos.realized_pnl), 40.0)
        self.assertAlmostEqual(float(pos.quantity), 0)

    def test_losing_redeem(self):
        """REDEEM on losing position: (0.0 - avg) * qty."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.60, 100, 60),
        ]
        activities = [
            # Loser: 0 USDC for 100 shares = $0/share
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 0,
                         asset=ASSET_YES, outcome='Yes'),
        ]
        positions, events = self.tracker.process_events(trades, activities)

        pos = positions[ASSET_YES]
        # Realized: (0.0 - 0.60) * 100 = -$60
        self.assertAlmostEqual(float(pos.realized_pnl), -60.0)

    def test_split_creates_both_positions(self):
        """SPLIT creates YES + NO positions with 50/50 cost allocation."""
        # Need trades so market_assets map is populated
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 10, 5),
            MockTrade(MARKET_A, ASSET_NO, TS_JAN_10, 'BUY', 'No', 0.50, 10, 5),
        ]
        activities = [
            # Split $100 into 100 YES + 100 NO tokens
            MockActivity(MARKET_A, 'SPLIT', TS_JAN_15, 100, 100),
        ]
        positions, events = self.tracker.process_events(trades, activities)

        # Both YES and NO should have positions
        self.assertIn(ASSET_YES, positions)
        self.assertIn(ASSET_NO, positions)

        # Each gets 100 tokens at $0.50 cost basis from the split
        yes_pos = positions[ASSET_YES]
        no_pos = positions[ASSET_NO]

        # YES: 10 shares @ 0.50 + 100 shares @ 0.50 = 110 shares @ 0.50
        self.assertAlmostEqual(float(yes_pos.quantity), 110)
        self.assertAlmostEqual(float(yes_pos.avg_price), 0.50)

        # NO: same
        self.assertAlmostEqual(float(no_pos.quantity), 110)
        self.assertAlmostEqual(float(no_pos.avg_price), 0.50)

    def test_merge_combined_pnl(self):
        """MERGE returns YES + NO tokens for USDC, realizing PnL."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.40, 100, 40),
            MockTrade(MARKET_A, ASSET_NO, TS_JAN_10, 'BUY', 'No', 0.40, 100, 40),
        ]
        activities = [
            # Merge 100 YES + 100 NO for $90 USDC
            MockActivity(MARKET_A, 'MERGE', TS_JAN_15, 100, 90),
        ]
        positions, events = self.tracker.process_events(trades, activities)

        # Realized: 90 - (0.40 + 0.40) * 100 = 90 - 80 = $10
        total_realized = sum(float(e.amount) for e in events)
        self.assertAlmostEqual(total_realized, 10.0)

    def test_reward_pure_income(self):
        """REWARD generates pure income with no position change."""
        activities = [
            MockActivity(None, 'REWARD', TS_JAN_15, 0, 50),
        ]
        positions, events = self.tracker.process_events([], activities)

        # No positions created
        self.assertEqual(len(positions), 0)
        # Pure income event
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(float(events[0].amount), 50.0)

    def test_full_lifecycle(self):
        """Buy, partial sell, buy more, then redeem — full lifecycle."""
        trades = [
            # Buy 100 @ $0.40
            MockTrade(MARKET_A, ASSET_YES, TS_DEC_01, 'BUY', 'Yes', 0.40, 100, 40),
            # Sell 50 @ $0.60
            MockTrade(MARKET_A, ASSET_YES, TS_DEC_15, 'SELL', 'Yes', 0.60, 50, 30),
            # Buy 50 more @ $0.80
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.80, 50, 40),
        ]
        activities = [
            # Redeem remaining 100 shares @ $1.00 (winner)
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset=ASSET_YES, outcome='Yes'),
        ]
        positions, events = self.tracker.process_events(trades, activities)

        pos = positions[ASSET_YES]

        # After buy 100@0.40: avg=0.40, qty=100
        # After sell 50@0.60: realized = (0.60-0.40)*50 = $10, qty=50, avg=0.40
        # After buy 50@0.80: avg = (0.40*50 + 0.80*50)/100 = 60/100 = 0.60, qty=100
        # After redeem 100@1.00: realized = (1.00-0.60)*100 = $40, qty=0

        # Total realized: $10 + $40 = $50
        self.assertAlmostEqual(float(pos.realized_pnl), 50.0)
        self.assertAlmostEqual(float(pos.quantity), 0)

        total_events_pnl = sum(float(e.amount) for e in events)
        self.assertAlmostEqual(total_events_pnl, 50.0)


# -- Tests: CostBasisPnLCalculator --

from wallet_analysis.calculators.cost_basis_calculator import CostBasisPnLCalculator


class TestCostBasisCalculator(TestCase):
    """Test the cost basis calculator wrapper."""

    def test_output_contains_required_keys(self):
        """Output dict has all required keys including open_position_value."""
        provider = MockCashFlowProvider()
        calc = CostBasisPnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        self.assertIn('total_realized_pnl', result)
        self.assertIn('total_unrealized_pnl', result)
        self.assertIn('open_position_value', result)
        self.assertIn('total_pnl', result)
        self.assertIn('cash_flow_pnl', result)
        self.assertIn('daily_pnl', result)
        self.assertIn('pnl_by_market', result)
        self.assertIn('positions', result)
        self.assertIn('totals', result)

    def test_open_position_value_zero_when_no_wallet(self):
        """open_position_value is 0 when wallet is None (no current positions)."""
        provider = MockCashFlowProvider()
        calc = CostBasisPnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        self.assertAlmostEqual(result['open_position_value'], 0.0)

    def test_simple_buy_sell_matches_cashflow(self):
        """For a fully closed position, cost basis == cash flow PnL."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.70, 100, 70),
        ]
        provider = MockCashFlowProvider(trades=trades)
        calc = CostBasisPnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        # Both methods should agree: $20
        self.assertAlmostEqual(result['total_realized_pnl'], 20.0)
        self.assertAlmostEqual(result['cash_flow_pnl'], 20.0)

    def test_includes_unrealized_pnl(self):
        """Unrealized PnL is 0 when wallet is None (no current positions)."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 100, 50),
        ]
        provider = MockCashFlowProvider(trades=trades)
        calc = CostBasisPnLCalculator(cash_flow_provider=provider)

        result = calc.calculate(None)

        # No wallet = no current positions = 0 unrealized
        self.assertAlmostEqual(result['total_unrealized_pnl'], 0.0)
        # Cost basis: 0 realized (no sells/redeems, only a buy)
        self.assertAlmostEqual(result['total_realized_pnl'], 0.0)
        # Cash flow method sees the buy as -$50 outflow
        self.assertAlmostEqual(result['cash_flow_pnl'], -50.0)


# -- Tests: Cost Basis vs Cash Flow agreement --

class TestCostBasisVsCashFlow(TestCase):
    """Test that both methods agree for closed positions, differ for open."""

    def test_closed_positions_agree(self):
        """Full round-trip: buy then sell — both methods give same result."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 100, 50),
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_15, 'SELL', 'Yes', 0.70, 100, 70),
        ]
        provider = MockCashFlowProvider(trades=trades)

        cashflow_calc = PnLCalculator(cash_flow_provider=provider)
        costbasis_calc = CostBasisPnLCalculator(cash_flow_provider=provider)

        cf_result = cashflow_calc.calculate(None)
        cb_result = costbasis_calc.calculate(None)

        self.assertAlmostEqual(cf_result['total_realized_pnl'], 20.0)
        self.assertAlmostEqual(cb_result['total_realized_pnl'], 20.0)

    def test_open_positions_differ(self):
        """Open position: cash flow sees -$50 (buy), cost basis sees $0 realized + unrealized."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 100, 50),
        ]
        provider = MockCashFlowProvider(trades=trades)

        cashflow_calc = PnLCalculator(cash_flow_provider=provider)
        costbasis_calc = CostBasisPnLCalculator(cash_flow_provider=provider)

        cf_result = cashflow_calc.calculate(None)
        cb_result = costbasis_calc.calculate(None)

        # Cash flow: -$50 (only outflow, no inflow)
        self.assertAlmostEqual(cf_result['total_realized_pnl'], -50.0)
        # Cost basis: $0 realized (no sells), cash_flow_pnl preserved for comparison
        # Note: cost_basis realized = -50 from cashflow for parity,
        # but the position tracker sees 0 realized events
        self.assertAlmostEqual(cb_result['cash_flow_pnl'], -50.0)


# -- Tests: Unresolvable activity handling (skip, don't inflate) --

class TestUnresolvableActivities(TestCase):
    """
    When activities lack asset/outcome data needed for cost basis,
    they should be SKIPPED rather than inflating PnL.
    """

    def setUp(self):
        self.tracker = PositionTracker()

    def test_redeem_without_asset_skipped(self):
        """REDEEM with empty asset emits no realized PnL event."""
        activities = [
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_15, 100, 100,
                         asset='', outcome=''),
        ]
        positions, events = self.tracker.process_events([], activities)

        self.assertEqual(len(events), 0)
        self.assertEqual(len(positions), 0)

    def test_redeem_without_asset_no_market_assets_skipped(self):
        """REDEEM with no asset and no market_assets lookup also skipped."""
        activities = [
            MockActivity(None, 'REDEEM', TS_JAN_15, 50, 50,
                         asset='', outcome=''),
        ]
        positions, events = self.tracker.process_events([], activities)

        self.assertEqual(len(events), 0)

    def test_merge_without_market_id_skipped(self):
        """MERGE with no market_id emits no realized PnL event."""
        activities = [
            MockActivity(None, 'MERGE', TS_JAN_15, 100, 100),
        ]
        positions, events = self.tracker.process_events([], activities)

        self.assertEqual(len(events), 0)

    def test_merge_without_existing_positions_skipped(self):
        """MERGE where no pre-existing positions have cost basis is skipped."""
        # Trade creates market_assets mapping, but for a different asset
        # than what the merge would need — merge creates phantom positions
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.50, 10, 5),
            MockTrade(MARKET_A, ASSET_NO, TS_JAN_10, 'BUY', 'No', 0.50, 10, 5),
        ]
        # Sell all positions before merge
        trades += [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10 + 1, 'SELL', 'Yes', 0.50, 10, 5),
            MockTrade(MARKET_A, ASSET_NO, TS_JAN_10 + 1, 'SELL', 'No', 0.50, 10, 5),
        ]
        activities = [
            MockActivity(MARKET_A, 'MERGE', TS_JAN_15, 100, 100),
        ]
        positions, events = self.tracker.process_events(trades, activities)

        # The sells generate 2 events, but merge should NOT generate one
        merge_events = [e for e in events if e.asset == '' or
                        (e.timestamp == TS_JAN_15)]
        self.assertEqual(len(merge_events), 0)

    def test_conversion_without_asset_skipped(self):
        """CONVERSION with empty asset emits no realized PnL event."""
        activities = [
            MockActivity(None, 'CONVERSION', TS_JAN_15, 50, 50,
                         asset='', outcome=''),
        ]
        positions, events = self.tracker.process_events([], activities)

        self.assertEqual(len(events), 0)
        self.assertEqual(len(positions), 0)

    def test_reward_still_emits_income(self):
        """REWARD should still emit income (no asset needed)."""
        activities = [
            MockActivity(None, 'REWARD', TS_JAN_15, 0, 50),
        ]
        positions, events = self.tracker.process_events([], activities)

        # Rewards are always pure income — should still work
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(float(events[0].amount), 50.0)

    def test_redeem_resolved_via_market_resolution_winner(self):
        """REDEEM without asset resolves via market_resolutions: winner side."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.60, 100, 60),
        ]
        activities = [
            # Winner: 100 USDC for 100 shares, but no asset/outcome on activity
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset='', outcome=''),
        ]
        market_resolutions = {str(MARKET_A): 'Yes'}
        positions, events = self.tracker.process_events(
            trades, activities, market_resolutions
        )

        # usdc_size > 0 → winner → outcome = 'Yes' → asset = ASSET_YES
        self.assertEqual(len(events), 1)
        # (1.0 - 0.60) * 100 = $40
        self.assertAlmostEqual(float(events[0].amount), 40.0)
        self.assertAlmostEqual(float(positions[ASSET_YES].quantity), 0)

    def test_redeem_resolved_via_market_resolution_loser(self):
        """REDEEM without asset resolves via market_resolutions: loser side."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.60, 100, 60),
        ]
        activities = [
            # Loser: 0 USDC for 100 shares, no asset/outcome
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 0,
                         asset='', outcome=''),
        ]
        # Market resolved NO wins — so YES is the loser
        market_resolutions = {str(MARKET_A): 'No'}
        positions, events = self.tracker.process_events(
            trades, activities, market_resolutions
        )

        self.assertEqual(len(events), 1)
        # usdc_size == 0 → loser → outcome = 'Yes' (the other) → asset = ASSET_YES
        # (0.0 - 0.60) * 100 = -$60
        self.assertAlmostEqual(float(events[0].amount), -60.0)

    def test_redeem_both_sides_resolved_correctly(self):
        """Both-sides market: winner YES + loser NO sum to $0 net for split positions."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.80, 100, 80),
            MockTrade(MARKET_A, ASSET_NO, TS_JAN_10, 'BUY', 'No', 0.20, 100, 20),
        ]
        activities = [
            # Winner: 100 USDC for 100 shares (YES wins)
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset='', outcome=''),
            # Loser: 0 USDC for 100 shares
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20 + 1, 100, 0,
                         asset='', outcome=''),
        ]
        market_resolutions = {str(MARKET_A): 'Yes'}
        positions, events = self.tracker.process_events(
            trades, activities, market_resolutions
        )

        # Winner (YES): (1.0 - 0.80) * 100 = +$20
        # Loser (NO): (0.0 - 0.20) * 100 = -$20
        # Total: $0
        total = sum(float(e.amount) for e in events)
        self.assertAlmostEqual(total, 0.0)

    def test_redeem_no_resolution_data_inferred_from_position(self):
        """REDEEM without asset AND no market_resolutions: resolved via position inference."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.60, 100, 60),
        ]
        activities = [
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset='', outcome=''),
        ]
        # No market_resolutions — but single open position allows inference
        positions, events = self.tracker.process_events(trades, activities)

        # Position inference: only ASSET_YES open → resolved
        # (1.0 - 0.60) * 100 = $40
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(float(events[0].amount), 40.0)
        self.assertAlmostEqual(float(positions[ASSET_YES].quantity), 0)

    def test_redeem_with_asset_still_works(self):
        """REDEEM with proper asset data still calculates PnL correctly."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.60, 100, 60),
        ]
        activities = [
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset=ASSET_YES, outcome='Yes'),
        ]
        positions, events = self.tracker.process_events(trades, activities)

        # Should still work: (1.0 - 0.60) * 100 = $40
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(float(events[0].amount), 40.0)

    def test_redeem_two_open_positions_no_resolution_skipped(self):
        """Two open positions without market_resolutions: can't infer, both skipped."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.60, 100, 60),
            MockTrade(MARKET_A, ASSET_NO, TS_JAN_10, 'BUY', 'No', 0.40, 100, 40),
        ]
        activities = [
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset='', outcome=''),
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20 + 1, 100, 0,
                         asset='', outcome=''),
        ]
        # No market_resolutions — two open positions, can't determine sides
        positions, events = self.tracker.process_events(trades, activities)

        self.assertEqual(len(events), 0)

    def test_merge_with_existing_positions_still_works(self):
        """MERGE with proper position data still calculates PnL correctly."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.40, 100, 40),
            MockTrade(MARKET_A, ASSET_NO, TS_JAN_10, 'BUY', 'No', 0.40, 100, 40),
        ]
        activities = [
            MockActivity(MARKET_A, 'MERGE', TS_JAN_15, 100, 90),
        ]
        positions, events = self.tracker.process_events(trades, activities)

        # Realized: 90 - (0.40 + 0.40) * 100 = $10
        merge_events = [e for e in events if e.timestamp == TS_JAN_15]
        self.assertEqual(len(merge_events), 1)
        self.assertAlmostEqual(float(merge_events[0].amount), 10.0)


# -- Tests: REDEEM position-based inference --

class TestRedeemPositionInference(TestCase):
    """
    Test that REDEEMs with empty asset/outcome are resolved by inferring
    from existing open positions in the tracker.
    """

    def setUp(self):
        self.tracker = PositionTracker()

    def test_winner_inferred_from_single_position(self):
        """Winner REDEEM with empty asset resolved from the only open position."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.60, 100, 60),
        ]
        activities = [
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset='', outcome=''),
        ]
        # No market_resolutions — pure position inference
        positions, events = self.tracker.process_events(trades, activities)

        self.assertEqual(len(events), 1)
        # (1.0 - 0.60) * 100 = $40
        self.assertAlmostEqual(float(events[0].amount), 40.0)
        self.assertAlmostEqual(float(positions[ASSET_YES].quantity), 0)

    def test_loser_inferred_from_single_position(self):
        """Loser REDEEM with empty asset resolved from the only open position."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.60, 100, 60),
        ]
        activities = [
            # Loser: 0 USDC for 100 shares
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 0,
                         asset='', outcome=''),
        ]
        positions, events = self.tracker.process_events(trades, activities)

        self.assertEqual(len(events), 1)
        # (0.0 - 0.60) * 100 = -$60
        self.assertAlmostEqual(float(events[0].amount), -60.0)
        self.assertAlmostEqual(float(positions[ASSET_YES].quantity), 0)

    def test_both_sides_same_timestamp_resolved(self):
        """Both winner+loser REDEEMs at same timestamp: winner sorted first,
        then loser inferred from remaining position."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.80, 100, 80),
            MockTrade(MARKET_A, ASSET_NO, TS_JAN_10, 'BUY', 'No', 0.20, 100, 20),
        ]
        activities = [
            # Deliberately put loser first — sort should reorder
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 0,
                         asset='', outcome=''),
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset='', outcome=''),
        ]
        market_resolutions = {str(MARKET_A): 'Yes'}
        positions, events = self.tracker.process_events(
            trades, activities, market_resolutions
        )

        # Winner YES: (1.0 - 0.80) * 100 = +$20
        # Loser NO: (0.0 - 0.20) * 100 = -$20
        # Total: $0
        self.assertEqual(len(events), 2)
        total = sum(float(e.amount) for e in events)
        self.assertAlmostEqual(total, 0.0)

    def test_position_inference_takes_priority_over_market_resolutions(self):
        """Position inference (Stage 2) resolves before market_resolutions (Stage 3)."""
        trades = [
            MockTrade(MARKET_A, ASSET_YES, TS_JAN_10, 'BUY', 'Yes', 0.60, 100, 60),
        ]
        activities = [
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset='', outcome=''),
        ]
        # Provide market_resolutions too — but position inference should get there first
        market_resolutions = {str(MARKET_A): 'Yes'}
        positions, events = self.tracker.process_events(
            trades, activities, market_resolutions
        )

        # Same result either way: (1.0 - 0.60) * 100 = $40
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(float(events[0].amount), 40.0)

    def test_no_positions_no_resolutions_still_skipped(self):
        """REDEEM with no open positions and no market_resolutions is skipped."""
        activities = [
            MockActivity(MARKET_A, 'REDEEM', TS_JAN_20, 100, 100,
                         asset='', outcome=''),
        ]
        positions, events = self.tracker.process_events([], activities)

        self.assertEqual(len(events), 0)
        self.assertEqual(len(positions), 0)
