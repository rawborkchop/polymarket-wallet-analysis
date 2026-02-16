"""
Position Tracker — Weighted Average Cost Basis (WACB) engine.

Pure logic, no Django dependencies. Processes trades and activities
chronologically to track per-asset cost basis and realized PnL.

This is the industry-standard method used by Polymarket's Data API,
their PnL subgraph, and all major community tools.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import Dict, List, Tuple, Optional

ZERO = Decimal('0')
ONE = Decimal('1')
HALF = Decimal('0.5')


@dataclass
class PositionState:
    """Per-asset (per-token) position state."""
    asset: str
    market_id: Optional[str] = None
    outcome: str = ''
    quantity: Decimal = ZERO
    avg_price: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    total_bought: Decimal = ZERO
    total_sold: Decimal = ZERO
    total_cost: Decimal = ZERO
    total_revenue: Decimal = ZERO


@dataclass
class RealizedPnLEvent:
    """Emitted when realized PnL is generated (sell, redeem, merge, reward, conversion)."""
    timestamp: int
    datetime: datetime
    asset: str
    market_id: Optional[str]
    amount: Decimal  # realized PnL delta


@dataclass
class _Event:
    """Internal unified event for chronological sorting."""
    timestamp: int
    datetime: datetime
    event_type: str       # BUY, SELL, REDEEM, SPLIT, MERGE, REWARD, CONVERSION
    asset: str
    market_id: Optional[str]
    outcome: str
    price: Decimal        # per-share price (trades only)
    size: Decimal         # number of shares
    usdc_size: Decimal    # total USDC amount (activities)
    total_value: Decimal  # price * size (trades) or usdc_size (activities)


class PositionTracker:
    """
    Processes trades and activities chronologically using weighted average
    cost basis to compute per-position state and realized PnL events.
    """

    def process_events(
        self,
        trades: list,
        activities: list,
        market_resolutions: Optional[Dict[str, str]] = None,
        db_market_assets: Optional[Dict] = None,
    ) -> Tuple[Dict[str, PositionState], List[RealizedPnLEvent]]:
        """
        Process all trades and activities for a wallet.

        Args:
            trades: List of trade objects (Django Trade model or MockTrade)
            activities: List of activity objects (Django Activity model or MockActivity)
            market_resolutions: Dict mapping market_id -> winning_outcome (e.g. 'Yes'/'No')

        Returns:
            (positions, realized_events) — dict of asset->PositionState, list of PnL events
        """
        self._market_resolutions = market_resolutions or {}

        # Build market-to-assets lookup from trades + activities for resolution
        market_assets = self._build_market_assets_map(trades, activities)

        # Merge in DB-sourced market assets (fills gaps from Trade records)
        if db_market_assets:
            for market_id, outcomes in db_market_assets.items():
                if market_id not in market_assets:
                    market_assets[market_id] = {}
                for outcome, asset_id in outcomes.items():
                    if outcome not in market_assets[market_id]:
                        market_assets[market_id][outcome] = asset_id

        # Merge into unified event list
        events = self._build_event_list(trades, activities)

        # Process chronologically
        positions: Dict[str, PositionState] = {}
        realized_events: List[RealizedPnLEvent] = []

        for event in events:
            self._process_event(event, positions, realized_events, market_assets)

        return positions, realized_events

    def _build_market_assets_map(
        self, trades: list, activities: list = None,
    ) -> Dict[str, Dict[str, str]]:
        """
        Build a mapping of market_id -> {outcome: asset_id} from trade and
        activity data.

        This allows SPLIT/MERGE/REDEEM/CONVERSION handling to know which
        assets correspond to YES and NO for a given market.
        """
        market_assets: Dict[str, Dict[str, str]] = {}
        for trade in trades:
            market_id = self._get_market_id(trade)
            if not market_id:
                continue
            asset = getattr(trade, 'asset', '') or ''
            outcome = getattr(trade, 'outcome', '') or ''
            if asset and outcome:
                if market_id not in market_assets:
                    market_assets[market_id] = {}
                market_assets[market_id][outcome] = asset

        # Enrich from activities (don't overwrite trade-sourced data)
        for activity in (activities or []):
            market_id = self._get_market_id(activity)
            if not market_id:
                continue
            asset = getattr(activity, 'asset', '') or ''
            outcome = getattr(activity, 'outcome', '') or ''
            if asset and outcome:
                if market_id not in market_assets:
                    market_assets[market_id] = {}
                if outcome not in market_assets[market_id]:
                    market_assets[market_id][outcome] = asset

        return market_assets

    def _build_event_list(self, trades: list, activities: list) -> List[_Event]:
        """Merge trades and activities into a single sorted event list."""
        events: List[_Event] = []

        for t in trades:
            events.append(_Event(
                timestamp=t.timestamp,
                datetime=t.datetime,
                event_type=t.side,  # BUY or SELL
                asset=getattr(t, 'asset', '') or '',
                market_id=self._get_market_id(t),
                outcome=getattr(t, 'outcome', '') or '',
                price=Decimal(str(t.price)),
                size=Decimal(str(t.size)),
                usdc_size=Decimal(str(t.total_value)),
                total_value=Decimal(str(t.total_value)),
            ))

        for a in activities:
            events.append(_Event(
                timestamp=a.timestamp,
                datetime=a.datetime,
                event_type=a.activity_type,  # REDEEM, SPLIT, MERGE, REWARD, CONVERSION
                asset=getattr(a, 'asset', '') or '',
                market_id=self._get_market_id(a),
                outcome=getattr(a, 'outcome', '') or '',
                price=ZERO,
                size=Decimal(str(a.size)),
                usdc_size=Decimal(str(a.usdc_size)),
                total_value=Decimal(str(a.usdc_size)),
            ))

        # Sort by timestamp, with ties broken by: buys before sells (so cost basis
        # is established before being consumed in the same second)
        type_order = {'BUY': 0, 'SPLIT': 1, 'SELL': 2, 'MERGE': 3, 'REDEEM': 4, 'REWARD': 5, 'CONVERSION': 6}
        events.sort(key=lambda e: (
            e.timestamp,
            type_order.get(e.event_type, 9),
            # Within same-timestamp REDEEMs, process winners (usdc>0) before
            # losers so position inference can work on the remaining position.
            -e.usdc_size if e.event_type == 'REDEEM' else ZERO,
        ))

        return events

    def _process_event(
        self,
        event: _Event,
        positions: Dict[str, PositionState],
        realized_events: List[RealizedPnLEvent],
        market_assets: Dict[str, Dict[str, str]],
    ) -> None:
        """Process a single event, updating positions and emitting realized PnL."""
        handler = {
            'BUY': self._handle_buy,
            'SELL': self._handle_sell,
            'REDEEM': self._handle_redeem,
            'SPLIT': self._handle_split,
            'MERGE': self._handle_merge,
            'REWARD': self._handle_reward,
            'CONVERSION': self._handle_conversion,
        }.get(event.event_type)

        if handler:
            handler(event, positions, realized_events, market_assets)

    def _get_or_create_position(
        self,
        positions: Dict[str, PositionState],
        asset: str,
        market_id: Optional[str] = None,
        outcome: str = '',
    ) -> PositionState:
        """Get or create a position state for an asset."""
        if asset not in positions:
            positions[asset] = PositionState(
                asset=asset,
                market_id=market_id,
                outcome=outcome,
            )
        return positions[asset]

    def _handle_buy(self, event, positions, realized_events, market_assets):
        """BUY: Increase position, update weighted average cost basis."""
        if not event.asset:
            return

        pos = self._get_or_create_position(
            positions, event.asset, event.market_id, event.outcome
        )

        # Weighted average: new_avg = (old_avg * old_qty + price * size) / (old_qty + size)
        old_cost = pos.avg_price * pos.quantity
        new_cost = event.price * event.size
        new_quantity = pos.quantity + event.size

        if new_quantity > ZERO:
            pos.avg_price = (old_cost + new_cost) / new_quantity

        pos.quantity = new_quantity
        pos.total_bought += event.size
        pos.total_cost += event.total_value

    def _handle_sell(self, event, positions, realized_events, market_assets):
        """SELL: Decrease position, realize PnL based on avg cost basis."""
        if not event.asset:
            return

        pos = self._get_or_create_position(
            positions, event.asset, event.market_id, event.outcome
        )

        # Realized PnL = (sell_price - avg_price) * size
        sell_size = min(event.size, pos.quantity) if pos.quantity > ZERO else ZERO
        if sell_size <= ZERO:
            return
        realized = (event.price - pos.avg_price) * sell_size
        pos.realized_pnl += realized
        pos.quantity = max(ZERO, pos.quantity - event.size)
        pos.total_sold += event.size
        pos.total_revenue += event.total_value

        # avg_price does NOT change on sells

        realized_events.append(RealizedPnLEvent(
            timestamp=event.timestamp,
            datetime=event.datetime,
            asset=event.asset,
            market_id=event.market_id,
            amount=realized,
        ))

    def _handle_redeem(self, event, positions, realized_events, market_assets):
        """
        REDEEM: Position resolves. Winners pay ~$1/share, losers ~$0/share.

        Redemption price = usdc_size / size (total USDC received per share).
        """
        if not event.asset:
            resolved_asset = None

            # Stage 1: market_assets lookup by outcome
            if event.market_id and event.market_id in market_assets:
                resolved_asset = market_assets[event.market_id].get(event.outcome, '')

            # Stage 2: market-resolution inference (most reliable for REDEEMs
            # with empty asset/outcome — infer winner vs loser from usdc_size)
            if not resolved_asset and event.market_id:
                winning_outcome = self._market_resolutions.get(event.market_id)
                if winning_outcome and event.market_id in market_assets:
                    outcomes = market_assets[event.market_id]
                    if event.usdc_size > ZERO:
                        # Winner side
                        inferred_outcome = winning_outcome
                    else:
                        # Loser side — the other outcome
                        other = [o for o in outcomes if o != winning_outcome]
                        inferred_outcome = other[0] if other else None
                    if inferred_outcome:
                        resolved_asset = outcomes.get(inferred_outcome, '')

            # Stage 3: Position-based inference (last resort fallback).
            # REDEEMs from the Activity API have empty asset/outcome fields.
            # Infer from open positions: if only one position exists for this
            # market, it must be the one being redeemed. Winner REDEEMs are
            # sorted before losers (by usdc_size desc), so the winner's
            # position is consumed first, leaving the loser's position as
            # the single remaining open position.
            if not resolved_asset and event.market_id:
                market_id_str = str(event.market_id)
                open_positions = [
                    (asset_id, pos) for asset_id, pos in positions.items()
                    if pos.market_id == market_id_str and pos.quantity > ZERO
                ]
                if len(open_positions) == 1:
                    resolved_asset = open_positions[0][0]

            if resolved_asset:
                event = _Event(
                    timestamp=event.timestamp,
                    datetime=event.datetime,
                    event_type=event.event_type,
                    asset=resolved_asset,
                    market_id=event.market_id,
                    outcome=event.outcome,
                    price=event.price,
                    size=event.size,
                    usdc_size=event.usdc_size,
                    total_value=event.total_value,
                )

        if not event.asset:
            # Can't resolve to a position — skip (cash_flow_pnl captures it)
            return

        pos = self._get_or_create_position(
            positions, event.asset, event.market_id, event.outcome
        )

        # Redemption price per share
        redeem_price = event.usdc_size / event.size if event.size > ZERO else ZERO
        redeem_size = min(event.size, pos.quantity) if pos.quantity > ZERO else ZERO
        if redeem_size <= ZERO:
            return

        realized = (redeem_price - pos.avg_price) * redeem_size
        pos.realized_pnl += realized
        pos.quantity = max(ZERO, pos.quantity - event.size)
        pos.total_revenue += event.usdc_size

        realized_events.append(RealizedPnLEvent(
            timestamp=event.timestamp,
            datetime=event.datetime,
            asset=event.asset,
            market_id=event.market_id,
            amount=realized,
        ))

    def _handle_split(self, event, positions, realized_events, market_assets):
        """
        SPLIT: Spend USDC to get YES + NO tokens. Each at 50% cost basis.

        Creates/adds to both YES and NO positions for the market.
        """
        market_id = event.market_id
        if not market_id:
            return

        # Cost per share for each outcome = usdc_size / size * 0.5
        # (spending $X to get `size` YES + `size` NO tokens)
        cost_per_share = event.usdc_size / event.size if event.size > ZERO else ZERO

        assets = market_assets.get(str(market_id), {})

        if assets:
            # We know the asset IDs — update each position
            for outcome_name, asset_id in assets.items():
                pos = self._get_or_create_position(
                    positions, asset_id, market_id, outcome_name
                )
                old_cost = pos.avg_price * pos.quantity
                # Each outcome gets `size` tokens at half the USDC cost
                new_cost = cost_per_share * HALF * event.size
                new_quantity = pos.quantity + event.size

                if new_quantity > ZERO:
                    pos.avg_price = (old_cost + new_cost) / new_quantity

                pos.quantity = new_quantity
                pos.total_bought += event.size
                pos.total_cost += event.usdc_size * HALF
        else:
            # No asset IDs known — create placeholder positions using market_id
            for suffix in ('YES', 'NO'):
                placeholder_asset = f"{market_id}_split_{suffix}"
                pos = self._get_or_create_position(
                    positions, placeholder_asset, market_id, suffix
                )
                old_cost = pos.avg_price * pos.quantity
                new_cost = cost_per_share * HALF * event.size
                new_quantity = pos.quantity + event.size

                if new_quantity > ZERO:
                    pos.avg_price = (old_cost + new_cost) / new_quantity

                pos.quantity = new_quantity
                pos.total_bought += event.size
                pos.total_cost += event.usdc_size * HALF

    def _handle_merge(self, event, positions, realized_events, market_assets):
        """
        MERGE: Return YES + NO tokens, receive USDC.

        Realized PnL = usdc_received - (avg_YES + avg_NO) * size
        """
        market_id = event.market_id
        if not market_id:
            # Can't resolve to positions — skip (cash_flow_pnl captures it)
            return

        assets = market_assets.get(str(market_id), {})

        total_avg_cost = ZERO
        merge_size = event.size
        asset_list = []
        had_existing_positions = False

        if assets:
            for outcome_name, asset_id in assets.items():
                # Check if position already exists with quantity before creating
                if asset_id in positions and positions[asset_id].quantity > ZERO:
                    had_existing_positions = True
                pos = self._get_or_create_position(
                    positions, asset_id, market_id, outcome_name
                )
                total_avg_cost += pos.avg_price
                actual_size = min(merge_size, pos.quantity) if pos.quantity > ZERO else merge_size
                pos.quantity = max(ZERO, pos.quantity - merge_size)
                pos.total_sold += actual_size
                asset_list.append(asset_id)
        else:
            # Check for placeholder positions
            for suffix in ('YES', 'NO'):
                placeholder_asset = f"{market_id}_split_{suffix}"
                if placeholder_asset in positions:
                    pos = positions[placeholder_asset]
                    if pos.quantity > ZERO:
                        had_existing_positions = True
                    total_avg_cost += pos.avg_price
                    actual_size = min(merge_size, pos.quantity) if pos.quantity > ZERO else merge_size
                    pos.quantity = max(ZERO, pos.quantity - merge_size)
                    pos.total_sold += actual_size
                    asset_list.append(placeholder_asset)

        # If no pre-existing positions had cost basis, skip — can't properly cost this merge
        if not had_existing_positions:
            return

        # Realized = usdc_received - total_cost_basis * size
        realized = event.usdc_size - total_avg_cost * merge_size

        # Attribute realized PnL to the first asset (or empty)
        primary_asset = asset_list[0] if asset_list else ''
        if primary_asset and primary_asset in positions:
            positions[primary_asset].realized_pnl += realized

        realized_events.append(RealizedPnLEvent(
            timestamp=event.timestamp,
            datetime=event.datetime,
            asset=primary_asset,
            market_id=market_id,
            amount=realized,
        ))

    def _handle_reward(self, event, positions, realized_events, market_assets):
        """REWARD: Pure income, no position change."""
        realized_events.append(RealizedPnLEvent(
            timestamp=event.timestamp,
            datetime=event.datetime,
            asset='',
            market_id=event.market_id,
            amount=event.usdc_size,
        ))

    def _handle_conversion(self, event, positions, realized_events, market_assets):
        """CONVERSION: Reduces source position, realizes PnL."""
        if not event.asset:
            return

        pos = self._get_or_create_position(
            positions, event.asset, event.market_id, event.outcome
        )
        conversion_size = min(event.size, pos.quantity) if pos.quantity > ZERO else ZERO
        if conversion_size <= ZERO:
            return
        realized = event.usdc_size - pos.avg_price * conversion_size
        pos.realized_pnl += realized
        pos.quantity = max(ZERO, pos.quantity - event.size)
        pos.total_revenue += event.usdc_size

        realized_events.append(RealizedPnLEvent(
            timestamp=event.timestamp,
            datetime=event.datetime,
            asset=event.asset,
            market_id=event.market_id,
            amount=realized,
        ))

    @staticmethod
    def _get_market_id(obj) -> Optional[str]:
        """Extract market_id from a trade or activity object."""
        market_id = getattr(obj, 'market_id', None)
        if market_id:
            return str(market_id)
        market = getattr(obj, 'market', None)
        if market:
            return str(getattr(market, 'id', None) or getattr(market, 'pk', None) or '')
        return None
