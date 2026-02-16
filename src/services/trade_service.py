from decimal import Decimal
from typing import List, Dict, Optional, Any
from collections import defaultdict

from src.api.models import Trade, TradeSide, to_decimal
from src.interfaces.trade_fetcher import ITradeFetcher


class TradeService:
    """
    Service for trade-related operations.

    Single Responsibility: Orchestrates trade fetching and basic transformations.
    Dependency Inversion: Depends on ITradeFetcher abstraction.
    """

    def __init__(self, trade_fetcher: ITradeFetcher):
        self._trade_fetcher = trade_fetcher

    def get_all_activity(
        self,
        wallet_address: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fetch all activity (TRADE + REDEEM + SPLIT + MERGE + REWARD + CONVERSION) for a wallet.

        Returns:
            Dict with 'trades' list (Trade objects - BUY/SELL only, NO redeems),
            'raw_activity' dict with categorized raw data,
            and 'cash_flow' dict with summary statistics.

        IMPORTANT: REDEEMs are NOT converted to trades. They are stored separately
        as Activity records. The P&L calculation is done by pnl_calculator.py
        which combines trades AND activities.
        """
        # Get all activity types
        raw_activity = self._trade_fetcher.fetch_all_activity(
            wallet_address, after_timestamp, before_timestamp
        )

        # Convert trades (BUY/SELL only - NO redeems)
        trades = [Trade.from_api_response(t) for t in raw_activity.get("TRADE", [])]
        trades.sort(key=lambda t: t.timestamp)

        # Calculate cash flows using Decimal for precision
        # NOTE: This is NOT the source of truth for P&L - that's pnl_calculator.py
        buy_trades = [t for t in raw_activity.get("TRADE", []) if t.get("side") == "BUY"]
        sell_trades = [t for t in raw_activity.get("TRADE", []) if t.get("side") == "SELL"]

        buy_cost = sum(
            (to_decimal(t.get("size", 0)) * to_decimal(t.get("price", 0)))
            for t in buy_trades
        )
        sell_revenue = sum(
            (to_decimal(t.get("size", 0)) * to_decimal(t.get("price", 0)))
            for t in sell_trades
        )

        # Token volumes (needed for points-based slippage calculation)
        buy_volume_tokens = sum(to_decimal(t.get("size", 0)) for t in buy_trades)
        sell_volume_tokens = sum(to_decimal(t.get("size", 0)) for t in sell_trades)

        redeem_revenue = sum(
            to_decimal(r.get("usdcSize", 0)) for r in raw_activity.get("REDEEM", [])
        )
        split_cost = sum(
            to_decimal(s.get("usdcSize", 0)) for s in raw_activity.get("SPLIT", [])
        )
        merge_revenue = sum(
            to_decimal(m.get("usdcSize", 0)) for m in raw_activity.get("MERGE", [])
        )
        reward_revenue = sum(
            to_decimal(r.get("usdcSize", 0)) for r in raw_activity.get("REWARD", [])
        )
        conversion_revenue = sum(
            to_decimal(c.get("usdcSize", 0)) for c in raw_activity.get("CONVERSION", [])
        )

        # This is a preview P&L from the current fetch only
        # The authoritative P&L comes from pnl_calculator after DB save
        preview_pnl = (sell_revenue + redeem_revenue + merge_revenue + reward_revenue + conversion_revenue) - (buy_cost + split_cost)

        return {
            "trades": trades,  # Only actual trades, no fake redeem trades
            "raw_activity": raw_activity,
            "stats": {
                "trade_count": len(trades),
                "redeem_count": len(raw_activity.get("REDEEM", [])),
                "split_count": len(raw_activity.get("SPLIT", [])),
                "merge_count": len(raw_activity.get("MERGE", [])),
                "reward_count": len(raw_activity.get("REWARD", [])),
                "conversion_count": len(raw_activity.get("CONVERSION", [])),
            },
            "cash_flow": {
                # All values as float for JSON serialization, but calculated with Decimal
                "buy_cost": float(buy_cost),
                "sell_revenue": float(sell_revenue),
                "redeem_revenue": float(redeem_revenue),
                "split_cost": float(split_cost),
                "merge_revenue": float(merge_revenue),
                "reward_revenue": float(reward_revenue),
                "conversion_revenue": float(conversion_revenue),
                "preview_pnl": float(preview_pnl),  # Preview only
                # Token volumes for points-based slippage
                "buy_volume_tokens": float(buy_volume_tokens),
                "sell_volume_tokens": float(sell_volume_tokens),
                "_note": "Preview P&L from this fetch. Authoritative P&L from pnl_calculator.",
            }
        }

    def get_current_positions(self, wallet_address: str) -> List[dict]:
        """Get current open positions with P&L data."""
        return self._trade_fetcher.fetch_current_positions(wallet_address)

    def get_trades_by_market(self, trades: List[Trade]) -> Dict[str, List[Trade]]:
        """Group trades by market (condition_id)."""
        grouped: Dict[str, List[Trade]] = defaultdict(list)
        for trade in trades:
            grouped[trade.condition_id].append(trade)
        return dict(grouped)

    def get_trades_by_side(self, trades: List[Trade]) -> Dict[TradeSide, List[Trade]]:
        """Group trades by side (BUY/SELL)."""
        grouped: Dict[TradeSide, List[Trade]] = defaultdict(list)
        for trade in trades:
            grouped[trade.side].append(trade)
        return dict(grouped)

    def get_unique_markets(self, trades: List[Trade]) -> List[str]:
        """Get list of unique market titles."""
        return list(set(trade.title for trade in trades))

    def filter_by_date_range(
        self, trades: List[Trade], start_timestamp: int, end_timestamp: int
    ) -> List[Trade]:
        """Filter trades by timestamp range."""
        return [
            trade for trade in trades
            if start_timestamp <= trade.timestamp <= end_timestamp
        ]

    def sort_by_timestamp(self, trades: List[Trade], descending: bool = True) -> List[Trade]:
        """Sort trades by timestamp."""
        return sorted(trades, key=lambda t: t.timestamp, reverse=descending)
