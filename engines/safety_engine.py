"""
Moonshot Sniper Bot - Safety Engine
Comprehensive contract security analysis using GoPlus API
"""

import asyncio
import aiohttp
import time
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

from config.settings import Chain, API_CONFIG, TRADING_CONFIG

logger = logging.getLogger(__name__)

class SafetyStatus(Enum):
    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"
    UNKNOWN = "unknown"

@dataclass
class SafetyCheck:
    name: str
    passed: bool
    value: Any
    message: str
    severity: str = "high"  # high, medium, low

@dataclass
class SafetyReport:
    token_address: str
    chain: Chain
    status: SafetyStatus = SafetyStatus.UNKNOWN
    checks: List[SafetyCheck] = field(default_factory=list)
    score: int = 0
    
    # Quick flags
    is_honeypot: bool = False
    has_mint: bool = False
    is_proxy: bool = False
    can_pause: bool = False
    has_blacklist: bool = False
    tax_buy: float = 0
    tax_sell: float = 0
    owner_address: Optional[str] = None
    is_renounced: bool = False
    lp_locked: bool = False
    lp_lock_days: int = 0
    holder_count: int = 0
    top_holder_percent: float = 0
    analyzed_at: float = field(default_factory=time.time)
    
    @property
    def is_safe(self) -> bool:
        return self.status == SafetyStatus.SAFE
    
    @property
    def failed_checks(self) -> List[SafetyCheck]:
        return [c for c in self.checks if not c.passed]
    
    def to_dict(self) -> Dict:
        return {
            "token": self.token_address, "chain": self.chain.value,
            "status": self.status.value, "score": self.score,
            "honeypot": self.is_honeypot, "mint": self.has_mint,
            "tax_buy": self.tax_buy, "tax_sell": self.tax_sell,
            "renounced": self.is_renounced, "lp_locked": self.lp_locked,
            "holders": self.holder_count, "top_holder": self.top_holder_percent,
            "failed": [c.name for c in self.failed_checks]
        }


