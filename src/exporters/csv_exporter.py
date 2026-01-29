import csv
from pathlib import Path
from typing import List, Any, Dict

import pandas as pd

from src.api.models import Trade
from src.interfaces.exporter import IExporter


class CsvExporter(IExporter):
    """
    CSV exporter for trade data.

    Single Responsibility: Only handles CSV export logic.
    Open/Closed: New export formats can be added by creating new classes.
    """

    def export(self, data: List[Any], output_path: Path) -> None:
        """Export data to CSV file."""
        if not data:
            raise ValueError("No data to export")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(data[0], Trade):
            self._export_trades(data, output_path)
        elif isinstance(data[0], dict):
            self._export_dicts(data, output_path)
        else:
            raise ValueError(f"Unsupported data type: {type(data[0])}")

    def _export_trades(self, trades: List[Trade], output_path: Path) -> None:
        """Export Trade objects to CSV."""
        records = [trade.to_dict() for trade in trades]
        df = pd.DataFrame(records)
        df.to_csv(output_path, index=False)

    def _export_dicts(self, data: List[Dict], output_path: Path) -> None:
        """Export list of dictionaries to CSV."""
        df = pd.DataFrame(data)
        df.to_csv(output_path, index=False)

    def export_analysis(self, analysis: Dict[str, Any], output_dir: Path) -> Dict[str, Path]:
        """
        Export analysis results to multiple CSV files.

        Returns dict mapping analysis type to file path.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        exported_files = {}

        if "summary" in analysis and analysis["summary"]:
            summary_path = output_dir / "summary.csv"
            df = pd.DataFrame([analysis["summary"]])
            df.to_csv(summary_path, index=False)
            exported_files["summary"] = summary_path

        if "performance" in analysis and analysis["performance"]:
            perf_path = output_dir / "performance.csv"
            df = pd.DataFrame([analysis["performance"]])
            df.to_csv(perf_path, index=False)
            exported_files["performance"] = perf_path

        if "market_breakdown" in analysis and analysis["market_breakdown"]:
            market_path = output_dir / "market_breakdown.csv"
            df = pd.DataFrame(analysis["market_breakdown"])
            df.to_csv(market_path, index=False)
            exported_files["market_breakdown"] = market_path

        if "time_analysis" in analysis and analysis["time_analysis"]:
            time_path = output_dir / "time_analysis.csv"
            df = pd.DataFrame([analysis["time_analysis"]])
            df.to_csv(time_path, index=False)
            exported_files["time_analysis"] = time_path

        if "risk_metrics" in analysis and analysis["risk_metrics"]:
            risk_path = output_dir / "risk_metrics.csv"
            df = pd.DataFrame([analysis["risk_metrics"]])
            df.to_csv(risk_path, index=False)
            exported_files["risk_metrics"] = risk_path

        return exported_files

    def export_copy_trading_analysis(
        self, analysis: Dict[str, Any], output_dir: Path
    ) -> Dict[str, Path]:
        """Export copy trading analysis to CSV files."""
        output_dir.mkdir(parents=True, exist_ok=True)
        exported_files = {}

        if "scenarios" in analysis and analysis["scenarios"]:
            scenarios_path = output_dir / "copy_trading_scenarios.csv"
            df = pd.DataFrame(analysis["scenarios"])
            df.to_csv(scenarios_path, index=False)
            exported_files["scenarios"] = scenarios_path

        if "comparison_table" in analysis and analysis["comparison_table"]:
            comparison_path = output_dir / "copy_trading_comparison.csv"
            df = pd.DataFrame(analysis["comparison_table"])
            df.to_csv(comparison_path, index=False)
            exported_files["comparison_table"] = comparison_path

        if "recommendation" in analysis and analysis["recommendation"]:
            rec_path = output_dir / "copy_trading_recommendation.csv"
            df = pd.DataFrame([analysis["recommendation"]])
            df.to_csv(rec_path, index=False)
            exported_files["recommendation"] = rec_path

        if "market_by_market" in analysis and analysis["market_by_market"]:
            market_path = output_dir / "copy_trading_by_market.csv"
            df = pd.DataFrame(analysis["market_by_market"])
            df.to_csv(market_path, index=False)
            exported_files["market_by_market"] = market_path

        return exported_files
