"""
Moonshot Sniper Bot - DEXScreener Scanner
Token discovery, price data, and market analytics
"""

import asyncio
import aiohttp
import time
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging

from config.settings import Chain, API_CONFIG

logger = logging.getLogger(__name__)

@dataclass
class TokenPair:
    """Trading pair from DEXScreener"""
    chain_id: str = ""
    dex_id: str = ""
    pair_address: str = ""
    base_token_address: str = ""
    base_token_symbol: str = ""
    base_token_name: str = ""
    quote_token_address: str = ""
    quote_token_symbol: str = ""
    price_usd: float = 0
    price_native: float = 0
    liquidity_usd: float = 0
    fdv: float = 0
    market_cap: float = 0
    volume_24h: float = 0
    volume_6h: float = 0
    volume_1h: float = 0
    volume_5m: float = 0
    price_change_5m: float = 0
    price_change_1h: float = 0
    price_change_6h: float = 0
    price_change_24h: float = 0
    txns_buys_5m: int = 0
    txns_sells_5m: int = 0
    txns_buys_1h: int = 0
    txns_sells_1h: int = 0
    txns_buys_24h: int = 0
    txns_sells_24h: int = 0
    created_at: Optional[datetime] = None
    pair_url: str = ""
    
    @property
    def age_minutes(self) -> float:
        if not self.created_at: return float('inf')
        return (datetime.utcnow() - self.created_at).total_seconds() / 60
    
    @property
    def buy_pressure_5m(self) -> float:
        total = self.txns_buys_5m + self.txns_sells_5m
        return self.txns_buys_5m / total if total > 0 else 0.5
    
    @property
    def buy_pressure_1h(self) -> float:
        total = self.txns_buys_1h + self.txns_sells_1h
        return self.txns_buys_1h / total if total > 0 else 0.5
    
    @property
    def volume_trend(self) -> str:
        """Analyze volume trend"""
        if self.volume_1h > self.volume_6h / 6 * 2:
            return "INCREASING"
        elif self.volume_1h < self.volume_6h / 6 * 0.5:
            return "DECREASING"
        return "STABLE"
    
    @classmethod
    def from_api(cls, data: Dict) -> "TokenPair":
        created_at = None
        if data.get("pairCreatedAt"):
            try:
                created_at = datetime.fromtimestamp(data["pairCreatedAt"] / 1000)
            except: pass
        
        volume = data.get("volume", {})
        price_change = data.get("priceChange", {})
        txns = data.get("txns", {})
        
        return cls(
            chain_id=data.get("chainId", ""),
            dex_id=data.get("dexId", ""),
            pair_address=data.get("pairAddress", ""),
            base_token_address=data.get("baseToken", {}).get("address", ""),
            base_token_symbol=data.get("baseToken", {}).get("symbol", ""),
            base_token_name=data.get("baseToken", {}).get("name", ""),
            quote_token_address=data.get("quoteToken", {}).get("address", ""),
            quote_token_symbol=data.get("quoteToken", {}).get("symbol", ""),
            price_usd=float(data.get("priceUsd", 0) or 0),
            price_native=float(data.get("priceNative", 0) or 0),
            liquidity_usd=float(data.get("liquidity", {}).get("usd", 0) or 0),
            fdv=float(data.get("fdv", 0) or 0),
            market_cap=float(data.get("marketCap", 0) or 0),
            volume_24h=float(volume.get("h24", 0) or 0),
            volume_6h=float(volume.get("h6", 0) or 0),
            volume_1h=float(volume.get("h1", 0) or 0),
            volume_5m=float(volume.get("m5", 0) or 0),
            price_change_5m=float(price_change.get("m5", 0) or 0),
            price_change_1h=float(price_change.get("h1", 0) or 0),
            price_change_6h=float(price_change.get("h6", 0) or 0),
            price_change_24h=float(price_change.get("h24", 0) or 0),
            txns_buys_5m=int(txns.get("m5", {}).get("buys", 0) or 0),
            txns_sells_5m=int(txns.get("m5", {}).get("sells", 0) or 0),
            txns_buys_1h=int(txns.get("h1", {}).get("buys", 0) or 0),
            txns_sells_1h=int(txns.get("h1", {}).get("sells", 0) or 0),
            txns_buys_24h=int(txns.get("h24", {}).get("buys", 0) or 0),
            txns_sells_24h=int(txns.get("h24", {}).get("sells", 0) or 0),
            created_at=created_at,
            pair_url=data.get("url", "")
        )
    
    def to_dict(self) -> Dict:
        return {
            "chain": self.chain_id, "dex": self.dex_id,
            "pair": self.pair_address, "token": self.base_token_address,
            "symbol": self.base_token_symbol, "name": self.base_token_name,
            "price": self.price_usd, "liquidity": self.liquidity_usd,
            "volume_1h": self.volume_1h, "volume_24h": self.volume_24h,
            "change_5m": self.price_change_5m, "change_1h": self.price_change_1h,
            "buy_pressure_5m": self.buy_pressure_5m, "buy_pressure_1h": self.buy_pressure_1h,
            "age_minutes": self.age_minutes, "url": self.pair_url
        }


