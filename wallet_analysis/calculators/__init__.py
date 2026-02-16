"""
Calculators module — P&L calculation components.

Provides two calculation strategies:
- CostBasisPnLCalculator (default): Weighted Average Cost Basis method
- PnLCalculator / CashFlowPnLCalculator: Legacy cash flow method
"""

from .pnl_calculator import (
    PnLCalculator,
    CashFlowPnLCalculator,
    calculate_wallet_pnl,
    calculate_wallet_pnl_filtered,
    calculate_wallet_pnl_cashflow,
)
from .cost_basis_calculator import CostBasisPnLCalculator
from .position_tracker import PositionTracker, PositionState, RealizedPnLEvent
from .interfaces import IPnLCalculator, ICashFlowProvider, IPositionTracker
from .aggregators import MarketAggregator, DailyAggregator

__all__ = [
    'PnLCalculator',
    'CashFlowPnLCalculator',
    'CostBasisPnLCalculator',
    'PositionTracker',
    'PositionState',
    'RealizedPnLEvent',
    'calculate_wallet_pnl',
    'calculate_wallet_pnl_filtered',
    'calculate_wallet_pnl_cashflow',
    'IPnLCalculator',
    'ICashFlowProvider',
    'IPositionTracker',
    'MarketAggregator',
    'DailyAggregator',
]
