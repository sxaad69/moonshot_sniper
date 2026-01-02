"""
Moonshot Sniper Bot - Telegram Logger
Comprehensive logging system with 4 channels
"""

import asyncio
import aiohttp
from typing import Optional, Dict, List, Any
from datetime import datetime
from enum import Enum
import logging

from config.settings import Chain, TradingMode, TELEGRAM_CONFIG
from engines.safety_engine import SafetyReport, SafetyStatus
from scanners.dexscreener import TokenPair

logger = logging.getLogger(__name__)

class LogLevel(Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4

class TelegramLogger:
    """4-channel Telegram logging system"""
    
    def __init__(self, config=None):
        self.config = config or TELEGRAM_CONFIG
        self.bot_token = self.config.bot_token
        self.session: Optional[aiohttp.ClientSession] = None
        self.enabled = bool(self.bot_token)
        self.channels = {
            LogLevel.CRITICAL: self.config.main_alerts_channel,
            LogLevel.HIGH: self.config.main_alerts_channel,
            LogLevel.MEDIUM: self.config.positions_channel,
            LogLevel.LOW: self.config.rejections_channel
        }
        self.queue: List[tuple] = []
        self.queue_lock = asyncio.Lock()
    
    async def start(self):
        if self.enabled:
            self.session = aiohttp.ClientSession()
            asyncio.create_task(self._process_queue())
            logger.info("Telegram Logger started")
    
    async def stop(self):
        await self._flush_queue()
        if self.session:
            await self.session.close()
    
    async def _send(self, chat_id: str, text: str):
        if not self.enabled or not self.session or not chat_id:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            await self.session.post(url, json={
                "chat_id": chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True
            })
        except Exception as e:
            logger.warning(f"Telegram error: {e}")
    
    async def _queue_message(self, level: LogLevel, text: str):
        async with self.queue_lock:
            self.queue.append((level, text))
    
    async def _process_queue(self):
        while True:
            try:
                async with self.queue_lock:
                    if self.queue:
                        level, text = self.queue.pop(0)
                        await self._send(self.channels.get(level), text)
            except: pass
            await asyncio.sleep(0.1)
    
    async def _flush_queue(self):
        async with self.queue_lock:
            for level, text in self.queue:
                await self._send(self.channels.get(level), text)
            self.queue.clear()
    
    # ============================================================
    # REJECTION LOGS
    # ============================================================
    
    async def log_rejection(self, pair: TokenPair, chain: Chain, 
                           safety: Optional[SafetyReport], score: int, reasons: List[str]):
        if not self.config.log_rejections:
            return
        
        status = "❓ Unknown"
        if safety:
            status = {"safe": "✅ Passed", "warning": "⚠️ Warning", 
                     "dangerous": "❌ Failed"}.get(safety.status.value, "❓")
        
        text = f"""❌ <b>REJECTED: ${pair.base_token_symbol}</b>
━━━━━━━━━━━━━━━━━━━━━
<b>Chain:</b> {chain.value.upper()}
<b>Token:</b> <code>{pair.base_token_address[:20]}...</code>
<b>Age:</b> {pair.age_minutes:.1f}m

<b>REASONS:</b>
"""
        for r in reasons[:5]:
            text += f"├── {r}\n"
        
        text += f"""
<b>Safety:</b> {status}
<b>Score:</b> {score}/100
<b>Liquidity:</b> ${pair.liquidity_usd:,.0f}
<b>Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
        
        await self._queue_message(LogLevel.LOW, text)
    
    # ============================================================
    # ENTRY LOGS
    # ============================================================
    
    async def log_entry(self, pair: TokenPair, chain: Chain, pool: str,
                       safety: SafetyReport, score: int, signals: List[str],
                       size: float, entry_price: float, sl_price: float,
                       mode: TradingMode = TradingMode.SIMULATION):
        
        badge = "🎮 SIM" if mode == TradingMode.SIMULATION else "💰 LIVE"
        pool_icon = "🛡️" if pool == "SAFE" else "🎯"
        
        text = f"""{badge} ✅ <b>ENTRY: ${pair.base_token_symbol}</b>
━━━━━━━━━━━━━━━━━━━━━
{pool_icon} <b>Pool:</b> {pool}
<b>Chain:</b> {chain.value.upper()}
<b>Token:</b> <code>{pair.base_token_address}</code>

<b>✅ SAFETY PASSED</b>
├── Tax: {safety.tax_buy:.1f}%/{safety.tax_sell:.1f}%
├── LP: {"🔒 Locked" if safety.lp_locked else "⚠️ Unlocked"}
└── Holders: {safety.holder_count}

<b>✅ SCORE: {score}/100</b>

<b>✅ CONFLUENCE: {len(signals)} signals</b>
"""
        for s in signals[:5]:
            text += f"├── ✅ {s}\n"
        
        sl_pct = ((entry_price - sl_price) / entry_price * 100)
        text += f"""
<b>💰 POSITION</b>
├── Entry: ${entry_price:.10f}
├── Size: ${size:.2f}
├── Stop Loss: ${sl_price:.10f} (-{sl_pct:.0f}%)
├── TP1: +50% | TP2: +100% | TP3: +200%

<b>Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
        
        await self._queue_message(LogLevel.HIGH, text)
    
    # ============================================================
    # TP/SL LOGS
    # ============================================================
    
    async def log_tp_hit(self, symbol: str, level: int, sell_pct: float,
                        sell_value: float, profit: float, new_sl: float,
                        mode: TradingMode = TradingMode.SIMULATION):
        badge = "🎮 SIM" if mode == TradingMode.SIMULATION else "💰 LIVE"
        
        text = f"""{badge} 🎯 <b>TP{level} HIT: ${symbol}</b>
━━━━━━━━━━━━━━━━━━━━━
<b>Sold:</b> {sell_pct:.0f}% (${sell_value:.2f})
<b>Profit:</b> +${profit:.2f}
<b>New SL:</b> ${new_sl:.10f}

<b>Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
        
        await self._queue_message(LogLevel.HIGH, text)
    
    async def log_stop_loss(self, symbol: str, exit_price: float, 
                           loss: float, loss_pct: float, reason: str,
                           mode: TradingMode = TradingMode.SIMULATION):
        badge = "🎮 SIM" if mode == TradingMode.SIMULATION else "💰 LIVE"
        
        text = f"""{badge} 🛑 <b>STOPPED: ${symbol}</b>
━━━━━━━━━━━━━━━━━━━━━
<b>Exit Price:</b> ${exit_price:.10f}
<b>Loss:</b> ${loss:.2f} ({loss_pct:.1f}%)
<b>Reason:</b> {reason}

<b>Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
        
        await self._queue_message(LogLevel.HIGH, text)
    
    # ============================================================
    # EXIT LOGS
    # ============================================================
    
    async def log_exit(self, symbol: str, pool: str, entry_price: float,
                      exit_price: float, pnl_usd: float, pnl_pct: float,
                      reason: str, duration_min: float,
                      mode: TradingMode = TradingMode.SIMULATION):
        badge = "🎮 SIM" if mode == TradingMode.SIMULATION else "💰 LIVE"
        result = "🏆 WINNER" if pnl_usd >= 0 else "❌ LOSER"
        
        text = f"""{badge} 💰 <b>CLOSED: ${symbol}</b>
━━━━━━━━━━━━━━━━━━━━━
<b>Result:</b> {result}
<b>Pool:</b> {pool}

<b>SUMMARY:</b>
├── Entry: ${entry_price:.10f}
├── Exit: ${exit_price:.10f}
├── Return: {pnl_pct:+.1f}%
├── P&L: ${pnl_usd:+.2f}
└── Duration: {duration_min:.0f}m

<b>Reason:</b> {reason}
<b>Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
        
        await self._queue_message(LogLevel.HIGH, text)
    
    # ============================================================
    # DAILY SUMMARY
    # ============================================================
    
    async def log_daily_summary(self, date: str, start_cap: float, end_cap: float,
                               trades: int, winners: int, losers: int,
                               safe_pnl: float, hunt_pnl: float,
                               scanned: int, rejections: Dict[str, int],
                               mode: TradingMode = TradingMode.SIMULATION):
        badge = "🎮 SIMULATION" if mode == TradingMode.SIMULATION else "💰 LIVE"
        total_pnl = end_cap - start_cap
        pnl_pct = (total_pnl / start_cap * 100) if start_cap > 0 else 0
        win_rate = (winners / trades * 100) if trades > 0 else 0
        
        text = f"""📈 <b>DAILY REPORT - {date}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
{badge}

<b>PORTFOLIO:</b>
├── Starting: ${start_cap:.2f}
├── Ending: ${end_cap:.2f}
└── Day P&L: ${total_pnl:+.2f} ({pnl_pct:+.1f}%)

<b>TRADING:</b>
├── Tokens Scanned: {scanned:,}
├── Trades: {trades}
├── Winners: {winners} | Losers: {losers}
└── Win Rate: {win_rate:.1f}%

<b>POOLS:</b>
├── SAFE P&L: ${safe_pnl:+.2f}
└── HUNT P&L: ${hunt_pnl:+.2f}

<b>TOP REJECTIONS:</b>
"""
        for reason, count in sorted(rejections.items(), key=lambda x: -x[1])[:5]:
            text += f"├── {reason}: {count}\n"
        
        text += f"""
<b>Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
        
        await self._queue_message(LogLevel.CRITICAL, text)
    
    # ============================================================
    # SYSTEM LOGS
    # ============================================================
    
    async def log_startup(self, config: Dict):
        text = f"""🚀 <b>BOT STARTED</b>
━━━━━━━━━━━━━━━━━━━━━
<b>Mode:</b> {config.get('mode', 'SIMULATION')}
<b>Capital:</b> ${config.get('capital', 100):.2f}
<b>Chains:</b> {', '.join(config.get('chains', []))}

<b>Pools:</b>
├── SAFE: {config.get('safe_pct', 60)}%
└── HUNT: {config.get('hunt_pct', 40)}%

<b>Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
        
        await self._queue_message(LogLevel.CRITICAL, text)
    
    async def log_error(self, error: str, context: str = ""):
        text = f"""❌ <b>ERROR</b>
━━━━━━━━━━━━━━━━━━━━━
<b>Context:</b> {context}
<b>Error:</b> {error}

<b>Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
        
        await self._queue_message(LogLevel.CRITICAL, text)
    
    async def log_system(self, message: str, level: str = "INFO"):
        emoji = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌"}.get(level, "ℹ️")
        text = f"""{emoji} <b>SYSTEM: {level}</b>
{message}
<b>Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
        
        await self._queue_message(LogLevel.MEDIUM, text)
    
    async def log_position_update(self, symbol: str, price: float, pnl_pct: float,
                                 tp_hit: List[int], sl: float):
        text = f"""📊 <b>UPDATE: ${symbol}</b>
├── Price: ${price:.10f}
├── P&L: {pnl_pct:+.1f}%
├── TPs Hit: {tp_hit}
└── SL: ${sl:.10f}"""
        
        await self._queue_message(LogLevel.MEDIUM, text)


# Singleton
_telegram: Optional[TelegramLogger] = None

def get_telegram_logger() -> TelegramLogger:
    global _telegram
    if _telegram is None:
        _telegram = TelegramLogger()
    return _telegram

async def shutdown_telegram_logger():
    global _telegram
    if _telegram:
        await _telegram.stop()
        _telegram = None
