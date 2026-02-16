"""
P&L Calculator — re-exports from the calculators package.

The default calculator is now CostBasisPnLCalculator (WACB method).
For the legacy cash flow method, use calculate_wallet_pnl_cashflow().
"""

from .calculators.pnl_calculator import (
    calculate_wallet_pnl,
    calculate_wallet_pnl_filtered,
    calculate_wallet_pnl_cashflow,
    AvgCostBasisCalculator,
    PnLCalculator,
    CashFlowPnLCalculator,
)
from .calculators.cost_basis_calculator import CostBasisPnLCalculator

__all__ = [
    'calculate_wallet_pnl',
    'calculate_wallet_pnl_filtered',
    'calculate_wallet_pnl_cashflow',
    'AvgCostBasisCalculator',
    'PnLCalculator',
    'CashFlowPnLCalculator',
    'CostBasisPnLCalculator',
]
