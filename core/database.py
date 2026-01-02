"""
Moonshot Sniper Bot - Database Layer
SQLite persistence for positions, trades, and analytics
"""

import aiosqlite
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import json
import logging
import os

from config.settings import Chain, PoolType, DATABASE_CONFIG

logger = logging.getLogger(__name__)

@dataclass
class Position:
    id: Optional[int] = None
    token_address: str = ""
    symbol: str = ""
    chain: str = ""
    pool: str = ""
    entry_price: float = 0
    current_price: float = 0
    quantity: float = 0
    entry_value: float = 0
    current_value: float = 0
    pnl_percent: float = 0
    pnl_usd: float = 0
    highest_price: float = 0
    stop_loss: float = 0
    entry_time: str = ""
    status: str = "OPEN"
    tp_levels_hit: str = "[]"
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    total_sold: float = 0
    remaining_quantity: float = 0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_row(cls, row: tuple, columns: List[str]) -> "Position":
        return cls(**dict(zip(columns, row)))

@dataclass
class Trade:
    id: Optional[int] = None
    position_id: int = 0
    trade_type: str = ""  # BUY, SELL, TP, SL
    token_address: str = ""
    symbol: str = ""
    chain: str = ""
    price: float = 0
    quantity: float = 0
    value: float = 0
    fee: float = 0
    slippage: float = 0
    tx_hash: Optional[str] = None
    timestamp: str = ""
    
    @classmethod
    def from_row(cls, row: tuple, columns: List[str]) -> "Trade":
        return cls(**dict(zip(columns, row)))

@dataclass
class SmartWallet:
    address: str = ""
    chain: str = ""
    total_trades: int = 0
    winning_trades: int = 0
    total_profit: float = 0
    win_rate: float = 0
    avg_return: float = 0
    last_trade: str = ""
    tags: str = "[]"
    
    @classmethod
    def from_row(cls, row: tuple, columns: List[str]) -> "SmartWallet":
        return cls(**dict(zip(columns, row)))

@dataclass
class DailyStats:
    date: str = ""
    starting_capital: float = 0
    ending_capital: float = 0
    total_pnl: float = 0
    pnl_percent: float = 0
    trades_count: int = 0
    winners: int = 0
    losers: int = 0
    win_rate: float = 0
    safe_pnl: float = 0
    hunt_pnl: float = 0
    tokens_scanned: int = 0
    tokens_rejected: int = 0


