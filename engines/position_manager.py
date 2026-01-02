"""
Moonshot Sniper Bot - Position Manager
Complete position lifecycle management with TP/SL
"""

import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging

from config.settings import (
    Chain, PoolType, SAFE_POOL, HUNT_POOL, TAKE_PROFIT_LADDER,
    TRADING_CONFIG, TradingMode
)
from core.database import get_database, Position, Trade
from engines.execution_engine import get_execution_engine, SwapResult
from scanners.dexscreener import get_dexscreener

logger = logging.getLogger(__name__)

@dataclass
class ActivePosition:
    """Runtime position with real-time tracking"""
    db_position: Position
    chain: Chain
    
    # Real-time data
    current_price: float = 0
    highest_price: float = 0
    pnl_percent: float = 0
    pnl_usd: float = 0
    
    # TP/SL state
    tp_levels_hit: List[int] = field(default_factory=list)
    current_stop_loss: float = 0
    trailing_active: bool = False
    trailing_high: float = 0
    
    # Quantities
    original_quantity: float = 0
    remaining_quantity: float = 0
    total_sold_value: float = 0
    total_realized_pnl: float = 0
    
    @property
    def position_id(self) -> int:
        return self.db_position.id
    
    @property
    def token_address(self) -> str:
        return self.db_position.token_address
    
    @property
    def symbol(self) -> str:
        return self.db_position.symbol
    
    @property
    def pool(self) -> str:
        return self.db_position.pool
    
    @property
    def entry_price(self) -> float:
        return self.db_position.entry_price
    
    @property
    def entry_value(self) -> float:
        return self.db_position.entry_value
    
    @property
    def entry_time(self) -> datetime:
        return datetime.fromisoformat(self.db_position.entry_time)
    
    @property
    def age_minutes(self) -> float:
        return (datetime.utcnow() - self.entry_time).total_seconds() / 60
    
    @property
    def current_value(self) -> float:
        return self.remaining_quantity * self.current_price
    
    def update_price(self, new_price: float):
        """Update current price and recalculate metrics"""
        self.current_price = new_price
        
        # Update highest price
        if new_price > self.highest_price:
            self.highest_price = new_price
            if self.trailing_active:
                self.trailing_high = new_price
        
        # Calculate PnL
        if self.entry_price > 0:
            self.pnl_percent = ((new_price - self.entry_price) / self.entry_price) * 100
            unrealized = self.remaining_quantity * (new_price - self.entry_price)
            self.pnl_usd = self.total_realized_pnl + unrealized
    
    def to_dict(self) -> Dict:
        return {
            "id": self.position_id,
            "token": self.token_address,
            "symbol": self.symbol,
            "chain": self.chain.value,
            "pool": self.pool,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "highest_price": self.highest_price,
            "pnl_percent": self.pnl_percent,
            "pnl_usd": self.pnl_usd,
            "remaining_qty": self.remaining_quantity,
            "tp_hit": self.tp_levels_hit,
            "stop_loss": self.current_stop_loss,
            "age_minutes": self.age_minutes
        }


