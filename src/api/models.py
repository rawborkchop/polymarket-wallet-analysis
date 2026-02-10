from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Union
from enum import Enum


class TradeSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class ActivityType(Enum):
    TRADE = "TRADE"
    REDEEM = "REDEEM"
    SPLIT = "SPLIT"
    MERGE = "MERGE"


def to_decimal(value, default: str = "0") -> Decimal:
    """
    Safely convert a value to Decimal, avoiding float precision issues.

    Always converts through string representation to preserve precision.
    """
    if value is None:
        return Decimal(default)
    # Convert through string to avoid float precision issues
    return Decimal(str(value))


@dataclass
class Trade:
    """Immutable data model representing a Polymarket trade."""

    proxy_wallet: str
    side: TradeSide
    asset: str
    condition_id: str
    size: Decimal
    price: Decimal
    timestamp: int
    title: str
    slug: str
    outcome: str
    outcome_index: int
    transaction_hash: str
    icon: Optional[str] = None
    event_slug: Optional[str] = None
    name: Optional[str] = None
    pseudonym: Optional[str] = None
    bio: Optional[str] = None
    profile_image: Optional[str] = None

    @property
    def datetime(self) -> datetime:
        """Convert timestamp to datetime."""
        return datetime.fromtimestamp(self.timestamp)

    @property
    def total_value(self) -> Decimal:
        """Calculate total value of the trade (size * price)."""
        return self.size * self.price

    @property
    def is_buy(self) -> bool:
        return self.side == TradeSide.BUY

    @property
    def is_sell(self) -> bool:
        return self.side == TradeSide.SELL

    @classmethod
    def from_api_response(cls, data: dict) -> "Trade":
        """Factory method to create a Trade from API response."""
        return cls(
            proxy_wallet=data.get("proxyWallet", ""),
            side=TradeSide(data.get("side", "BUY")),
            asset=data.get("asset", ""),
            condition_id=data.get("conditionId", ""),
            size=to_decimal(data.get("size", 0)),
            price=to_decimal(data.get("price", 0)),
            timestamp=int(data.get("timestamp", 0)),
            title=data.get("title", ""),
            slug=data.get("slug", ""),
            outcome=data.get("outcome", ""),
            outcome_index=int(data.get("outcomeIndex", 0)),
            transaction_hash=data.get("transactionHash", ""),
            icon=data.get("icon"),
            event_slug=data.get("eventSlug"),
            name=data.get("name"),
            pseudonym=data.get("pseudonym"),
            bio=data.get("bio"),
            profile_image=data.get("profileImage"),
        )

    def to_dict(self) -> dict:
        """Convert Trade to dictionary for export."""
        return {
            "proxy_wallet": self.proxy_wallet,
            "side": self.side.value,
            "asset": self.asset,
            "condition_id": self.condition_id,
            "size": float(self.size),  # Convert to float for JSON serialization
            "price": float(self.price),
            "timestamp": self.timestamp,
            "datetime": self.datetime.isoformat(),
            "title": self.title,
            "slug": self.slug,
            "outcome": self.outcome,
            "outcome_index": self.outcome_index,
            "transaction_hash": self.transaction_hash,
            "total_value": float(self.total_value),
            "event_slug": self.event_slug,
        }
