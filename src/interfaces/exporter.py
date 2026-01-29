from abc import ABC, abstractmethod
from typing import List, Any
from pathlib import Path


class IExporter(ABC):
    """Interface for exporting data (Open/Closed Principle - can add new exporters)."""

    @abstractmethod
    def export(self, data: List[Any], output_path: Path) -> None:
        """Export data to the specified path."""
        pass
