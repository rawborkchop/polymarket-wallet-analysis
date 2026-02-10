"""
P&L Calculator - SINGLE SOURCE OF TRUTH for P&L calculation.

This module re-exports the SOLID-compliant calculator from the calculators package.
For direct use of the calculator classes, import from wallet_analysis.calculators.

Formula: P&L = (sells + redeems + merges + rewards) - (buys + splits)

IMPORTANT:
- Trades table contains only actual BUY/SELL trades (NO redeems as fake sells)
- Activities table contains REDEEM, SPLIT, MERGE, REWARD
- This calculator combines both for accurate P&L
"""

# Re-export from the calculators package for backward compatibility
from .calculators.pnl_calculator import (
    calculate_wallet_pnl,
    calculate_wallet_pnl_filtered,
    PnLCalculator,
)

__all__ = [
    'calculate_wallet_pnl',
    'calculate_wallet_pnl_filtered',
    'PnLCalculator',
]
