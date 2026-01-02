"""
Moonshot Sniper Bot - Smart Wallet Tracker
Track and analyze winning wallets for copy trading signals
"""

import asyncio
import aiohttp
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import json

from config.settings import Chain, API_CONFIG, SMART_WALLET_CONFIG
from core.database import get_database, SmartWallet

logger = logging.getLogger(__name__)

@dataclass
class WalletActivity:
    """Activity record for a tracked wallet"""
    wallet: str
    chain: str
    token: str
    symbol: str
    action: str  # BUY, SELL
    amount_usd: float
    price: float
    timestamp: datetime
    tx_hash: str = ""
    
    @property
    def is_whale(self) -> bool:
        return self.amount_usd >= SMART_WALLET_CONFIG.whale_size_threshold

@dataclass 
class WalletStats:
    """Performance stats for a wallet"""
    address: str
    chain: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit_usd: float = 0
    avg_hold_time_hours: float = 0
    best_return_percent: float = 0
    worst_return_percent: float = 0
    favorite_dex: str = ""
    tags: List[str] = field(default_factory=list)
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0: return 0
        return self.winning_trades / self.total_trades
    
    @property
    def avg_return(self) -> float:
        if self.total_trades == 0: return 0
        return self.total_profit_usd / self.total_trades
    
    def qualifies(self) -> bool:
        """Check if wallet qualifies as 'smart money'"""
        return (self.total_trades >= SMART_WALLET_CONFIG.min_total_trades and
                self.win_rate >= SMART_WALLET_CONFIG.min_win_rate)


