from typing import List, Dict, Any, Optional
from collections import defaultdict
from dataclasses import dataclass

from src.api.models import Trade, TradeSide
from src.api.gamma_client import GammaClient
from src.interfaces.analyzer import IAnalyzer


@dataclass
class CashFlowPnL:
    """
    Simple cash flow P&L calculation.

    P&L = (Sell + Redeem + Merge) - (Buy + Split)

    This matches Polymarket's displayed P&L.
    """
    buy_cost: float = 0.0
    sell_revenue: float = 0.0
    redeem_revenue: float = 0.0
    split_cost: float = 0.0
    merge_revenue: float = 0.0

    @property
    def total_pnl(self) -> float:
        return (
            self.sell_revenue + self.redeem_revenue + self.merge_revenue
        ) - (
            self.buy_cost + self.split_cost
        )

    @property
    def total_inflows(self) -> float:
        return self.sell_revenue + self.redeem_revenue + self.merge_revenue

    @property
    def total_outflows(self) -> float:
        return self.buy_cost + self.split_cost


@dataclass
class MarketPosition:
    """Represents a position in a specific market outcome."""

    market_title: str
    condition_id: str
    outcome: str
    total_bought: float
    total_sold: float
    avg_buy_price: float
    avg_sell_price: float
    total_buy_cost: float
    total_sell_revenue: float
    trades_count: int
    resolved: bool = False
    won: Optional[bool] = None

    @property
    def net_position(self) -> float:
        """Current position size."""
        return self.total_bought - self.total_sold

    @property
    def realized_pnl(self) -> float:
        """
        Realized profit/loss.

        For resolved markets:
        - If won: profit = (1 - avg_buy_price) * size_held + sell_pnl
        - If lost: loss = avg_buy_price * size_held - sell_pnl

        For unresolved: only count explicit sells
        """
        # P&L from explicit sells
        sold_size = min(self.total_bought, self.total_sold)
        sell_pnl = sold_size * (self.avg_sell_price - self.avg_buy_price) if sold_size > 0 else 0

        if not self.resolved:
            return sell_pnl

        # P&L from market resolution
        remaining_size = self.total_bought - self.total_sold
        if remaining_size <= 0:
            return sell_pnl

        if self.won:
            # Won: each token redeems for $1
            resolution_pnl = remaining_size * (1.0 - self.avg_buy_price)
        else:
            # Lost: tokens worth $0
            resolution_pnl = -remaining_size * self.avg_buy_price

        return sell_pnl + resolution_pnl

    @property
    def is_closed(self) -> bool:
        """Check if position is fully closed (sold or resolved)."""
        if self.resolved:
            return True
        return abs(self.net_position) < 0.0001