class DEXScreenerClient:
    """DEXScreener API client for token discovery"""
    
    CHAIN_MAP = {Chain.SOL: "solana", Chain.BSC: "bsc", Chain.BASE: "base"}
    
    def __init__(self):
        self.base_url = API_CONFIG.dexscreener_base
        self.rate_limit = API_CONFIG.dexscreener_rate_limit
        self.session: Optional[aiohttp.ClientSession] = None
        self.request_times: List[float] = []
        self.seen_pairs: Dict[str, datetime] = {}
    
    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    
    async def stop(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    def _check_rate_limit(self) -> bool:
        now = time.time()
        self.request_times = [t for t in self.request_times if now - t < 60]
        return len(self.request_times) < self.rate_limit
    
    async def _request(self, endpoint: str) -> Optional[Dict]:
        if not self.session: await self.start()
        if not self._check_rate_limit():
            await asyncio.sleep(1)
        
        self.request_times.append(time.time())
        url = f"{self.base_url}/{endpoint}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    await asyncio.sleep(5)
        except Exception as e:
            logger.warning(f"DEXScreener error: {e}")
        return None
    
    async def get_token_pairs(self, chain: Chain, token_address: str) -> List[TokenPair]:
        chain_id = self.CHAIN_MAP.get(chain)
        if not chain_id: return []
        
        data = await self._request(f"dex/tokens/{token_address}")
        if not data or "pairs" not in data: return []
        
        pairs = []
        for pair_data in data["pairs"]:
            if pair_data.get("chainId") == chain_id:
                try:
                    pairs.append(TokenPair.from_api(pair_data))
                except: pass
        return pairs
    
    async def get_pair(self, chain: Chain, pair_address: str) -> Optional[TokenPair]:
        chain_id = self.CHAIN_MAP.get(chain)
        if not chain_id: return None
        
        data = await self._request(f"dex/pairs/{chain_id}/{pair_address}")
        if data and "pairs" in data and data["pairs"]:
            return TokenPair.from_api(data["pairs"][0])
        return None
    
    async def get_price(self, chain: Chain, token_address: str) -> Optional[float]:
        pairs = await self.get_token_pairs(chain, token_address)
        if pairs:
            # Return price from pair with highest liquidity
            best = max(pairs, key=lambda p: p.liquidity_usd)
            return best.price_usd
        return None
    
    async def search_tokens(self, query: str) -> List[TokenPair]:
        data = await self._request(f"dex/search?q={query}")
        if not data or "pairs" not in data: return []
        return [TokenPair.from_api(p) for p in data["pairs"][:20]]
    
    async def get_new_pairs(self, chain: Chain, max_age_minutes: int = 60) -> List[TokenPair]:
        """Get new pairs created within max_age_minutes"""
        chain_id = self.CHAIN_MAP.get(chain)
        if not chain_id: return []
        
        data = await self._request(f"dex/pairs/{chain_id}")
        if not data or "pairs" not in data: return []
        
        pairs = []
        for pair_data in data["pairs"]:
            try:
                pair = TokenPair.from_api(pair_data)
                if pair.age_minutes <= max_age_minutes:
                    pairs.append(pair)
            except: pass
        
        pairs.sort(key=lambda p: p.created_at or datetime.min, reverse=True)
        return pairs
    
    async def get_trending(self, chain: Chain, limit: int = 50) -> List[TokenPair]:
        """Get trending tokens by volume"""
        chain_id = self.CHAIN_MAP.get(chain)
        if not chain_id: return []
        
        data = await self._request(f"dex/pairs/{chain_id}")
        if not data or "pairs" not in data: return []
        
        pairs = [TokenPair.from_api(p) for p in data["pairs"] if p.get("liquidity", {}).get("usd", 0) > 1000]
        pairs.sort(key=lambda p: p.volume_1h, reverse=True)
        return pairs[:limit]
    
    async def get_gainers(self, chain: Chain, timeframe: str = "1h", limit: int = 20) -> List[TokenPair]:
        """Get top gainers"""
        pairs = await self.get_trending(chain, 100)
        
        attr_map = {"5m": "price_change_5m", "1h": "price_change_1h", 
                   "6h": "price_change_6h", "24h": "price_change_24h"}
        attr = attr_map.get(timeframe, "price_change_1h")
        
        pairs.sort(key=lambda p: getattr(p, attr, 0), reverse=True)
        return [p for p in pairs if getattr(p, attr, 0) > 0][:limit]
    
    async def scan_new_tokens(self, chains: List[Chain], 
                              min_liquidity: float = 3000,
                              max_age_minutes: int = 30) -> List[tuple]:
        """Scan all chains for new tokens meeting criteria"""
        results = []
        
        for chain in chains:
            pairs = await self.get_new_pairs(chain, max_age_minutes)
            
            for pair in pairs:
                # Skip if already seen recently
                if pair.pair_address in self.seen_pairs:
                    if (datetime.utcnow() - self.seen_pairs[pair.pair_address]).seconds < 300:
                        continue
                
                # Check minimum liquidity
                if pair.liquidity_usd < min_liquidity:
                    continue
                
                self.seen_pairs[pair.pair_address] = datetime.utcnow()
                results.append((chain, pair))
        
        # Clean old seen pairs
        if len(self.seen_pairs) > 5000:
            cutoff = datetime.utcnow()
            self.seen_pairs = {k: v for k, v in self.seen_pairs.items() 
                             if (cutoff - v).seconds < 3600}
        
        return results
    
    async def get_holder_info(self, chain: Chain, token_address: str) -> Dict:
        """Get holder distribution info (estimated from transactions)"""
        pairs = await self.get_token_pairs(chain, token_address)
        if not pairs: return {}
        
        pair = max(pairs, key=lambda p: p.liquidity_usd)
        
        # Estimate based on transaction patterns
        total_txns = pair.txns_buys_24h + pair.txns_sells_24h
        
        return {
            "estimated_holders": max(20, total_txns // 5),
            "daily_transactions": total_txns,
            "buy_sell_ratio": pair.buy_pressure_1h,
            "liquidity": pair.liquidity_usd
        }


# Singleton
_dexscreener: Optional[DEXScreenerClient] = None

def get_dexscreener() -> DEXScreenerClient:
    global _dexscreener
    if _dexscreener is None:
        _dexscreener = DEXScreenerClient()
    return _dexscreener

async def shutdown_dexscreener():
    global _dexscreener
    if _dexscreener:
        await _dexscreener.stop()
        _dexscreener = None