class SmartWalletTracker:
    """
    Track and analyze winning wallets
    Sources: Pump.fun graduates, DEX leaderboards, known traders
    """
    
    def __init__(self):
        self.tracked_wallets: Dict[str, WalletStats] = {}
        self.recent_activity: List[WalletActivity] = []
        self.session: Optional[aiohttp.ClientSession] = None
        self.watching_tokens: Set[str] = set()
    
    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        # Load tracked wallets from database
        db = await get_database()
        wallets = await db.get_smart_wallets()
        for w in wallets:
            self.tracked_wallets[w.address] = WalletStats(
                address=w.address, chain=w.chain,
                total_trades=w.total_trades, winning_trades=w.winning_trades,
                total_profit_usd=w.total_profit,
                tags=json.loads(w.tags) if w.tags else []
            )
        logger.info(f"Smart Wallet Tracker started with {len(self.tracked_wallets)} wallets")
    
    async def stop(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    async def _request(self, url: str, headers: Dict = None) -> Optional[Dict]:
        if not self.session: await self.start()
        try:
            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
        except Exception as e:
            logger.warning(f"Wallet tracker request error: {e}")
        return None
    
    # ============================================================
    # WALLET DISCOVERY
    # ============================================================
    
    async def discover_pump_graduates(self) -> List[str]:
        """Find wallets that profited from Pump.fun tokens that graduated to Raydium"""
        # This would query Pump.fun API for recent graduates and their early buyers
        # For now, return placeholder - implement with actual API
        data = await self._request(f"{API_CONFIG.pumpfun_base}/coins/graduated")
        if not data: return []
        
        wallets = []
        for coin in data[:20]:  # Check last 20 graduates
            # Get early buyers who sold profitably
            # Implementation depends on Pump.fun API structure
            pass
        
        return wallets
    
    async def discover_dex_winners(self, chain: Chain) -> List[str]:
        """Find wallets with consistent DEX trading profits"""
        # Query Birdeye or similar for top traders
        if chain == Chain.SOL and API_CONFIG.birdeye_api_key:
            url = f"{API_CONFIG.birdeye_base}/trader/top?chain=solana"
            headers = {"x-api-key": API_CONFIG.birdeye_api_key}
            data = await self._request(url, headers)
            if data and "data" in data:
                return [t["address"] for t in data["data"][:50]]
        return []
    
    async def add_wallet(self, address: str, chain: Chain, tags: List[str] = None):
        """Add a wallet to tracking"""
        if address in self.tracked_wallets:
            return
        
        stats = WalletStats(address=address, chain=chain.value, tags=tags or [])
        self.tracked_wallets[address] = stats
        
        # Save to database
        db = await get_database()
        await db.upsert_smart_wallet(SmartWallet(
            address=address, chain=chain.value,
            tags=json.dumps(tags or [])
        ))
        
        logger.info(f"Added wallet to tracking: {address[:10]}... ({chain.value})")
    
    async def remove_wallet(self, address: str):
        """Remove wallet from tracking"""
        if address in self.tracked_wallets:
            del self.tracked_wallets[address]
    
    # ============================================================
    # ACTIVITY MONITORING
    # ============================================================
    
    async def check_wallet_activity(self, address: str, chain: Chain) -> List[WalletActivity]:
        """Check recent activity for a specific wallet"""
        activities = []
        
        if chain == Chain.SOL:
            # Query Solscan or Helius for recent transactions
            url = f"{API_CONFIG.solscan_base}/account/transactions?account={address}&limit=20"
            data = await self._request(url)
            if data:
                for tx in data:
                    # Parse swap transactions
                    # Implementation depends on API response structure
                    pass
        
        return activities
    
    async def scan_tracked_wallets(self, chain: Chain) -> List[WalletActivity]:
        """Scan all tracked wallets for recent activity"""
        activities = []
        
        chain_wallets = [w for w in self.tracked_wallets.values() 
                        if w.chain == chain.value and w.qualifies()]
        
        for wallet in chain_wallets[:SMART_WALLET_CONFIG.max_tracked_wallets]:
            wallet_activities = await self.check_wallet_activity(wallet.address, chain)
            activities.extend(wallet_activities)
            await asyncio.sleep(0.1)  # Rate limiting
        
        # Sort by timestamp
        activities.sort(key=lambda a: a.timestamp, reverse=True)
        
        # Update recent activity cache
        self.recent_activity = activities[:100]
        
        return activities
    
    # ============================================================
    # SIGNAL GENERATION
    # ============================================================
    
    async def get_smart_money_signals(self, token_address: str, chain: Chain) -> Dict:
        """Get smart money signals for a token"""
        signals = {
            "smart_wallets_buying": 0,
            "smart_wallets_selling": 0,
            "whale_buys": 0,
            "whale_sells": 0,
            "total_smart_volume_usd": 0,
            "recent_buyers": [],
            "recent_sellers": [],
            "signal_strength": 0  # -100 to +100
        }
        
        # Check recent activity for this token
        token_activities = [a for a in self.recent_activity 
                          if a.token.lower() == token_address.lower()]
        
        for activity in token_activities:
            if activity.action == "BUY":
                signals["smart_wallets_buying"] += 1
                signals["total_smart_volume_usd"] += activity.amount_usd
                signals["recent_buyers"].append(activity.wallet[:10])
                if activity.is_whale:
                    signals["whale_buys"] += 1
            else:
                signals["smart_wallets_selling"] += 1
                signals["recent_sellers"].append(activity.wallet[:10])
                if activity.is_whale:
                    signals["whale_sells"] += 1
        
        # Calculate signal strength
        buys = signals["smart_wallets_buying"]
        sells = signals["smart_wallets_selling"]
        if buys + sells > 0:
            signals["signal_strength"] = int((buys - sells) / (buys + sells) * 100)
        
        return signals
    
    async def is_smart_money_buying(self, token_address: str, chain: Chain) -> bool:
        """Quick check if smart money is accumulating"""
        signals = await self.get_smart_money_signals(token_address, chain)
        return signals["smart_wallets_buying"] >= SMART_WALLET_CONFIG.smart_money_buy_threshold
    
    # ============================================================
    # WALLET ANALYSIS
    # ============================================================
    
    async def analyze_wallet(self, address: str, chain: Chain) -> WalletStats:
        """Deep analysis of a wallet's trading history"""
        stats = WalletStats(address=address, chain=chain.value)
        
        # Get historical trades
        # This would query blockchain data / indexers
        # Implementation depends on data source
        
        return stats
    
    async def update_wallet_stats(self, address: str, trade_profit: float, is_winner: bool):
        """Update wallet stats after a trade resolves"""
        if address not in self.tracked_wallets:
            return
        
        stats = self.tracked_wallets[address]
        stats.total_trades += 1
        stats.total_profit_usd += trade_profit
        
        if is_winner:
            stats.winning_trades += 1
        else:
            stats.losing_trades += 1
        
        # Save to database
        db = await get_database()
        await db.upsert_smart_wallet(SmartWallet(
            address=address, chain=stats.chain,
            total_trades=stats.total_trades,
            winning_trades=stats.winning_trades,
            total_profit=stats.total_profit_usd,
            win_rate=stats.win_rate,
            avg_return=stats.avg_return,
            last_trade=datetime.utcnow().isoformat(),
            tags=json.dumps(stats.tags)
        ))
    
    # ============================================================
    # LEADERBOARD
    # ============================================================
    
    def get_top_wallets(self, chain: Optional[Chain] = None, limit: int = 20) -> List[WalletStats]:
        """Get top performing wallets"""
        wallets = list(self.tracked_wallets.values())
        
        if chain:
            wallets = [w for w in wallets if w.chain == chain.value]
        
        # Filter to qualified only
        wallets = [w for w in wallets if w.qualifies()]
        
        # Sort by profit
        wallets.sort(key=lambda w: w.total_profit_usd, reverse=True)
        
        return wallets[:limit]
    
    def get_wallet_count(self, chain: Optional[Chain] = None) -> int:
        """Get count of tracked wallets"""
        if chain:
            return len([w for w in self.tracked_wallets.values() if w.chain == chain.value])
        return len(self.tracked_wallets)


# Singleton
_wallet_tracker: Optional[SmartWalletTracker] = None

def get_wallet_tracker() -> SmartWalletTracker:
    global _wallet_tracker
    if _wallet_tracker is None:
        _wallet_tracker = SmartWalletTracker()
    return _wallet_tracker

async def shutdown_wallet_tracker():
    global _wallet_tracker
    if _wallet_tracker:
        await _wallet_tracker.stop()
        _wallet_tracker = None