class AnalyticsService(IAnalyzer):
    """
    Service for analyzing trading performance.

    Single Responsibility: Only handles analytics calculations.
    Open/Closed: Can be extended with new metrics without modification.
    """

    def __init__(self, gamma_client: Optional[GammaClient] = None):
        self._gamma_client = gamma_client or GammaClient()

    def analyze(self, trades: List[Trade]) -> Dict[str, Any]:
        """Perform comprehensive analysis on trades."""
        if not trades:
            return self._empty_analysis()

        # Get unique condition_ids and fetch resolutions
        condition_ids = list(set(t.condition_id for t in trades))
        resolutions = self._gamma_client.get_market_resolutions(condition_ids)

        positions = self._calculate_positions(trades, resolutions)

        return {
            "summary": self._calculate_summary(trades),
            "performance": self._calculate_performance(positions),
            "market_breakdown": self._calculate_market_breakdown(trades, positions),
            "time_analysis": self._calculate_time_analysis(trades),
            "risk_metrics": self._calculate_risk_metrics(positions),
            "_resolutions": resolutions,  # Internal: pass to other analyzers
        }

    def _empty_analysis(self) -> Dict[str, Any]:
        """Return empty analysis structure."""
        return {
            "summary": {},
            "performance": {},
            "market_breakdown": [],
            "time_analysis": {},
            "risk_metrics": {},
        }

    def _calculate_positions(
        self, trades: List[Trade], resolutions: Dict[str, dict]
    ) -> Dict[str, MarketPosition]:
        """Calculate positions for each market/outcome combination."""
        position_data: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "buys": [],
                "sells": [],
                "title": "",
                "condition_id": "",
                "outcome": "",
            }
        )

        for trade in trades:
            key = f"{trade.condition_id}_{trade.outcome}"
            position_data[key]["title"] = trade.title
            position_data[key]["condition_id"] = trade.condition_id
            position_data[key]["outcome"] = trade.outcome

            if trade.is_buy:
                position_data[key]["buys"].append(trade)
            else:
                position_data[key]["sells"].append(trade)

        positions = {}
        for key, data in position_data.items():
            buys = data["buys"]
            sells = data["sells"]
            condition_id = data["condition_id"]
            outcome = data["outcome"]

            total_bought = float(sum(t.size for t in buys))
            total_sold = float(sum(t.size for t in sells))
            total_buy_cost = float(sum(t.total_value for t in buys))
            total_sell_revenue = float(sum(t.total_value for t in sells))

            # Get resolution info
            resolution = resolutions.get(condition_id, {})
            resolved = resolution.get("resolved", False)
            winning_outcome = resolution.get("winning_outcome")
            won = (winning_outcome == outcome) if resolved and winning_outcome else None

            positions[key] = MarketPosition(
                market_title=data["title"],
                condition_id=condition_id,
                outcome=outcome,
                total_bought=total_bought,
                total_sold=total_sold,
                avg_buy_price=total_buy_cost / total_bought if total_bought > 0 else 0,
                avg_sell_price=total_sell_revenue / total_sold if total_sold > 0 else 0,
                total_buy_cost=total_buy_cost,
                total_sell_revenue=total_sell_revenue,
                trades_count=len(buys) + len(sells),
                resolved=resolved,
                won=won,
            )

        return positions

    def _calculate_summary(self, trades: List[Trade]) -> Dict[str, Any]:
        """Calculate high-level summary statistics."""
        buys = [t for t in trades if t.is_buy]
        sells = [t for t in trades if t.is_sell]

        total_volume = float(sum(t.size for t in trades))
        total_buy_volume = float(sum(t.size for t in buys))
        total_sell_volume = float(sum(t.size for t in sells))

        unique_markets = len(set(t.condition_id for t in trades))

        timestamps = [t.timestamp for t in trades]

        return {
            "total_trades": len(trades),
            "total_buys": len(buys),
            "total_sells": len(sells),
            "total_volume_usd": round(total_volume, 2),
            "total_buy_volume_usd": round(total_buy_volume, 2),
            "total_sell_volume_usd": round(total_sell_volume, 2),
            "unique_markets": unique_markets,
            "first_trade_timestamp": min(timestamps) if timestamps else None,
            "last_trade_timestamp": max(timestamps) if timestamps else None,
            "avg_trade_size_usd": round(total_volume / len(trades), 2) if trades else 0,
        }

    def _calculate_performance(self, positions: Dict[str, MarketPosition]) -> Dict[str, Any]:
        """Calculate performance metrics."""
        closed_positions = [p for p in positions.values() if p.is_closed]
        open_positions = [p for p in positions.values() if not p.is_closed]

        winning_positions = [p for p in closed_positions if p.realized_pnl > 0]
        losing_positions = [p for p in closed_positions if p.realized_pnl < 0]

        total_realized_pnl = sum(p.realized_pnl for p in closed_positions)
        total_wins = sum(p.realized_pnl for p in winning_positions)
        total_losses = abs(sum(p.realized_pnl for p in losing_positions))

        win_rate = (
            len(winning_positions) / len(closed_positions) * 100
            if closed_positions
            else 0
        )

        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')

        avg_win = total_wins / len(winning_positions) if winning_positions else 0
        avg_loss = total_losses / len(losing_positions) if losing_positions else 0

        return {
            "total_realized_pnl_usd": round(total_realized_pnl, 2),
            "win_rate_percent": round(win_rate, 2),
            "total_closed_positions": len(closed_positions),
            "total_open_positions": len(open_positions),
            "winning_positions": len(winning_positions),
            "losing_positions": len(losing_positions),
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "Infinity",
            "avg_win_usd": round(avg_win, 2),
            "avg_loss_usd": round(avg_loss, 2),
            "largest_win_usd": round(max((p.realized_pnl for p in winning_positions), default=0), 2),
            "largest_loss_usd": round(abs(min((p.realized_pnl for p in losing_positions), default=0)), 2),
        }

    def _calculate_market_breakdown(
        self, trades: List[Trade], positions: Dict[str, MarketPosition]
    ) -> List[Dict[str, Any]]:
        """Calculate breakdown by market."""
        market_data: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"trades": 0, "volume": 0, "pnl": 0, "title": "", "resolved": False}
        )

        for trade in trades:
            market_data[trade.condition_id]["trades"] += 1
            market_data[trade.condition_id]["volume"] += float(trade.size)
            market_data[trade.condition_id]["title"] = trade.title

        for key, pos in positions.items():
            condition_id = pos.condition_id
            market_data[condition_id]["pnl"] += pos.realized_pnl
            market_data[condition_id]["resolved"] = pos.resolved

        result = []
        for condition_id, data in market_data.items():
            result.append({
                "condition_id": condition_id,
                "title": data["title"],
                "trades_count": data["trades"],
                "volume_usd": round(data["volume"], 2),
                "realized_pnl_usd": round(data["pnl"], 2),
                "resolved": data["resolved"],
            })

        return sorted(result, key=lambda x: x["volume_usd"], reverse=True)

    def _calculate_time_analysis(self, trades: List[Trade]) -> Dict[str, Any]:
        """Analyze trading patterns over time."""
        if not trades:
            return {}

        trades_by_day: Dict[str, int] = defaultdict(int)
        volume_by_day: Dict[str, float] = defaultdict(float)

        for trade in trades:
            day = trade.datetime.strftime("%Y-%m-%d")
            trades_by_day[day] += 1
            volume_by_day[day] += float(trade.total_value)

        active_days = len(trades_by_day)
        avg_trades_per_day = len(trades) / active_days if active_days > 0 else 0
        avg_volume_per_day = sum(volume_by_day.values()) / active_days if active_days > 0 else 0

        most_active_day = max(trades_by_day.items(), key=lambda x: x[1]) if trades_by_day else ("N/A", 0)

        return {
            "active_trading_days": active_days,
            "avg_trades_per_active_day": round(avg_trades_per_day, 2),
            "avg_volume_per_active_day_usd": round(avg_volume_per_day, 2),
            "most_active_day": most_active_day[0],
            "most_active_day_trades": most_active_day[1],
        }

    def _calculate_risk_metrics(self, positions: Dict[str, MarketPosition]) -> Dict[str, Any]:
        """Calculate risk-related metrics."""
        closed_positions = [p for p in positions.values() if p.is_closed]

        if not closed_positions:
            return {
                "max_drawdown_usd": 0,
                "avg_position_size_usd": 0,
                "position_size_std_dev": 0,
            }

        pnls = [p.realized_pnl for p in closed_positions]
        position_sizes = [p.total_buy_cost for p in closed_positions]

        cumulative_pnl = []
        running_pnl = 0
        for pnl in pnls:
            running_pnl += pnl
            cumulative_pnl.append(running_pnl)

        peak = cumulative_pnl[0]
        max_drawdown = 0
        for value in cumulative_pnl:
            if value > peak:
                peak = value
            drawdown = peak - value
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        avg_position_size = sum(position_sizes) / len(position_sizes) if position_sizes else 0

        if len(position_sizes) > 1:
            mean = avg_position_size
            variance = sum((x - mean) ** 2 for x in position_sizes) / len(position_sizes)
            std_dev = variance ** 0.5
        else:
            std_dev = 0

        return {
            "max_drawdown_usd": round(max_drawdown, 2),
            "avg_position_size_usd": round(avg_position_size, 2),
            "position_size_std_dev_usd": round(std_dev, 2),
        }
