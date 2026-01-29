from abc import ABC, abstractmethod
from typing import List, Dict, Any

from src.api.models import Trade


class IAnalyzer(ABC):
    """Interface for trade analysis (Liskov Substitution Principle)."""

    @abstractmethod
    def analyze(self, trades: List[Trade]) -> Dict[str, Any]:
        """Perform analysis on the given trades and return results."""
        pass
