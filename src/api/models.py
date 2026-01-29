from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class TradeSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class ActivityType(Enum):
    TRADE = "TRADE"
    REDEEM = "REDEEM"
    SPLIT = "SPLIT"
    MERGE = "MERGE"


@dataclass
class Trade:
    """Immutable data model representing a Polymarket trade."""

    proxy_wallet: str
    side: TradeSide
    asset: str
    condition_id: str
    size: float
    price: float
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
    def total_value(self) -> float:
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
            size=float(data.get("size", 0)),
            price=float(data.get("price", 0)),
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
            "size": self.size,
            "price": self.price,
            "timestamp": self.timestamp,
            "datetime": self.datetime.isoformat(),
            "title": self.title,
            "slug": self.slug,
            "outcome": self.outcome,
            "outcome_index": self.outcome_index,
            "transaction_hash": self.transaction_hash,
            "total_value": self.total_value,
            "event_slug": self.event_slug,
        }

    @classmethod
    def from_redeem(cls, data: dict) -> "Trade":
        """
        Create a Trade from a REDEEM activity.

        REDEEM = selling winning tokens at $1 each.
        """
        return cls(
            proxy_wallet=data.get("proxyWallet", ""),
            side=TradeSide.SELL,  # REDEEM is like selling at $1
            asset=data.get("asset", ""),
            condition_id=data.get("conditionId", ""),
            size=float(data.get("size", 0)),
            price=1.0,  # Winning tokens redeem for $1
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
