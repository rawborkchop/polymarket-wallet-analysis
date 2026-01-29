from typing import List, Dict, Optional, Any
from collections import defaultdict

from src.api.models import Trade, TradeSide
from src.interfaces.trade_fetcher import ITradeFetcher


class TradeService:
    """
    Service for trade-related operations.

    Single Responsibility: Orchestrates trade fetching and basic transformations.
    Dependency Inversion: Depends on ITradeFetcher abstraction.
    """

    def __init__(self, trade_fetcher: ITradeFetcher):
        self._trade_fetcher = trade_fetcher

    def get_all_trades(
        self,
        wallet_address: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> List[Trade]:
        """Fetch all trades for a wallet."""
        return self._trade_fetcher.fetch_all_trades(
            wallet_address, after_timestamp, before_timestamp
        )

    def get_all_activity(
        self,
        wallet_address: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fetch all activity (TRADE + REDEEM + SPLIT + MERGE) for a wallet.

        Returns:
            Dict with 'trades' list (Trade objects including REDEEMs as sells),
            'raw_activity' dict with categorized raw data,
            and 'cash_flow' dict for P&L calculation.
        """
        # Get all activity types
        raw_activity = self._trade_fetcher.fetch_all_activity(
            wallet_address, after_timestamp, before_timestamp
        )

        # Convert trades
        trades = [Trade.from_api_response(t) for t in raw_activity.get("TRADE", [])]

        # Convert REDEEMs to trades (selling at $1)
        redeems = [Trade.from_redeem(r) for r in raw_activity.get("REDEEM", [])]

        # Combine and sort by timestamp
        all_trades = trades + redeems
        all_trades.sort(key=lambda t: t.timestamp)

        # Calculate cash flows for accurate P&L
        # P&L = (Sell + Redeem + Merge + Reward) - (Buy + Split)
        buy_trades = [t for t in raw_activity.get("TRADE", []) if t.get("side") == "BUY"]
        sell_trades = [t for t in raw_activity.get("TRADE", []) if t.get("side") == "SELL"]

        buy_cost = sum(float(t.get("size", 0)) * float(t.get("price", 0)) for t in buy_trades)
        sell_revenue = sum(float(t.get("size", 0)) * float(t.get("price", 0)) for t in sell_trades)

        # Token volumes (needed for points-based slippage calculation)
        buy_volume_tokens = sum(float(t.get("size", 0)) for t in buy_trades)
        sell_volume_tokens = sum(float(t.get("size", 0)) for t in sell_trades)

        redeem_revenue = sum(
            float(r.get("usdcSize", 0)) for r in raw_activity.get("REDEEM", [])
        )
        split_cost = sum(
            float(s.get("usdcSize", 0)) for s in raw_activity.get("SPLIT", [])
        )
        merge_revenue = sum(
            float(m.get("usdcSize", 0)) for m in raw_activity.get("MERGE", [])
        )
        reward_revenue = sum(
            float(r.get("usdcSize", 0)) for r in raw_activity.get("REWARD", [])
        )

        total_pnl = (sell_revenue + redeem_revenue + merge_revenue + reward_revenue) - (buy_cost + split_cost)

        return {
            "trades": all_trades,
            "raw_activity": raw_activity,
            "stats": {
                "trade_count": len(trades),
                "redeem_count": len(redeems),
                "split_count": len(raw_activity.get("SPLIT", [])),
                "merge_count": len(raw_activity.get("MERGE", [])),
                "reward_count": len(raw_activity.get("REWARD", [])),
            },
            "cash_flow": {
                "buy_cost": buy_cost,
                "sell_revenue": sell_revenue,
                "redeem_revenue": redeem_revenue,
                "split_cost": split_cost,
                "merge_revenue": merge_revenue,
                "reward_revenue": reward_revenue,
                "total_pnl": total_pnl,
                # Token volumes for points-based slippage
                "buy_volume_tokens": buy_volume_tokens,
                "sell_volume_tokens": sell_volume_tokens,
                # Note: activity API may be incomplete for high-volume wallets
                # Use fetch_pnl_from_subgraph() for accurate all-time P&L
                "_note": "Activity API may be incomplete. Use subgraph for accurate P&L.",
            }
        }

    def get_accurate_pnl(self, wallet_address: str) -> Dict[str, Any]:
        """
        Get accurate all-time P&L from the PnL subgraph.

        The activity API has data limitations. The subgraph indexes
        directly from blockchain and provides authoritative P&L data.
        """
        return self._trade_fetcher.fetch_pnl_from_subgraph(wallet_address)

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