class Database:
    """Async SQLite database manager"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DATABASE_CONFIG.path
        self.connection: Optional[aiosqlite.Connection] = None
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
    
    async def connect(self):
        self.connection = await aiosqlite.connect(self.db_path)
        self.connection.row_factory = aiosqlite.Row
        await self._create_tables()
        logger.info(f"Database connected: {self.db_path}")
    
    async def close(self):
        if self.connection:
            await self.connection.close()
            self.connection = None
    
    async def _create_tables(self):
        await self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address TEXT NOT NULL,
                symbol TEXT NOT NULL,
                chain TEXT NOT NULL,
                pool TEXT NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL DEFAULT 0,
                quantity REAL NOT NULL,
                entry_value REAL NOT NULL,
                current_value REAL DEFAULT 0,
                pnl_percent REAL DEFAULT 0,
                pnl_usd REAL DEFAULT 0,
                highest_price REAL DEFAULT 0,
                stop_loss REAL NOT NULL,
                entry_time TEXT NOT NULL,
                status TEXT DEFAULT 'OPEN',
                tp_levels_hit TEXT DEFAULT '[]',
                exit_time TEXT,
                exit_price REAL,
                exit_reason TEXT,
                total_sold REAL DEFAULT 0,
                remaining_quantity REAL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER,
                trade_type TEXT NOT NULL,
                token_address TEXT NOT NULL,
                symbol TEXT NOT NULL,
                chain TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                value REAL NOT NULL,
                fee REAL DEFAULT 0,
                slippage REAL DEFAULT 0,
                tx_hash TEXT,
                timestamp TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (position_id) REFERENCES positions(id)
            );
            
            CREATE TABLE IF NOT EXISTS smart_wallets (
                address TEXT PRIMARY KEY,
                chain TEXT NOT NULL,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                total_profit REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                avg_return REAL DEFAULT 0,
                last_trade TEXT,
                tags TEXT DEFAULT '[]',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                starting_capital REAL NOT NULL,
                ending_capital REAL NOT NULL,
                total_pnl REAL DEFAULT 0,
                pnl_percent REAL DEFAULT 0,
                trades_count INTEGER DEFAULT 0,
                winners INTEGER DEFAULT 0,
                losers INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0,
                safe_pnl REAL DEFAULT 0,
                hunt_pnl REAL DEFAULT 0,
                tokens_scanned INTEGER DEFAULT 0,
                tokens_rejected INTEGER DEFAULT 0
            );
            
            CREATE TABLE IF NOT EXISTS token_cache (
                address TEXT PRIMARY KEY,
                chain TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
            CREATE INDEX IF NOT EXISTS idx_positions_chain ON positions(chain);
            CREATE INDEX IF NOT EXISTS idx_trades_position ON trades(position_id);
            CREATE INDEX IF NOT EXISTS idx_smart_wallets_chain ON smart_wallets(chain);
        """)
        await self.connection.commit()
    
    # ============================================================
    # POSITION OPERATIONS
    # ============================================================
    
    async def create_position(self, position: Position) -> int:
        cursor = await self.connection.execute("""
            INSERT INTO positions (token_address, symbol, chain, pool, entry_price, 
                current_price, quantity, entry_value, current_value, highest_price, 
                stop_loss, entry_time, status, remaining_quantity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (position.token_address, position.symbol, position.chain, position.pool,
              position.entry_price, position.entry_price, position.quantity,
              position.entry_value, position.entry_value, position.entry_price,
              position.stop_loss, position.entry_time, "OPEN", position.quantity))
        await self.connection.commit()
        return cursor.lastrowid
    
    async def get_position(self, position_id: int) -> Optional[Position]:
        cursor = await self.connection.execute(
            "SELECT * FROM positions WHERE id = ?", (position_id,))
        row = await cursor.fetchone()
        if row:
            return Position.from_row(tuple(row), [d[0] for d in cursor.description])
        return None
    
    async def get_open_positions(self, chain: Optional[str] = None) -> List[Position]:
        if chain:
            cursor = await self.connection.execute(
                "SELECT * FROM positions WHERE status = 'OPEN' AND chain = ?", (chain,))
        else:
            cursor = await self.connection.execute(
                "SELECT * FROM positions WHERE status = 'OPEN'")
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [Position.from_row(tuple(row), columns) for row in rows]
    
    async def update_position(self, position_id: int, **kwargs):
        sets = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [position_id]
        await self.connection.execute(
            f"UPDATE positions SET {sets} WHERE id = ?", values)
        await self.connection.commit()
    
    async def close_position(self, position_id: int, exit_price: float, 
                            exit_reason: str, pnl_usd: float):
        await self.connection.execute("""
            UPDATE positions SET status = 'CLOSED', exit_time = ?, exit_price = ?,
                exit_reason = ?, pnl_usd = ?, current_price = ?, 
                pnl_percent = ((? - entry_price) / entry_price * 100)
            WHERE id = ?
        """, (datetime.utcnow().isoformat(), exit_price, exit_reason, pnl_usd,
              exit_price, exit_price, position_id))
        await self.connection.commit()
    
    async def get_position_count(self, pool: Optional[str] = None) -> int:
        if pool:
            cursor = await self.connection.execute(
                "SELECT COUNT(*) FROM positions WHERE status = 'OPEN' AND pool = ?", (pool,))
        else:
            cursor = await self.connection.execute(
                "SELECT COUNT(*) FROM positions WHERE status = 'OPEN'")
        row = await cursor.fetchone()
        return row[0] if row else 0
    
    # ============================================================
    # TRADE OPERATIONS
    # ============================================================
    
    async def record_trade(self, trade: Trade) -> int:
        cursor = await self.connection.execute("""
            INSERT INTO trades (position_id, trade_type, token_address, symbol, chain,
                price, quantity, value, fee, slippage, tx_hash, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (trade.position_id, trade.trade_type, trade.token_address, trade.symbol,
              trade.chain, trade.price, trade.quantity, trade.value, trade.fee,
              trade.slippage, trade.tx_hash, trade.timestamp))
        await self.connection.commit()
        return cursor.lastrowid
    
    async def get_trades_for_position(self, position_id: int) -> List[Trade]:
        cursor = await self.connection.execute(
            "SELECT * FROM trades WHERE position_id = ? ORDER BY timestamp", (position_id,))
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [Trade.from_row(tuple(row), columns) for row in rows]
    
    async def get_today_trades(self) -> List[Trade]:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cursor = await self.connection.execute(
            "SELECT * FROM trades WHERE timestamp LIKE ? ORDER BY timestamp", (f"{today}%",))
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [Trade.from_row(tuple(row), columns) for row in rows]
    
    # ============================================================
    # SMART WALLET OPERATIONS
    # ============================================================
    
    async def upsert_smart_wallet(self, wallet: SmartWallet):
        await self.connection.execute("""
            INSERT OR REPLACE INTO smart_wallets 
                (address, chain, total_trades, winning_trades, total_profit, 
                 win_rate, avg_return, last_trade, tags, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (wallet.address, wallet.chain, wallet.total_trades, wallet.winning_trades,
              wallet.total_profit, wallet.win_rate, wallet.avg_return, 
              wallet.last_trade, wallet.tags))
        await self.connection.commit()
    
    async def get_smart_wallets(self, chain: Optional[str] = None, 
                                min_win_rate: float = 0.5) -> List[SmartWallet]:
        if chain:
            cursor = await self.connection.execute(
                "SELECT * FROM smart_wallets WHERE chain = ? AND win_rate >= ?",
                (chain, min_win_rate))
        else:
            cursor = await self.connection.execute(
                "SELECT * FROM smart_wallets WHERE win_rate >= ?", (min_win_rate,))
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [SmartWallet.from_row(tuple(row), columns) for row in rows]
    
    async def get_smart_wallet(self, address: str) -> Optional[SmartWallet]:
        cursor = await self.connection.execute(
            "SELECT * FROM smart_wallets WHERE address = ?", (address,))
        row = await cursor.fetchone()
        if row:
            return SmartWallet.from_row(tuple(row), [d[0] for d in cursor.description])
        return None
    
    # ============================================================
    # DAILY STATS OPERATIONS
    # ============================================================
    
    async def save_daily_stats(self, stats: DailyStats):
        await self.connection.execute("""
            INSERT OR REPLACE INTO daily_stats
                (date, starting_capital, ending_capital, total_pnl, pnl_percent,
                 trades_count, winners, losers, win_rate, safe_pnl, hunt_pnl,
                 tokens_scanned, tokens_rejected)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (stats.date, stats.starting_capital, stats.ending_capital, stats.total_pnl,
              stats.pnl_percent, stats.trades_count, stats.winners, stats.losers,
              stats.win_rate, stats.safe_pnl, stats.hunt_pnl, stats.tokens_scanned,
              stats.tokens_rejected))
        await self.connection.commit()
    
    async def get_daily_stats(self, date: str) -> Optional[DailyStats]:
        cursor = await self.connection.execute(
            "SELECT * FROM daily_stats WHERE date = ?", (date,))
        row = await cursor.fetchone()
        if row:
            return DailyStats(**dict(zip([d[0] for d in cursor.description], row)))
        return None
    
    async def get_stats_range(self, start_date: str, end_date: str) -> List[DailyStats]:
        cursor = await self.connection.execute(
            "SELECT * FROM daily_stats WHERE date BETWEEN ? AND ? ORDER BY date",
            (start_date, end_date))
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [DailyStats(**dict(zip(columns, row))) for row in rows]
    
    # ============================================================
    # TOKEN CACHE OPERATIONS
    # ============================================================
    
    async def cache_token(self, address: str, chain: str, data: Dict):
        await self.connection.execute("""
            INSERT OR REPLACE INTO token_cache (address, chain, data, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (address, chain, json.dumps(data)))
        await self.connection.commit()
    
    async def get_cached_token(self, address: str, max_age_seconds: int = 300) -> Optional[Dict]:
        cursor = await self.connection.execute("""
            SELECT data, updated_at FROM token_cache 
            WHERE address = ? AND updated_at > datetime('now', ?)
        """, (address, f"-{max_age_seconds} seconds"))
        row = await cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None
    
    # ============================================================
    # ANALYTICS
    # ============================================================
    
    async def get_performance_summary(self, days: int = 30) -> Dict:
        start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        cursor = await self.connection.execute("""
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as winners,
                SUM(CASE WHEN pnl_usd <= 0 THEN 1 ELSE 0 END) as losers,
                SUM(pnl_usd) as total_pnl,
                AVG(pnl_percent) as avg_return,
                MAX(pnl_percent) as best_trade,
                MIN(pnl_percent) as worst_trade
            FROM positions 
            WHERE status = 'CLOSED' AND entry_time >= ?
        """, (start_date,))
        row = await cursor.fetchone()
        
        if row:
            total = row[0] or 0
            winners = row[1] or 0
            return {
                "total_trades": total,
                "winners": winners,
                "losers": row[2] or 0,
                "win_rate": (winners / total * 100) if total > 0 else 0,
                "total_pnl": row[3] or 0,
                "avg_return": row[4] or 0,
                "best_trade": row[5] or 0,
                "worst_trade": row[6] or 0
            }
        return {}


# Singleton instance
_database: Optional[Database] = None

async def get_database() -> Database:
    global _database
    if _database is None:
        _database = Database()
        await _database.connect()
    return _database

async def shutdown_database():
    global _database
    if _database:
        await _database.close()
        _database = None
