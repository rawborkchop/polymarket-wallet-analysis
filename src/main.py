#!/usr/bin/env python3
"""
Polymarket Wallet Analysis Tool

Fetches trades from a Polymarket wallet, stores in SQLite database,
and provides comprehensive trading analysis including copy trading simulation.

Usage:
    python -m src.main <wallet_address> [--output-dir <dir>]

Example:
    python -m src.main 0x1234567890abcdef1234567890abcdef12345678
"""

import os
import sys

# Setup Django before other imports
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')

import django
django.setup()

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from src.api.polymarket_client import PolymarketClient
from src.services.trade_service import TradeService
from src.services.analytics_service import AnalyticsService
from src.services.copy_trading_analyzer import CopyTradingAnalyzer
from src.exporters.csv_exporter import CsvExporter
from wallet_analysis.services import DatabaseService


class WalletAnalyzer:
    """
    Main application orchestrator.

    Coordinates between services following Dependency Inversion Principle.
    Data is persisted to SQLite database via Django ORM.
    """

    def __init__(
        self,
        trade_service: TradeService,
        analytics_service: AnalyticsService,
        copy_trading_analyzer: CopyTradingAnalyzer,
        csv_exporter: CsvExporter,
        db_service: Optional[DatabaseService] = None,
    ):
        self._trade_service = trade_service
        self._analytics_service = analytics_service
        self._copy_trading_analyzer = copy_trading_analyzer
        self._csv_exporter = csv_exporter
        self._db_service = db_service or DatabaseService()

    def analyze_wallet(
        self, wallet_address: str, output_dir: Path, start_hours_ago: int = 6, end_hours_ago: int = 5
    ) -> Dict[str, Any]:
        """
        Perform complete wallet analysis.

        Args:
            wallet_address: The 0x-prefixed wallet address
            output_dir: Directory for output files
            start_hours_ago: Start of window (hours ago)
            end_hours_ago: End of window (hours ago)

        Returns:
            Dictionary with all analysis results
        """
        print(f"\n{'='*60}")
        print(f"Polymarket Wallet Analysis")
        print(f"{'='*60}")
        print(f"Wallet: {wallet_address}")
        print(f"Output: {output_dir}")
        print(f"Period: {start_hours_ago} to {end_hours_ago} hours ago")
        print(f"{'='*60}\n")

        now = datetime.now().timestamp()
        after_timestamp = int(now - (start_hours_ago * 60 * 60))
        before_timestamp = int(now - (end_hours_ago * 60 * 60))

        # Get or create wallet in database
        wallet_db = self._db_service.get_or_create_wallet(wallet_address)

        print("[1/6] Fetching all activity from Polymarket API...")
        activity_result = self._trade_service.get_all_activity(
            wallet_address, after_timestamp, before_timestamp
        )

        trades = activity_result["trades"]
        stats = activity_result["stats"]
        raw_activity = activity_result.get("raw_activity", {})

        if not trades:
            print("No activity found for this wallet.")
            return {"error": "No activity found"}

        print(f"      Found {len(trades)} activities: "
              f"{stats['trade_count']} trades, {stats['redeem_count']} redeems, "
              f"{stats['split_count']} splits, {stats['merge_count']} merges")

        print("[2/6] Saving to database...")
        trades_sorted = self._trade_service.sort_by_timestamp(trades, descending=False)
        trades_inserted = self._db_service.save_trades(wallet_db, trades_sorted)
        activity_counts = self._db_service.save_activities(wallet_db, raw_activity)
        print(f"      Saved {trades_inserted} new trades to database")

        # Also export to CSV for backwards compatibility
        trades_path = output_dir / "trades.csv"
        self._csv_exporter.export(trades_sorted, trades_path)
        print(f"      CSV backup: {trades_path}")

        print("[3/6] Performing trading analytics...")
        analytics = self._analytics_service.analyze(trades)

        # Get cash flow from activity
        cash_flow = activity_result.get("cash_flow", {})
        analytics["cash_flow_pnl"] = cash_flow

        analytics_files = self._csv_exporter.export_analysis(analytics, output_dir / "analytics")
        print(f"      Generated {len(analytics_files)} analytics files.")

        print("[4/6] Running copy trading simulation...")
        # Pass resolutions and cash_flow from analytics to avoid duplicate API calls
        resolutions = analytics.pop("_resolutions", {})
        copy_analysis = self._copy_trading_analyzer.analyze(trades, resolutions, cash_flow)
        copy_files = self._csv_exporter.export_copy_trading_analysis(
            copy_analysis, output_dir / "copy_trading"
        )
        print(f"      Generated {len(copy_files)} copy trading files.")

        print("[5/6] Saving analysis results to database...")
        # Save market resolutions
        self._db_service.save_market_resolutions(resolutions)

        # Save analysis run with all metrics
        analysis_run = self._db_service.save_analysis_run(
            wallet=wallet_db,
            summary=analytics.get("summary", {}),
            cash_flow=cash_flow,
            performance=analytics.get("performance", {}),
            period_start_hours=start_hours_ago,
            period_end_hours=end_hours_ago,
        )

        # Save copy trading scenarios
        scenarios = copy_analysis.get("scenarios", [])
        self._db_service.save_copy_trading_scenarios(analysis_run, scenarios)
        print(f"      Saved analysis run #{analysis_run.id} to database")

        print("[6/6] Generating summary report...")
        report = self._generate_report(analytics, copy_analysis)
        report_path = output_dir / "report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"      Saved to: {report_path}")

        self._print_summary(analytics, copy_analysis)

        return {
            "trades_count": len(trades),
            "analytics": analytics,
            "copy_trading": copy_analysis,
            "output_files": {
                "trades": str(trades_path),
                "analytics": {k: str(v) for k, v in analytics_files.items()},
                "copy_trading": {k: str(v) for k, v in copy_files.items()},
                "report": str(report_path),
            },
        }

    def _generate_report(
        self, analytics: Dict[str, Any], copy_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate combined analysis report."""
        return {
            "generated_at": datetime.now().isoformat(),
            "summary": analytics.get("summary", {}),
            "performance": analytics.get("performance", {}),
            "time_analysis": analytics.get("time_analysis", {}),
            "risk_metrics": analytics.get("risk_metrics", {}),
            "copy_trading_recommendation": copy_analysis.get("recommendation", {}),
            "copy_trading_scenarios": copy_analysis.get("scenarios", []),
        }

    def _print_summary(
        self, analytics: Dict[str, Any], copy_analysis: Dict[str, Any]
    ) -> None:
        """Print analysis summary to console."""
        print(f"\n{'='*60}")
        print("ANALYSIS SUMMARY")
        print(f"{'='*60}\n")

        # Cash flow P&L calculated from trades and activities
        cash_flow = analytics.get("cash_flow_pnl", {})
        if cash_flow:
            total_pnl = cash_flow.get('total_pnl', 0)
            print("PERIOD P&L (calculated from trades):")
            print(f"  Total P&L:           ${total_pnl:,.2f}")
            print(f"  Buy Cost:            ${cash_flow.get('buy_cost', 0):,.2f}")
            print(f"  Sell Revenue:        ${cash_flow.get('sell_revenue', 0):,.2f}")
            print(f"  Redeem Revenue:      ${cash_flow.get('redeem_revenue', 0):,.2f}")
            print(f"  Split Cost:          ${cash_flow.get('split_cost', 0):,.2f}")
            print(f"  Merge Revenue:       ${cash_flow.get('merge_revenue', 0):,.2f}")
            print(f"  Reward Revenue:      ${cash_flow.get('reward_revenue', 0):,.2f}")
            print()

        summary = analytics.get("summary", {})
        print("Trading Activity:")
        print(f"  Total Trades:        {summary.get('total_trades', 0)}")
        print(f"  Buys/Sells:          {summary.get('total_buys', 0)} / {summary.get('total_sells', 0)}")
        print(f"  Total Volume:        ${summary.get('total_volume_usd', 0):,.2f}")
        print(f"  Unique Markets:      {summary.get('unique_markets', 0)}")
        print(f"  Avg Trade Size:      ${summary.get('avg_trade_size_usd', 0):,.2f}")

        perf = analytics.get("performance", {})
        print("\nPosition-Based Metrics:")
        print(f"  Realized P&L:        ${perf.get('total_realized_pnl_usd', 0):,.2f}")
        print(f"  Win Rate:            {perf.get('win_rate_percent', 0):.1f}%")
        print(f"  Profit Factor:       {perf.get('profit_factor', 'N/A')}")
        print(f"  Closed Positions:    {perf.get('total_closed_positions', 0)}")
        print(f"  Open Positions:      {perf.get('total_open_positions', 0)}")
        print(f"  Largest Win:         ${perf.get('largest_win_usd', 0):,.2f}")
        print(f"  Largest Loss:        ${perf.get('largest_loss_usd', 0):,.2f}")

        risk = analytics.get("risk_metrics", {})
        print("\nRisk Metrics:")
        print(f"  Max Drawdown:        ${risk.get('max_drawdown_usd', 0):,.2f}")
        print(f"  Avg Position Size:   ${risk.get('avg_position_size_usd', 0):,.2f}")

        print("\n" + "-"*60)
        print("COPY TRADING ANALYSIS")
        print("-"*60 + "\n")

        comparison = copy_analysis.get("comparison_table", [])
        if comparison:
            print("Slippage Scenarios:")
            print(f"{'Slippage':<12} {'Original P&L':<15} {'Copy P&L':<15} {'Impact':<12} {'Verdict':<10}")
            print("-" * 64)
            for row in comparison:
                print(f"{row['slippage']:<12} {row['original_pnl']:<15} {row['copy_pnl']:<15} {row['impact']:<12} {row['verdict']:<10}")

        rec = copy_analysis.get("recommendation", {})
        if rec:
            print(f"\nRecommendation: {rec.get('verdict', 'N/A')}")
            print(f"Reason: {rec.get('reason', 'N/A')}")
            slippage_unit = rec.get('max_profitable_slippage_unit', 'percent')
            unit_symbol = "%" if slippage_unit == "percent" else " pts"
            print(f"Max Profitable Slippage: {rec.get('max_profitable_slippage', 0)}{unit_symbol}")

        print(f"\n{'='*60}\n")


def create_analyzer(
    use_percentage_slippage: bool = True,
    slippage_values: list = None,
) -> WalletAnalyzer:
    """Factory function to create WalletAnalyzer with dependencies."""
    client = PolymarketClient()
    trade_service = TradeService(client)
    analytics_service = AnalyticsService()
    copy_trading_analyzer = CopyTradingAnalyzer(
        slippage_values=slippage_values,
        use_percentage=use_percentage_slippage,
    )
    csv_exporter = CsvExporter()

    return WalletAnalyzer(
        trade_service=trade_service,
        analytics_service=analytics_service,
        copy_trading_analyzer=copy_trading_analyzer,
        csv_exporter=csv_exporter,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a Polymarket wallet's trading activity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main 0x1234567890abcdef1234567890abcdef12345678
  python -m src.main 0x1234...5678 --output-dir ./my_analysis
        """,
    )
    parser.add_argument(
        "wallet_address",
        help="Polymarket wallet address (0x-prefixed, 42 characters)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("./output"),
        help="Output directory for CSV files and reports (default: ./output)",
    )
    parser.add_argument(
        "--start-hours-ago",
        type=int,
        default=6,
        help="Start of analysis window in hours ago (default: 6)",
    )
    parser.add_argument(
        "--end-hours-ago",
        type=int,
        default=5,
        help="End of analysis window in hours ago (default: 5, must be > 2 for resolved markets)",
    )
    parser.add_argument(
        "--slippage-mode",
        choices=["percentage", "points"],
        default="percentage",
        help="Slippage calculation mode: 'percentage' (1.0 = 1%%) or 'points' (0.01 = 1 cent drift per token)",
    )
    parser.add_argument(
        "--slippage-values",
        type=str,
        default=None,
        help="Comma-separated slippage values to test (e.g., '0.5,1.0,2.0' for %% or '0.01,0.02,0.05' for points)",
    )

    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir / f"analysis_{args.wallet_address[:10]}_{timestamp}"

    # Parse slippage configuration
    use_percentage = args.slippage_mode == "percentage"
    slippage_values = None
    if args.slippage_values:
        slippage_values = [float(v.strip()) for v in args.slippage_values.split(",")]

    try:
        analyzer = create_analyzer(
            use_percentage_slippage=use_percentage,
            slippage_values=slippage_values,
        )
        result = analyzer.analyze_wallet(
            args.wallet_address, output_dir, args.start_hours_ago, args.end_hours_ago
        )

        if "error" in result:
            sys.exit(1)

        print("Analysis completed successfully!")
        sys.exit(0)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
