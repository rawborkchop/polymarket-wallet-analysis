from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from src.api.models import Trade, TradeSide
from src.interfaces.analyzer import IAnalyzer


@dataclass
class CopyTradeResult:
    """Result of a simulated copy trade."""

    original_trade: Trade
    copy_price: float
    slippage_percent: float
    original_pnl_contribution: float
    copy_pnl_contribution: float
    pnl_difference: float


@dataclass
class CopyTradingScenario:
    """Results for a specific slippage scenario."""

    slippage_value: float  # Percentage or points depending on mode
    slippage_mode: str  # "percentage" or "points"
    total_trades_copied: int
    total_volume_usd: float
    estimated_pnl_usd: float
    original_pnl_usd: float
    pnl_difference_usd: float
    pnl_difference_percent: float
    trades_breakdown: List[CopyTradeResult]


class CopyTradingAnalyzer(IAnalyzer):
    """
    Analyzer for simulating copy trading scenarios.

    Simulates what would happen if you copied a trader's trades
    with different price slippages.

    Supports two slippage modes:
    - percentage: 1% slippage = buy at price * 1.01, sell at price * 0.99
    - points: 1 point slippage = buy at price + 0.01, sell at price - 0.01

    Uses market resolution data to calculate P&L for positions held until
    market resolution (not just explicit buy/sell pairs).
    """

    DEFAULT_SLIPPAGES_PERCENT = [0.5, 1.0, 2.0, 3.0, 5.0]
    DEFAULT_SLIPPAGES_POINTS = [0.01, 0.02, 0.03, 0.05, 0.10]  # In price points (cents)

    def __init__(
        self,
        slippage_values: List[float] = None,
        use_percentage: bool = True,
    ):
        """
        Initialize the analyzer.

        Args:
            slippage_values: List of slippage values to test
            use_percentage: If True, slippage is percentage-based (e.g., 1.0 = 1%)
                           If False, slippage is points-based (e.g., 0.01 = 1 cent)
        """
        self._use_percentage = use_percentage
        if slippage_values:
            self._slippages = slippage_values
        else:
            self._slippages = (
                self.DEFAULT_SLIPPAGES_PERCENT if use_percentage
                else self.DEFAULT_SLIPPAGES_POINTS
            )
        self._resolutions: Dict[str, dict] = {}

    def analyze(
        self,
        trades: List[Trade],
        resolutions: Optional[Dict[str, dict]] = None,
        cash_flow: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze copy trading potential with various slippage scenarios.

        Args:
            trades: List of trades to analyze
            resolutions: Market resolution data (from GammaClient).
            cash_flow: Cash flow data for P&L calculation.
                       Contains buy_cost, sell_revenue, redeem_revenue,
                       split_cost, merge_revenue, and total_pnl.

        Slippage only affects BUY and SELL trades:
        - For BUY: You buy at a higher price (original_price * (1 + slippage))
        - For SELL: You sell at a lower price (original_price * (1 - slippage))
        - REDEEM, SPLIT, MERGE: No slippage (contract-level operations)

        Original trader P&L is calculated from trades/activities in the period.
        Copy P&L estimates slippage impact on that period's activity.
        """
        if not trades:
            return {"scenarios": [], "recommendation": None}

        self._resolutions = resolutions or {}
        self._cash_flow = cash_flow or {}

        scenarios = []
        for slippage in self._slippages:
            scenario = self._simulate_scenario_cashflow(trades, slippage)
            scenarios.append(scenario)

        return {
            "scenarios": [self._scenario_to_dict(s) for s in scenarios],
            "comparison_table": self._create_comparison_table(scenarios),
            "recommendation": self._generate_recommendation(scenarios),
            "market_by_market": self._analyze_by_market(trades, scenarios),
        }

    def _simulate_scenario_cashflow(
        self, trades: List[Trade], slippage_value: float
    ) -> CopyTradingScenario:
        """
        Simulate copy trading using Cash Flow method.

        Slippage only affects BUY/SELL trades, not REDEEM/SPLIT/MERGE.
        P&L = (Sell + Redeem + Merge + Reward) - (Buy + Split)

        Two slippage modes:
        - Percentage: slippage_value = 1.0 means 1% slippage
          BUY cost *= (1 + 0.01), SELL revenue *= (1 - 0.01)
        - Points: slippage_value = 0.01 means 1 cent drift per token
          BUY cost += tokens * 0.01, SELL revenue -= tokens * 0.01
        """
        # Get original cash flow values
        orig_buy_cost = self._cash_flow.get("buy_cost", 0)
        orig_sell_revenue = self._cash_flow.get("sell_revenue", 0)
        redeem_revenue = self._cash_flow.get("redeem_revenue", 0)
        split_cost = self._cash_flow.get("split_cost", 0)
        merge_revenue = self._cash_flow.get("merge_revenue", 0)
        reward_revenue = self._cash_flow.get("reward_revenue", 0)
        conversion_revenue = self._cash_flow.get("conversion_revenue", 0)

        if self._use_percentage:
            # Percentage mode: slippage as % of price
            slippage_factor = slippage_value / 100
            copy_buy_cost = orig_buy_cost * (1 + slippage_factor)
            copy_sell_revenue = orig_sell_revenue * (1 - slippage_factor)
        else:
            # Points mode: fixed price drift per token
            # If trader buys at 0.50, you buy at 0.50 + slippage_value
            buy_volume_tokens = self._cash_flow.get("buy_volume_tokens", 0)
            sell_volume_tokens = self._cash_flow.get("sell_volume_tokens", 0)
            copy_buy_cost = orig_buy_cost + (buy_volume_tokens * slippage_value)
            copy_sell_revenue = orig_sell_revenue - (sell_volume_tokens * slippage_value)

        # REDEEM, SPLIT, MERGE, REWARD: no slippage (contract-level operations)
        # These happen at fixed rates, not market execution

        # Calculate P&L for the period's activity (from activity API)
        period_original_pnl = (orig_sell_revenue + redeem_revenue + merge_revenue + reward_revenue + conversion_revenue) - (orig_buy_cost + split_cost)
        period_copy_pnl = (copy_sell_revenue + redeem_revenue + merge_revenue + reward_revenue + conversion_revenue) - (copy_buy_cost + split_cost)

        # Use period P&L calculated from trades and activities
        original_pnl = period_original_pnl
        copy_pnl = period_copy_pnl

        total_volume = float(sum(t.size for t in trades))
        pnl_diff = copy_pnl - original_pnl

        return CopyTradingScenario(
            slippage_value=slippage_value,
            slippage_mode="percentage" if self._use_percentage else "points",
            total_trades_copied=len(trades),
            total_volume_usd=total_volume,
            estimated_pnl_usd=copy_pnl,
            original_pnl_usd=original_pnl,
            pnl_difference_usd=pnl_diff,
            pnl_difference_percent=(pnl_diff / abs(original_pnl) * 100) if original_pnl != 0 else 0,
            trades_breakdown=[],  # Simplified for cash flow method
        )

    def _simulate_scenario(
        self, trades: List[Trade], slippage_percent: float
    ) -> CopyTradingScenario:
        """Simulate copy trading with given slippage."""
        results: List[CopyTradeResult] = []
        slippage_factor = slippage_percent / 100

        market_positions: Dict[str, Dict[str, Any]] = {}

        for trade in trades:
            key = f"{trade.condition_id}_{trade.outcome}"

            if key not in market_positions:
                market_positions[key] = {
                    "condition_id": trade.condition_id,
                    "outcome": trade.outcome,
                    "original_buys": [],
                    "original_sells": [],
                    "copy_buys": [],
                    "copy_sells": [],
                }

            trade_price = float(trade.price)
            trade_size = float(trade.size)

            if trade.is_buy:
                copy_price = min(trade_price * (1 + slippage_factor), 0.99)
                market_positions[key]["original_buys"].append(
                    {"size": trade_size, "price": trade_price}
                )
                market_positions[key]["copy_buys"].append(
                    {"size": trade_size, "price": copy_price}
                )
            else:
                copy_price = max(trade_price * (1 - slippage_factor), 0.01)
                market_positions[key]["original_sells"].append(
                    {"size": trade_size, "price": trade_price}
                )
                market_positions[key]["copy_sells"].append(
                    {"size": trade_size, "price": copy_price}
                )

            results.append(
                CopyTradeResult(
                    original_trade=trade,
                    copy_price=copy_price,
                    slippage_percent=slippage_percent,
                    original_pnl_contribution=0,
                    copy_pnl_contribution=0,
                    pnl_difference=0,
                )
            )

        original_pnl = 0.0
        copy_pnl = 0.0

        for key, pos in market_positions.items():
            orig_buy_cost = sum(b["size"] * b["price"] for b in pos["original_buys"])
            orig_sell_rev = sum(s["size"] * s["price"] for s in pos["original_sells"])

            copy_buy_cost = sum(b["size"] * b["price"] for b in pos["copy_buys"])
            copy_sell_rev = sum(s["size"] * s["price"] for s in pos["copy_sells"])

            orig_bought = sum(b["size"] for b in pos["original_buys"])
            orig_sold = sum(s["size"] for s in pos["original_sells"])

            condition_id = pos["condition_id"]
            outcome = pos["outcome"]
            resolution = self._resolutions.get(condition_id, {})
            is_resolved = resolution.get("resolved", False)

            # Check if position is "closed" (consistent with analytics)
            # A position is closed if: market resolved OR fully sold
            remaining_size = orig_bought - orig_sold
            is_closed = is_resolved or abs(remaining_size) < 0.0001

            if not is_closed:
                # Skip open positions (not yet realized P&L)
                continue

            # P&L from explicit sells
            sold_size = min(orig_bought, orig_sold)
            if sold_size > 0:
                orig_avg_buy = orig_buy_cost / orig_bought if orig_bought > 0 else 0
                orig_avg_sell = orig_sell_rev / orig_sold if orig_sold > 0 else 0
                original_pnl += sold_size * (orig_avg_sell - orig_avg_buy)

                copy_avg_buy = copy_buy_cost / orig_bought if orig_bought > 0 else 0
                copy_avg_sell = copy_sell_rev / orig_sold if orig_sold > 0 else 0
                copy_pnl += sold_size * (copy_avg_sell - copy_avg_buy)

            # P&L from market resolution (for remaining position)
            if remaining_size > 0 and is_resolved:
                winning_outcome = resolution.get("winning_outcome")
                won = (winning_outcome == outcome)

                orig_avg_buy = orig_buy_cost / orig_bought if orig_bought > 0 else 0
                copy_avg_buy = copy_buy_cost / orig_bought if orig_bought > 0 else 0

                if won:
                    # Won: tokens redeem for $1
                    original_pnl += remaining_size * (1.0 - orig_avg_buy)
                    copy_pnl += remaining_size * (1.0 - copy_avg_buy)
                else:
                    # Lost: tokens worth $0
                    original_pnl += remaining_size * (0.0 - orig_avg_buy)
                    copy_pnl += remaining_size * (0.0 - copy_avg_buy)

        total_volume = float(sum(t.size for t in trades))
        pnl_diff = copy_pnl - original_pnl

        return CopyTradingScenario(
            slippage_value=slippage_percent,
            slippage_mode="percentage",  # Old method always uses percentage
            total_trades_copied=len(trades),
            total_volume_usd=total_volume,
            estimated_pnl_usd=copy_pnl,
            original_pnl_usd=original_pnl,
            pnl_difference_usd=pnl_diff,
            pnl_difference_percent=(pnl_diff / abs(original_pnl) * 100) if original_pnl != 0 else 0,
            trades_breakdown=results,
        )

    def _scenario_to_dict(self, scenario: CopyTradingScenario) -> Dict[str, Any]:
        """Convert scenario to dictionary."""
        return {
            "slippage_value": scenario.slippage_value,
            "slippage_mode": scenario.slippage_mode,
            "total_trades_copied": scenario.total_trades_copied,
            "total_volume_usd": round(scenario.total_volume_usd, 2),
            "original_pnl_usd": round(scenario.original_pnl_usd, 2),
            "estimated_copy_pnl_usd": round(scenario.estimated_pnl_usd, 2),
            "pnl_difference_usd": round(scenario.pnl_difference_usd, 2),
            "pnl_difference_percent": round(scenario.pnl_difference_percent, 2),
            "profitable": scenario.estimated_pnl_usd > 0,
        }

    def _create_comparison_table(
        self, scenarios: List[CopyTradingScenario]
    ) -> List[Dict[str, Any]]:
        """Create a comparison table of all scenarios."""
        return [
            {
                "slippage": f"{s.slippage_value}%" if s.slippage_mode == "percentage" else f"{s.slippage_value} pts",
                "original_pnl": f"${s.original_pnl_usd:,.2f}",
                "copy_pnl": f"${s.estimated_pnl_usd:,.2f}",
                "difference": f"${s.pnl_difference_usd:,.2f}",
                "impact": f"{s.pnl_difference_percent:+.2f}%",
                "verdict": "Profitable" if s.estimated_pnl_usd > 0 else "Loss",
            }
            for s in scenarios
        ]

    def _generate_recommendation(
        self, scenarios: List[CopyTradingScenario]
    ) -> Dict[str, Any]:
        """Generate recommendation based on analysis."""
        profitable_scenarios = [s for s in scenarios if s.estimated_pnl_usd > 0]
        is_percentage = self._use_percentage
        unit = "%" if is_percentage else " pts"

        if not profitable_scenarios:
            max_slippage = 0
            recommendation = "NOT_RECOMMENDED"
            reason = "Copy trading this wallet is not profitable at any tested slippage level."
        else:
            max_profitable = max(profitable_scenarios, key=lambda s: s.slippage_value)
            max_slippage = max_profitable.slippage_value

            # Different thresholds for percentage vs points mode
            if is_percentage:
                if max_slippage >= 2.0:
                    recommendation = "RECOMMENDED"
                    reason = f"Copy trading remains profitable up to {max_slippage}{unit} slippage."
                elif max_slippage >= 1.0:
                    recommendation = "MODERATE"
                    reason = f"Copy trading is profitable but sensitive to slippage (max {max_slippage}{unit})."
                else:
                    recommendation = "RISKY"
                    reason = f"Copy trading only profitable at very low slippage ({max_slippage}{unit}). High execution risk."
            else:
                # Points mode: 0.02 = 2 cents is reasonable, 0.05 = 5 cents is good
                if max_slippage >= 0.05:
                    recommendation = "RECOMMENDED"
                    reason = f"Copy trading remains profitable up to {max_slippage}{unit} slippage."
                elif max_slippage >= 0.02:
                    recommendation = "MODERATE"
                    reason = f"Copy trading is profitable but sensitive to slippage (max {max_slippage}{unit})."
                else:
                    recommendation = "RISKY"
                    reason = f"Copy trading only profitable at very low slippage ({max_slippage}{unit}). High execution risk."

        breakeven_scenario = min(
            scenarios,
            key=lambda s: abs(s.estimated_pnl_usd),
        )

        return {
            "verdict": recommendation,
            "reason": reason,
            "max_profitable_slippage": max_slippage,
            "max_profitable_slippage_unit": "percent" if is_percentage else "points",
            "breakeven_slippage_approx": round(breakeven_scenario.slippage_value, 4),
            "original_trader_pnl_usd": round(scenarios[0].original_pnl_usd, 2),
        }

    def _analyze_by_market(
        self, trades: List[Trade], scenarios: List[CopyTradingScenario]
    ) -> List[Dict[str, Any]]:
        """Analyze copy trading viability by individual market."""
        markets: Dict[str, List[Trade]] = {}
        for trade in trades:
            if trade.condition_id not in markets:
                markets[trade.condition_id] = []
            markets[trade.condition_id].append(trade)

        results = []
        for condition_id, market_trades in markets.items():
            if len(market_trades) < 2:
                continue

            title = market_trades[0].title
            scenario_1pct = self._simulate_scenario(market_trades, 1.0)
            scenario_2pct = self._simulate_scenario(market_trades, 2.0)

            results.append({
                "market_title": title,
                "condition_id": condition_id,
                "total_trades": len(market_trades),
                "original_pnl_usd": round(scenario_1pct.original_pnl_usd, 2),
                "copy_pnl_1pct_slippage": round(scenario_1pct.estimated_pnl_usd, 2),
                "copy_pnl_2pct_slippage": round(scenario_2pct.estimated_pnl_usd, 2),
                "recommended_to_copy": scenario_1pct.estimated_pnl_usd > 0,
            })

        return sorted(results, key=lambda x: x["original_pnl_usd"], reverse=True)
