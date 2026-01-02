"""
Moonshot Sniper Bot - Main Orchestrator
Complete bot coordination and lifecycle management
"""

import asyncio
import signal
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import (
    Chain, WalletConfig, TradingMode, TRADING_CONFIG, SAFE_POOL, HUNT_POOL,
    CHAIN_CONFIGS, load_config_from_env, BotConfig
)
from core.rpc_manager import get_rpc_manager, shutdown_rpc_manager
from core.database import get_database, shutdown_database, DailyStats
from scanners.dexscreener import get_dexscreener, shutdown_dexscreener, TokenPair
from scanners.wallet_tracker import get_wallet_tracker, shutdown_wallet_tracker
from engines.safety_engine import get_safety_engine, shutdown_safety_engine, SafetyStatus
from engines.scoring_engine import get_scoring_engine
from engines.momentum_engine import get_momentum_engine
from engines.confluence_engine import get_confluence_engine
from engines.execution_engine import get_execution_engine, shutdown_execution_engine
from engines.position_manager import get_position_manager, shutdown_position_manager
from utils.telegram_logger import get_telegram_logger, shutdown_telegram_logger

# Setup logging
def setup_logging():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('logs/bot.log')
        ]
    )

logger = logging.getLogger(__name__)


class MoonshotBot:
    """
    Main bot orchestrator
    Coordinates all components for the complete trading system
    """
    
    def __init__(self, config: BotConfig = None):
        self.config = config or load_config_from_env()
        self.wallets = self.config.wallets
        self.mode = self.config.trading.mode
        self.active_chains = self.wallets.get_active_chains()
        
        # Components (initialized on start)
        self.rpc = None
        self.db = None
        self.dexscreener = None
        self.wallet_tracker = None
        self.safety_engine = None
        self.scoring_engine = None
        self.momentum_engine = None
        self.confluence_engine = None
        self.execution_engine = None
        self.position_manager = None
        self.telegram = None
        
        # Statistics
        self.stats = {
            "tokens_scanned": 0,
            "tokens_analyzed": 0,
            "entries": 0,
            "rejections": 0,
            "rejections_by_reason": {},
            "start_time": None
        }
        
        # Control
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        logger.info(f"MoonshotBot initialized in {self.mode.value} mode")
        logger.info(f"Active chains: {[c.value for c in self.active_chains]}")
    
    async def start(self):
        """Start all bot components"""
        logger.info("Starting Moonshot Sniper Bot...")
        
        # Initialize all components
        self.rpc = get_rpc_manager(self.wallets)
        self.db = await get_database()
        self.dexscreener = get_dexscreener()
        self.wallet_tracker = get_wallet_tracker()
        self.safety_engine = get_safety_engine()
        self.scoring_engine = get_scoring_engine()
        self.momentum_engine = get_momentum_engine()
        self.confluence_engine = get_confluence_engine()
        self.execution_engine = get_execution_engine(self.wallets, self.mode)
        self.position_manager = get_position_manager(self.mode)
        self.telegram = get_telegram_logger()
        
        # Start components
        await self.rpc.start()
        await self.dexscreener.start()
        await self.wallet_tracker.start()
        await self.safety_engine.start()
        await self.execution_engine.start()
        await self.position_manager.start()
        await self.telegram.start()
        
        self.running = True
        self.stats["start_time"] = datetime.utcnow()
        
        # Log startup
        await self.telegram.log_startup({
            "mode": self.mode.value.upper(),
            "capital": TRADING_CONFIG.starting_capital,
            "chains": [c.value.upper() for c in self.active_chains],
            "safe_pct": SAFE_POOL.allocation_percent,
            "hunt_pct": HUNT_POOL.allocation_percent
        })
        
        logger.info("All components started successfully!")
        
        # Start main loops
        await asyncio.gather(
            self._scan_loop(),
            self._position_loop(),
            self._daily_loop(),
            return_exceptions=True
        )
    
    async def stop(self):
        """Stop all bot components"""
        logger.info("Stopping Moonshot Sniper Bot...")
        self.running = False
        self.shutdown_event.set()
        
        # Log daily summary
        await self._save_daily_stats()
        
        # Shutdown all components
        await shutdown_telegram_logger()
        await shutdown_position_manager()
        await shutdown_execution_engine()
        await shutdown_wallet_tracker()
        await shutdown_safety_engine()
        await shutdown_dexscreener()
        await shutdown_rpc_manager()
        await shutdown_database()
        
        logger.info("Bot stopped successfully!")
    
    # ============================================================
    # MAIN SCANNING LOOP
    # ============================================================
    
    async def _scan_loop(self):
        """Main token scanning loop"""
        logger.info("Starting scan loop...")
        
        while self.running:
            try:
                for chain in self.active_chains:
                    await self._scan_chain(chain)
                
                await asyncio.sleep(TRADING_CONFIG.scan_interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
                await self.telegram.log_error(str(e), "Scan Loop")
                await asyncio.sleep(5)
    
    async def _scan_chain(self, chain: Chain):
        """Scan a single chain for opportunities"""
        try:
            # Get new tokens
            new_tokens = await self.dexscreener.scan_new_tokens(
                [chain],
                min_liquidity=CHAIN_CONFIGS[chain].min_liquidity,
                max_age_minutes=60
            )
            
            for chain, pair in new_tokens[:10]:  # Limit per cycle
                self.stats["tokens_scanned"] += 1
                await self._analyze_token(chain, pair)
                await asyncio.sleep(0.5)  # Rate limiting
                
        except Exception as e:
            logger.error(f"Chain scan error ({chain.value}): {e}")
    
    async def _analyze_token(self, chain: Chain, pair: TokenPair):
        """Full analysis pipeline for a token"""
        self.stats["tokens_analyzed"] += 1
        rejection_reasons = []
        
        # Quick filters
        config = CHAIN_CONFIGS[chain]
        
        if pair.liquidity_usd < config.min_liquidity:
            rejection_reasons.append(f"Low liquidity: ${pair.liquidity_usd:,.0f}")
        
        if pair.age_minutes > 240:
            rejection_reasons.append(f"Too old: {pair.age_minutes:.0f}m")
        
        if pair.buy_pressure_5m < 0.35:
            rejection_reasons.append(f"Heavy selling: {pair.buy_pressure_5m*100:.0f}%")
        
        if rejection_reasons:
            await self._reject_token(pair, chain, None, 0, rejection_reasons)
            return
        
        # Safety analysis
        safety = await self.safety_engine.analyze(chain, pair.base_token_address)
        
        if safety.status == SafetyStatus.DANGEROUS:
            reasons = self.safety_engine.get_rejection_reasons(safety)
            await self._reject_token(pair, chain, safety, safety.score, reasons)
            return
        
        # Get additional data
        momentum = self.momentum_engine.analyze(chain, pair.base_token_address, pair)
        smart_money = await self.wallet_tracker.get_smart_money_signals(
            pair.base_token_address, chain
        )
        
        # Quality scoring
        score = self.scoring_engine.score(pair, safety, None, None, smart_money)
        
        # Confluence analysis
        confluence = self.confluence_engine.analyze(
            chain, pair, safety, score, momentum, smart_money
        )
        
        # Entry decision
        if confluence.should_enter:
            await self._enter_position(chain, pair, safety, score, confluence)
        else:
            await self._reject_token(
                pair, chain, safety, score.total_score,
                confluence.rejection_reasons
            )
    
    async def _reject_token(self, pair: TokenPair, chain: Chain,
                           safety: Optional[any], score: int, reasons: List[str]):
        """Log token rejection"""
        self.stats["rejections"] += 1
        
        # Track reasons
        for reason in reasons:
            key = reason.split(":")[0].strip()
            self.stats["rejections_by_reason"][key] = \
                self.stats["rejections_by_reason"].get(key, 0) + 1
        
        await self.telegram.log_rejection(pair, chain, safety, score, reasons)
    
    async def _enter_position(self, chain: Chain, pair: TokenPair,
                             safety, score, confluence):
        """Execute entry into a position"""
        pool = confluence.recommended_pool
        size_pct = confluence.position_size_percent
        
        # Calculate position size
        pm = self.position_manager
        pool_capital = pm.safe_pool_capital if pool == "SAFE" else pm.hunt_pool_capital
        size_usd = pool_capital * (size_pct / 100)
        
        # Clamp size
        size_usd = max(TRADING_CONFIG.min_position_size,
                      min(TRADING_CONFIG.max_position_size, size_usd))
        
        # Open position
        position = await pm.open_position(
            chain=chain,
            token_address=pair.base_token_address,
            symbol=pair.base_token_symbol,
            pool=pool,
            entry_price=pair.price_usd,
            size_usd=size_usd
        )
        
        if position:
            self.stats["entries"] += 1
            
            # Log entry
            signals = [s.name for s in confluence.signals if s.active]
            await self.telegram.log_entry(
                pair=pair,
                chain=chain,
                pool=pool,
                safety=safety,
                score=score.total_score,
                signals=signals,
                size=size_usd,
                entry_price=pair.price_usd,
                sl_price=position.current_stop_loss,
                mode=self.mode
            )
            
            logger.info(f"Entered {pool}: {pair.base_token_symbol} @ ${pair.price_usd:.10f}")
    
    # ============================================================
    # POSITION MONITORING LOOP
    # ============================================================
    
    async def _position_loop(self):
        """Position monitoring and management loop"""
        logger.info("Starting position loop...")
        
        while self.running:
            try:
                await self.position_manager.update_positions()
                await asyncio.sleep(TRADING_CONFIG.position_check_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Position loop error: {e}")
                await asyncio.sleep(5)
    
    # ============================================================
    # DAILY STATS LOOP
    # ============================================================
    
    async def _daily_loop(self):
        """Daily statistics and summary loop"""
        logger.info("Starting daily loop...")
        
        while self.running:
            try:
                now = datetime.utcnow()
                
                # Check if midnight UTC
                if now.hour == 0 and now.minute == 0:
                    await self._save_daily_stats()
                    await self._log_daily_summary()
                    
                    # Reset daily stats
                    self.position_manager.daily_pnl = 0
                    self.position_manager.daily_trades = 0
                    self.stats["tokens_scanned"] = 0
                    self.stats["tokens_analyzed"] = 0
                    self.stats["rejections_by_reason"] = {}
                
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Daily loop error: {e}")
                await asyncio.sleep(60)
    
    async def _save_daily_stats(self):
        """Save daily statistics to database"""
        pm = self.position_manager
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        # Get trade counts
        trades = await self.db.get_today_trades()
        winners = len([t for t in trades if t.trade_type in ["TP1", "TP2", "TP3", "TP4"]])
        losers = len([t for t in trades if t.trade_type in ["STOP_LOSS", "TRAILING_STOP"]])
        
        stats = DailyStats(
            date=today,
            starting_capital=TRADING_CONFIG.starting_capital,
            ending_capital=pm.total_capital + pm.daily_pnl,
            total_pnl=pm.daily_pnl,
            pnl_percent=(pm.daily_pnl / pm.total_capital * 100),
            trades_count=len(trades),
            winners=winners,
            losers=losers,
            win_rate=(winners / len(trades) * 100) if trades else 0,
            safe_pnl=0,  # Would calculate per pool
            hunt_pnl=0,
            tokens_scanned=self.stats["tokens_scanned"],
            tokens_rejected=self.stats["rejections"]
        )
        
        await self.db.save_daily_stats(stats)
    
    async def _log_daily_summary(self):
        """Log daily summary to Telegram"""
        pm = self.position_manager
        today = datetime.utcnow().strftime("%B %d, %Y")
        
        trades = await self.db.get_today_trades()
        winners = len([t for t in trades if t.trade_type.startswith("TP")])
        losers = len([t for t in trades if "STOP" in t.trade_type])
        
        await self.telegram.log_daily_summary(
            date=today,
            start_cap=TRADING_CONFIG.starting_capital,
            end_cap=pm.total_capital + pm.daily_pnl,
            trades=len(trades),
            winners=winners,
            losers=losers,
            safe_pnl=0,
            hunt_pnl=0,
            scanned=self.stats["tokens_scanned"],
            rejections=self.stats["rejections_by_reason"],
            mode=self.mode
        )
    
    # ============================================================
    # STATUS & CONTROL
    # ============================================================
    
    def get_status(self) -> Dict:
        """Get current bot status"""
        pm = self.position_manager
        return {
            "running": self.running,
            "mode": self.mode.value,
            "uptime_hours": (datetime.utcnow() - self.stats["start_time"]).seconds / 3600 if self.stats["start_time"] else 0,
            "chains": [c.value for c in self.active_chains],
            "positions": pm.get_position_count() if pm else 0,
            "portfolio": pm.get_portfolio_summary() if pm else {},
            "stats": {
                "scanned": self.stats["tokens_scanned"],
                "analyzed": self.stats["tokens_analyzed"],
                "entries": self.stats["entries"],
                "rejections": self.stats["rejections"]
            },
            "rpc_health": self.rpc.get_health_report() if self.rpc else {}
        }


async def main():
    """Main entry point"""
    setup_logging()
    
    # Load configuration
    config = load_config_from_env()
    
    # Override with CLI args or defaults for testing
    if not config.wallets.get_active_chains():
        logger.warning("No wallets configured, using test mode")
        config.wallets.SOL = "test_wallet"
    
    # Create bot
    bot = MoonshotBot(config)
    
    # Setup signal handlers
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Shutdown signal received")
        asyncio.create_task(bot.stop())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt")
    finally:
        if bot.running:
            await bot.stop()


if __name__ == "__main__":
    # Create required directories
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    
    # Load .env if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # Run bot
    asyncio.run(main())