class SafetyEngine:
    """Contract safety analysis using GoPlus Security API"""
    
    CHAIN_MAP = {Chain.SOL: "solana", Chain.BSC: "56", Chain.BASE: "8453"}
    
    def __init__(self):
        self.base_url = API_CONFIG.goplus_base
        self.rate_limit = API_CONFIG.goplus_rate_limit
        self.session: Optional[aiohttp.ClientSession] = None
        self.request_times: List[float] = []
        self.cache: Dict[str, SafetyReport] = {}
        self.cache_ttl: int = 300
    
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
    
    async def _request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        if not self.session: await self.start()
        if not self._check_rate_limit():
            await asyncio.sleep(1)
        
        self.request_times.append(time.time())
        url = f"{self.base_url}/{endpoint}"
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 1:
                        return data.get("result", {})
        except Exception as e:
            logger.warning(f"GoPlus error: {e}")
        return None
    
    def _get_cache(self, key: str) -> Optional[SafetyReport]:
        if key in self.cache:
            report = self.cache[key]
            if time.time() - report.analyzed_at < self.cache_ttl:
                return report
            del self.cache[key]
        return None
    
    async def analyze(self, chain: Chain, token_address: str) -> SafetyReport:
        """Full safety analysis of a token"""
        cache_key = f"{chain.value}:{token_address}"
        cached = self._get_cache(cache_key)
        if cached: return cached
        
        report = SafetyReport(token_address=token_address, chain=chain)
        chain_id = self.CHAIN_MAP.get(chain)
        if not chain_id:
            report.status = SafetyStatus.UNKNOWN
            return report
        
        # Fetch security data
        if chain == Chain.SOL:
            data = await self._request(f"solana/token_security/{token_address}")
        else:
            data = await self._request(f"token_security/{chain_id}", 
                                       {"contract_addresses": token_address})
        
        if not data:
            report.status = SafetyStatus.UNKNOWN
            report.checks.append(SafetyCheck("api_response", False, None, "Failed to fetch", "high"))
            return report
        
        # Parse response
        if chain == Chain.SOL:
            self._parse_solana(report, data)
        else:
            token_data = data.get(token_address.lower(), {})
            if token_data:
                self._parse_evm(report, token_data)
            else:
                report.status = SafetyStatus.UNKNOWN
        
        # Calculate score and status
        self._calculate_score(report)
        self.cache[cache_key] = report
        
        return report
    
    def _parse_solana(self, report: SafetyReport, data: Dict):
        """Parse Solana security response"""
        # Mint authority
        mint = data.get("mintAuthority")
        has_mint = mint is not None and mint != ""
        report.has_mint = has_mint
        report.checks.append(SafetyCheck("mint_function", not has_mint, mint,
            "Mint authority exists" if has_mint else "No mint", "high"))
        
        # Freeze authority
        freeze = data.get("freezeAuthority")
        has_freeze = freeze is not None and freeze != ""
        report.checks.append(SafetyCheck("freeze_authority", not has_freeze, freeze,
            "Freeze authority exists" if has_freeze else "No freeze", "high"))
        
        # LP info
        lp_info = data.get("lpInfo", {})
        if lp_info:
            lp_locked = lp_info.get("lpLocked", 0) > 50
            report.lp_locked = lp_locked
            report.checks.append(SafetyCheck("lp_locked", lp_locked,
                lp_info.get("lpLocked", 0), f"LP {lp_info.get('lpLocked', 0)}% locked", "high"))
        
        # Holders
        holders = data.get("holders", [])
        if holders:
            report.holder_count = len(holders)
            top = max(holders, key=lambda h: float(h.get("percentage", 0)), default={})
            report.top_holder_percent = float(top.get("percentage", 0))
            concentrated = report.top_holder_percent > TRADING_CONFIG.max_top_holder_percent
            report.checks.append(SafetyCheck("holder_concentration", not concentrated,
                report.top_holder_percent, f"Top: {report.top_holder_percent:.1f}%",
                "high" if concentrated else "low"))
    
    def _parse_evm(self, report: SafetyReport, data: Dict):
        """Parse EVM (BSC, Base) security response"""
        # Honeypot
        honeypot = data.get("is_honeypot") == "1"
        report.is_honeypot = honeypot
        report.checks.append(SafetyCheck("honeypot", not honeypot, honeypot,
            "HONEYPOT!" if honeypot else "Not honeypot", "high"))
        
        # Mint
        mint = data.get("is_mintable") == "1"
        report.has_mint = mint
        report.checks.append(SafetyCheck("mint_function", not mint, mint,
            "Mintable" if mint else "Not mintable", "high"))
        
        # Proxy
        proxy = data.get("is_proxy") == "1"
        report.is_proxy = proxy
        report.checks.append(SafetyCheck("proxy_contract", not proxy, proxy,
            "Proxy contract" if proxy else "Not proxy", "high"))
        
        # Pause
        pause = data.get("can_take_back_ownership") == "1" or data.get("trading_cooldown") == "1"
        report.can_pause = pause
        report.checks.append(SafetyCheck("can_pause", not pause, pause,
            "Can pause" if pause else "Cannot pause", "high"))
        
        # Blacklist
        blacklist = data.get("is_blacklisted") == "1" or data.get("is_whitelisted") == "1"
        report.has_blacklist = blacklist
        report.checks.append(SafetyCheck("blacklist", not blacklist, blacklist,
            "Has blacklist" if blacklist else "No blacklist", "medium"))
        
        # Tax
        buy_tax = float(data.get("buy_tax", 0) or 0) * 100
        sell_tax = float(data.get("sell_tax", 0) or 0) * 100
        report.tax_buy = buy_tax
        report.tax_sell = sell_tax
        high_tax = buy_tax > TRADING_CONFIG.max_tax_percent or sell_tax > TRADING_CONFIG.max_tax_percent
        report.checks.append(SafetyCheck("tax", not high_tax,
            {"buy": buy_tax, "sell": sell_tax},
            f"Tax: {buy_tax:.1f}%/{sell_tax:.1f}%", "high" if high_tax else "low"))
        
        # Ownership
        owner = data.get("owner_address", "")
        renounced = data.get("is_renounced") == "1" or owner == "0x" + "0" * 40
        report.owner_address = owner
        report.is_renounced = renounced
        report.checks.append(SafetyCheck("ownership", renounced, owner,
            "Renounced" if renounced else f"Owner: {owner[:10]}...", "medium"))
        
        # Holders
        holders = int(data.get("holder_count", 0) or 0)
        report.holder_count = holders
        enough = holders >= TRADING_CONFIG.min_holders
        report.checks.append(SafetyCheck("holder_count", enough, holders,
            f"{holders} holders", "medium"))
        
        # LP
        lp_holders = data.get("lp_holders", [])
        lp_locked = any(lp.get("is_locked") == 1 for lp in lp_holders)
        report.lp_locked = lp_locked
        report.checks.append(SafetyCheck("lp_locked", lp_locked, lp_locked,
            "LP locked" if lp_locked else "LP not locked", "high"))
    
    def _calculate_score(self, report: SafetyReport):
        """Calculate safety score (0-100)"""
        score = 100
        critical_fail = False
        
        for check in report.checks:
            if not check.passed:
                if check.severity == "high":
                    score -= 25
                    critical_fail = True
                elif check.severity == "medium":
                    score -= 10
                else:
                    score -= 5
        
        report.score = max(0, min(100, score))
        
        if report.is_honeypot:
            report.status = SafetyStatus.DANGEROUS
        elif critical_fail:
            report.status = SafetyStatus.DANGEROUS
        elif report.score >= 75:
            report.status = SafetyStatus.SAFE
        elif report.score >= 50:
            report.status = SafetyStatus.WARNING
        else:
            report.status = SafetyStatus.DANGEROUS
    
    async def quick_check(self, chain: Chain, token_address: str) -> bool:
        """Quick honeypot check"""
        if chain == Chain.SOL:
            return True  # Solana doesn't have traditional honeypots
        
        chain_id = self.CHAIN_MAP.get(chain)
        if not chain_id: return False
        
        data = await self._request(f"token_security/{chain_id}",
                                   {"contract_addresses": token_address})
        if not data: return False
        
        token_data = data.get(token_address.lower(), {})
        return token_data.get("is_honeypot") != "1"
    
    async def batch_analyze(self, chain: Chain, addresses: List[str]) -> Dict[str, SafetyReport]:
        """Analyze multiple tokens efficiently"""
        results = {}
        uncached = []
        
        for addr in addresses:
            key = f"{chain.value}:{addr}"
            cached = self._get_cache(key)
            if cached:
                results[addr] = cached
            else:
                uncached.append(addr)
        
        if uncached and chain != Chain.SOL:
            chain_id = self.CHAIN_MAP.get(chain)
            data = await self._request(f"token_security/{chain_id}",
                                       {"contract_addresses": ",".join(uncached)})
            if data:
                for addr in uncached:
                    report = SafetyReport(token_address=addr, chain=chain)
                    token_data = data.get(addr.lower(), {})
                    if token_data:
                        self._parse_evm(report, token_data)
                        self._calculate_score(report)
                    results[addr] = report
                    self.cache[f"{chain.value}:{addr}"] = report
        else:
            for addr in uncached:
                results[addr] = await self.analyze(chain, addr)
        
        return results
    
    def get_rejection_reasons(self, report: SafetyReport) -> List[str]:
        """Get human-readable rejection reasons"""
        reasons = []
        if report.is_honeypot:
            reasons.append("🚨 HONEYPOT - Cannot sell")
        if report.has_mint:
            reasons.append("⚠️ Mint function enabled")
        if report.is_proxy:
            reasons.append("⚠️ Proxy contract")
        if report.can_pause:
            reasons.append("⚠️ Can pause trading")
        if report.has_blacklist:
            reasons.append("⚠️ Has blacklist")
        if report.tax_buy > TRADING_CONFIG.max_tax_percent:
            reasons.append(f"⚠️ High buy tax: {report.tax_buy:.1f}%")
        if report.tax_sell > TRADING_CONFIG.max_tax_percent:
            reasons.append(f"⚠️ High sell tax: {report.tax_sell:.1f}%")
        if not report.lp_locked:
            reasons.append("⚠️ LP not locked")
        if report.holder_count < TRADING_CONFIG.min_holders:
            reasons.append(f"⚠️ Low holders: {report.holder_count}")
        if report.top_holder_percent > TRADING_CONFIG.max_top_holder_percent:
            reasons.append(f"⚠️ Concentrated: {report.top_holder_percent:.1f}%")
        return reasons


# Singleton
_safety_engine: Optional[SafetyEngine] = None

def get_safety_engine() -> SafetyEngine:
    global _safety_engine
    if _safety_engine is None:
        _safety_engine = SafetyEngine()
    return _safety_engine

async def shutdown_safety_engine():
    global _safety_engine
    if _safety_engine:
        await _safety_engine.stop()
        _safety_engine = None