class PositionManager:
    """
    Manages the full lifecycle of trading positions
    - Entry execution
    - Price monitoring
    - Take profit ladder
    - Stop loss / trailing stop
    - Exit execution
    """
    
    def __init__(self, mode: TradingMode = TradingMode.SIMULATION):
        self.mode = mode
        self.positions: Dict[int, ActivePosition] = {}
        self.execution = None
        self.dexscreener = None
        self.db = None
        
        # Portfolio tracking
        self.total_capital: float = TRADING_CONFIG.starting_capital
        self.available_capital: float = TRADING_CONFIG.starting_capital
        self.safe_pool_capital: float = self.total_capital * (SAFE_POOL.allocation_percent / 100)
        self.hunt_pool_capital: float = self.total_capital * (HUNT_POOL.allocation_percent / 100)
        
        # Daily tracking
        self.daily_pnl: float = 0
        self.daily_trades: int = 0
        self.consecutive_losses: int = 0
        self.is_paused: bool = False
        self.pause_until: Optional[datetime] = None
    
    async def start(self):
        """Initialize the position manager"""
        self.db = await get_database()
        self.execution = get_execution_engine()
        self.dexscreener = get_dexscreener()
        
        await self.execution.start()
        await self.dexscreener.start()
        
        # Load open positions from database
        await self._load_open_positions()
        
        logger.info(f"Position Manager started with ${self.total_capital:.2f} capital")
    
    async def stop(self):
        """Shutdown the position manager"""
        # Save all position states
        for pos in self.positions.values():
            await self._save_position_state(pos)
        
        logger.info("Position Manager stopped")
    
    async def _load_open_positions(self):
        """Load open positions from database"""
        open_positions = await self.db.get_open_positions()
        
        for db_pos in open_positions:
            chain = Chain(db_pos.chain)
            active = ActivePosition(
                db_position=db_pos,
                chain=chain,
                current_price=db_pos.current_price,
                highest_price=db_pos.highest_price,
                current_stop_loss=db_pos.stop_loss,
                original_quantity=db_pos.quantity,
                remaining_quantity=db_pos.remaining_quantity or db_pos.quantity,
                tp_levels_hit=json.loads(db_pos.tp_levels_hit) if db_pos.tp_levels_hit else []
            )
            self.positions[db_pos.id] = active
        
        logger.info(f"Loaded {len(self.positions)} open positions")
    
    async def _save_position_state(self, pos: ActivePosition):
        """Save position state to database"""
        await self.db.update_position(
            pos.position_id,
            current_price=pos.current_price,
            highest_price=pos.highest_price,
            pnl_percent=pos.pnl_percent,
            pnl_usd=pos.pnl_usd,
            stop_loss=pos.current_stop_loss,
            remaining_quantity=pos.remaining_quantity,
            tp_levels_hit=json.dumps(pos.tp_levels_hit),
            current_value=pos.current_value
        )
    
    # ============================================================
    # ENTRY
    # ============================================================
    
    async def open_position(self, chain: Chain, token_address: str, symbol: str,
                           pool: str, entry_price: float, size_usd: float) -> Optional[ActivePosition]:
        """
        Open a new position
        
        Args:
            chain: Target chain
            token_address: Token to buy
            symbol: Token symbol
            pool: SAFE or HUNT
            entry_price: Current price
            size_usd: Position size in USD
        
        Returns:
            ActivePosition or None
        """
        # Check if paused
        if self.is_paused:
            if self.pause_until and datetime.utcnow() < self.pause_until:
                logger.warning("Trading paused due to circuit breaker")
                return None
            self.is_paused = False
        
        # Check position limits
        pool_config = SAFE_POOL if pool == "SAFE" else HUNT_POOL
        pool_positions = len([p for p in self.positions.values() if p.pool == pool])
        
        if pool_positions >= pool_config.max_positions:
            logger.warning(f"{pool} pool at max positions ({pool_config.max_positions})")
            return None
        
        if len(self.positions) >= TRADING_CONFIG.max_total_positions:
            logger.warning(f"Total positions at max ({TRADING_CONFIG.max_total_positions})")
            return None
        
        # Check available capital
        pool_capital = self.safe_pool_capital if pool == "SAFE" else self.hunt_pool_capital
        if size_usd > pool_capital:
            size_usd = pool_capital * 0.9  # Use 90% of remaining
        
        if size_usd < TRADING_CONFIG.min_position_size:
            logger.warning(f"Position size too small: ${size_usd:.2f}")
            return None
        
        # Calculate quantity
        quantity = size_usd / entry_price if entry_price > 0 else 0
        
        # Calculate stop loss
        sl_percent = abs(pool_config.stop_loss_percent)
        stop_loss = entry_price * (1 - sl_percent / 100)
        
        # Execute buy
        result = await self.execution.buy_token(chain, token_address, size_usd / self._get_native_price(chain))
        
        if not result.success:
            logger.error(f"Buy failed: {result.error}")
            return None
        
        # Create database position
        db_position = Position(
            token_address=token_address,
            symbol=symbol,
            chain=chain.value,
            pool=pool,
            entry_price=entry_price,
            quantity=quantity,
            entry_value=size_usd,
            stop_loss=stop_loss,
            entry_time=datetime.utcnow().isoformat(),
            remaining_quantity=quantity
        )
        
        position_id = await self.db.create_position(db_position)
        db_position.id = position_id
        
        # Record trade
        await self.db.record_trade(Trade(
            position_id=position_id,
            trade_type="BUY",
            token_address=token_address,
            symbol=symbol,
            chain=chain.value,
            price=entry_price,
            quantity=quantity,
            value=size_usd,
            slippage=result.slippage,
            tx_hash=result.tx_hash,
            timestamp=datetime.utcnow().isoformat()
        ))
        
        # Create active position
        active = ActivePosition(
            db_position=db_position,
            chain=chain,
            current_price=entry_price,
            highest_price=entry_price,
            current_stop_loss=stop_loss,
            original_quantity=quantity,
            remaining_quantity=quantity
        )
        
        self.positions[position_id] = active
        
        # Update capital
        if pool == "SAFE":
            self.safe_pool_capital -= size_usd
        else:
            self.hunt_pool_capital -= size_usd
        self.available_capital -= size_usd
        
        logger.info(f"Opened {pool} position: {symbol} @ ${entry_price:.10f} (${size_usd:.2f})")
        
        return active
    
    # ============================================================
    # MONITORING
    # ============================================================
    
    async def update_positions(self):
        """Update all position prices and check TP/SL"""
        for pos in list(self.positions.values()):
            try:
                # Get current price
                price = await self.dexscreener.get_price(pos.chain, pos.token_address)
                
                if price and price > 0:
                    old_price = pos.current_price
                    pos.update_price(price)
                    
                    # Check take profits
                    await self._check_take_profits(pos)
                    
                    # Check stop loss
                    await self._check_stop_loss(pos)
                    
                    # Check time-based exit
                    await self._check_time_exit(pos)
                    
                    # Save state periodically
                    await self._save_position_state(pos)
                    
            except Exception as e:
                logger.error(f"Error updating position {pos.symbol}: {e}")
    
    async def _check_take_profits(self, pos: ActivePosition):
        """Check and execute take profit levels"""
        for tp in TAKE_PROFIT_LADDER:
            if tp.level in pos.tp_levels_hit:
                continue
            
            trigger_price = pos.entry_price * (1 + tp.trigger_percent / 100)
            
            if pos.current_price >= trigger_price:
                await self._execute_take_profit(pos, tp.level, tp.sell_percent, tp.move_sl_to_percent)
    
    async def _execute_take_profit(self, pos: ActivePosition, level: int, 
                                   sell_percent: float, new_sl_percent: Optional[float]):
        """Execute a take profit level"""
        sell_quantity = pos.remaining_quantity * (sell_percent / 100)
        
        if sell_quantity <= 0:
            return
        
        # Execute sell
        result = await self.execution.sell_token(pos.chain, pos.token_address, sell_quantity)
        
        if result.success:
            sell_value = sell_quantity * pos.current_price
            profit = sell_value - (sell_quantity * pos.entry_price)
            
            pos.tp_levels_hit.append(level)
            pos.remaining_quantity -= sell_quantity
            pos.total_sold_value += sell_value
            pos.total_realized_pnl += profit
            
            # Move stop loss
            if new_sl_percent is not None:
                new_sl = pos.entry_price * (1 + new_sl_percent / 100)
                if new_sl > pos.current_stop_loss:
                    pos.current_stop_loss = new_sl
                    logger.info(f"Moved SL to +{new_sl_percent}% for {pos.symbol}")
            
            # Record trade
            await self.db.record_trade(Trade(
                position_id=pos.position_id,
                trade_type=f"TP{level}",
                token_address=pos.token_address,
                symbol=pos.symbol,
                chain=pos.chain.value,
                price=pos.current_price,
                quantity=sell_quantity,
                value=sell_value,
                tx_hash=result.tx_hash,
                timestamp=datetime.utcnow().isoformat()
            ))
            
            # Activate trailing stop after TP4
            if level >= 4:
                pos.trailing_active = True
                pos.trailing_high = pos.current_price
            
            logger.info(f"TP{level} hit for {pos.symbol}: sold {sell_percent}% for ${sell_value:.2f}")
            
            return True
        
        return False
    
    async def _check_stop_loss(self, pos: ActivePosition):
        """Check stop loss conditions"""
        # Trailing stop
        if pos.trailing_active:
            pool_config = SAFE_POOL if pos.pool == "SAFE" else HUNT_POOL
            trail_percent = pool_config.trailing_stop_percent
            trail_stop = pos.trailing_high * (1 - trail_percent / 100)
            
            if trail_stop > pos.current_stop_loss:
                pos.current_stop_loss = trail_stop
            
            if pos.current_price <= trail_stop:
                await self._close_position(pos, "TRAILING_STOP")
                return
        
        # Regular stop loss
        if pos.current_price <= pos.current_stop_loss:
            await self._close_position(pos, "STOP_LOSS")
    
    async def _check_time_exit(self, pos: ActivePosition):
        """Check time-based exit conditions"""
        pool_config = SAFE_POOL if pos.pool == "SAFE" else HUNT_POOL
        max_age = pool_config.flat_exit_minutes
        
        # Exit if flat for too long
        if pos.age_minutes > max_age:
            if abs(pos.pnl_percent) < 10:  # Less than 10% move
                await self._close_position(pos, "TIME_EXIT")
    
    # ============================================================
    # EXIT
    # ============================================================
    
    async def _close_position(self, pos: ActivePosition, reason: str):
        """Close a position completely"""
        if pos.remaining_quantity <= 0:
            return
        
        # Execute sell
        result = await self.execution.sell_token(
            pos.chain, pos.token_address, pos.remaining_quantity
        )
        
        if result.success:
            sell_value = pos.remaining_quantity * pos.current_price
            final_profit = sell_value - (pos.remaining_quantity * pos.entry_price)
            total_pnl = pos.total_realized_pnl + final_profit
            
            # Record trade
            await self.db.record_trade(Trade(
                position_id=pos.position_id,
                trade_type=reason,
                token_address=pos.token_address,
                symbol=pos.symbol,
                chain=pos.chain.value,
                price=pos.current_price,
                quantity=pos.remaining_quantity,
                value=sell_value,
                tx_hash=result.tx_hash,
                timestamp=datetime.utcnow().isoformat()
            ))
            
            # Close in database
            await self.db.close_position(
                pos.position_id,
                pos.current_price,
                reason,
                total_pnl
            )
            
            # Update capital
            return_value = pos.total_sold_value + sell_value
            if pos.pool == "SAFE":
                self.safe_pool_capital += return_value
            else:
                self.hunt_pool_capital += return_value
            self.available_capital += return_value
            
            # Update daily stats
            self.daily_pnl += total_pnl
            self.daily_trades += 1
            
            if total_pnl < 0:
                self.consecutive_losses += 1
                self._check_circuit_breaker()
            else:
                self.consecutive_losses = 0
            
            # Remove from active positions
            if pos.position_id in self.positions:
                del self.positions[pos.position_id]
            
            logger.info(f"Closed {pos.symbol}: {reason} | PnL: ${total_pnl:+.2f} ({pos.pnl_percent:+.1f}%)")
    
    async def close_all_positions(self, reason: str = "MANUAL"):
        """Emergency close all positions"""
        for pos in list(self.positions.values()):
            await self._close_position(pos, reason)
    
    # ============================================================
    # CIRCUIT BREAKER
    # ============================================================
    
    def _check_circuit_breaker(self):
        """Check if circuit breaker should activate"""
        # Consecutive loss limit
        if self.consecutive_losses >= TRADING_CONFIG.consecutive_loss_pause:
            self._activate_pause(f"{self.consecutive_losses} consecutive losses")
            return
        
        # Daily loss limit
        daily_loss_percent = (self.daily_pnl / self.total_capital) * 100
        if daily_loss_percent <= -TRADING_CONFIG.daily_loss_limit_percent:
            self._activate_pause(f"Daily loss limit hit: {daily_loss_percent:.1f}%")
    
    def _activate_pause(self, reason: str):
        """Activate trading pause"""
        from datetime import timedelta
        self.is_paused = True
        self.pause_until = datetime.utcnow() + timedelta(hours=TRADING_CONFIG.pause_duration_hours)
        logger.warning(f"Circuit breaker activated: {reason}. Paused until {self.pause_until}")
    
    # ============================================================
    # UTILITIES
    # ============================================================
    
    def _get_native_price(self, chain: Chain) -> float:
        """Get native token price (placeholder)"""
        # Would fetch from price API
        prices = {Chain.SOL: 100, Chain.BSC: 300, Chain.BASE: 2000}
        return prices.get(chain, 100)
    
    def get_position_count(self, pool: Optional[str] = None) -> int:
        """Get count of open positions"""
        if pool:
            return len([p for p in self.positions.values() if p.pool == pool])
        return len(self.positions)
    
    def get_total_exposure(self) -> float:
        """Get total current exposure in USD"""
        return sum(p.current_value for p in self.positions.values())
    
    def get_portfolio_summary(self) -> Dict:
        """Get portfolio summary"""
        return {
            "total_capital": self.total_capital,
            "available": self.available_capital,
            "safe_pool": self.safe_pool_capital,
            "hunt_pool": self.hunt_pool_capital,
            "exposure": self.get_total_exposure(),
            "positions": self.get_position_count(),
            "daily_pnl": self.daily_pnl,
            "is_paused": self.is_paused
        }


# Singleton
_position_manager: Optional[PositionManager] = None

def get_position_manager(mode: TradingMode = None) -> PositionManager:
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager(mode or TradingMode.SIMULATION)
    return _position_manager

async def shutdown_position_manager():
    global _position_manager
    if _position_manager:
        await _position_manager.stop()
        _position_manager = None
