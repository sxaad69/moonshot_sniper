"""
Moonshot Sniper Bot - Confluence Engine
Aggregates signals from multiple sources for entry decisions
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import logging

from config.settings import (
    Chain, PoolType, SAFE_POOL, HUNT_POOL, CONFLUENCE_CONFIG, TRADING_CONFIG
)
from scanners.dexscreener import TokenPair
from engines.safety_engine import SafetyReport, SafetyStatus
from engines.scoring_engine import ScoreBreakdown
from engines.momentum_engine import MomentumSignal

logger = logging.getLogger(__name__)

@dataclass
class ConfluenceSignal:
    """Individual confluence signal"""
    name: str
    active: bool
    weight: int
    reason: str
    data: Dict = field(default_factory=dict)

@dataclass
class ConfluenceResult:
    """Result of confluence analysis"""
    token_address: str
    chain: str
    
    # Signal aggregation
    signals: List[ConfluenceSignal] = field(default_factory=list)
    active_signals: int = 0
    total_weight: int = 0
    max_weight: int = 0
    
    # Decision
    should_enter: bool = False
    recommended_pool: Optional[str] = None
    confidence: float = 0  # 0-100
    
    # Position sizing
    position_size_percent: float = 0
    risk_level: str = "MEDIUM"  # LOW, MEDIUM, HIGH
    
    # Reasons
    entry_reasons: List[str] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "token": self.token_address, "chain": self.chain,
            "should_enter": self.should_enter, "pool": self.recommended_pool,
            "confidence": self.confidence, "active_signals": self.active_signals,
            "weight": self.total_weight, "max_weight": self.max_weight,
            "position_size": self.position_size_percent, "risk": self.risk_level,
            "signals": [s.name for s in self.signals if s.active],
            "entry_reasons": self.entry_reasons,
            "rejection_reasons": self.rejection_reasons
        }


class ConfluenceEngine:
    """
    Confluence analysis engine
    Combines multiple signals to make entry decisions
    """
    
    def __init__(self):
        self.config = CONFLUENCE_CONFIG
        self.signal_weights = self.config.weights
    
    def analyze(self, chain: Chain, pair: TokenPair, safety: SafetyReport,
                score: ScoreBreakdown, momentum: MomentumSignal,
                smart_money: Dict = None) -> ConfluenceResult:
        """
        Analyze confluence of signals for entry decision
        
        Args:
            chain: Blockchain
            pair: Token pair data
            safety: Safety analysis
            score: Quality score
            momentum: Momentum analysis
            smart_money: Smart wallet signals
        
        Returns:
            ConfluenceResult with entry decision
        """
        result = ConfluenceResult(
            token_address=pair.base_token_address,
            chain=chain.value
        )
        
        # Calculate max possible weight
        result.max_weight = sum(self.signal_weights.values())
        
        # Check each signal
        self._check_safety(result, safety)
        self._check_liquidity(result, pair)
        self._check_holders(result, safety)
        self._check_volume(result, pair)
        self._check_buy_pressure(result, pair)
        self._check_momentum(result, momentum)
        self._check_smart_money(result, smart_money)
        self._check_social(result)  # Placeholder
        self._check_age(result, pair)
        self._check_red_flags(result, safety, pair)
        
        # Count active signals and weight
        result.active_signals = len([s for s in result.signals if s.active])
        result.total_weight = sum(s.weight for s in result.signals if s.active)
        
        # Make decision
        self._make_decision(result, score, pair)
        
        return result
    
    def _check_safety(self, result: ConfluenceResult, safety: SafetyReport):
        """Check safety signal"""
        active = safety.status == SafetyStatus.SAFE
        result.signals.append(ConfluenceSignal(
            name="safety_passed",
            active=active,
            weight=self.signal_weights["safety_passed"] if active else 0,
            reason="Contract verified safe" if active else f"Safety: {safety.status.value}",
            data={"score": safety.score}
        ))
        
        if not active:
            result.rejection_reasons.append(f"Safety check failed: {safety.status.value}")
    
    def _check_liquidity(self, result: ConfluenceResult, pair: TokenPair):
        """Check liquidity signal"""
        min_liq = TRADING_CONFIG.min_liquidity_usd
        active = pair.liquidity_usd >= min_liq
        
        # Extra check for suspicious liquidity
        suspicious = pair.liquidity_usd > pair.volume_24h * 10 and pair.volume_24h < 1000
        
        result.signals.append(ConfluenceSignal(
            name="liquidity_healthy",
            active=active and not suspicious,
            weight=self.signal_weights["liquidity_healthy"] if (active and not suspicious) else 0,
            reason=f"Liquidity: ${pair.liquidity_usd:,.0f}",
            data={"liquidity": pair.liquidity_usd}
        ))
        
        if not active:
            result.rejection_reasons.append(f"Low liquidity: ${pair.liquidity_usd:,.0f}")
        if suspicious:
            result.rejection_reasons.append("Suspicious liquidity pattern")
    
    def _check_holders(self, result: ConfluenceResult, safety: SafetyReport):
        """Check holder distribution signal"""
        active = (safety.holder_count >= TRADING_CONFIG.min_holders and
                 safety.top_holder_percent <= TRADING_CONFIG.max_top_holder_percent)
        
        result.signals.append(ConfluenceSignal(
            name="holders_distributed",
            active=active,
            weight=self.signal_weights["holders_distributed"] if active else 0,
            reason=f"{safety.holder_count} holders, top: {safety.top_holder_percent:.1f}%",
            data={"holders": safety.holder_count, "top": safety.top_holder_percent}
        ))
        
        if safety.holder_count < TRADING_CONFIG.min_holders:
            result.rejection_reasons.append(f"Too few holders: {safety.holder_count}")
        if safety.top_holder_percent > TRADING_CONFIG.max_top_holder_percent:
            result.rejection_reasons.append(f"Too concentrated: {safety.top_holder_percent:.1f}%")
    
    def _check_volume(self, result: ConfluenceResult, pair: TokenPair):
        """Check volume trend signal"""
        vol_trend = pair.volume_trend
        active = vol_trend == "INCREASING" or (vol_trend == "STABLE" and pair.volume_1h > 1000)
        
        result.signals.append(ConfluenceSignal(
            name="volume_increasing",
            active=active,
            weight=self.signal_weights["volume_increasing"] if active else 0,
            reason=f"Volume {vol_trend}: ${pair.volume_1h:,.0f}/h",
            data={"trend": vol_trend, "volume_1h": pair.volume_1h}
        ))
    
    def _check_buy_pressure(self, result: ConfluenceResult, pair: TokenPair):
        """Check buy pressure signal"""
        bp = pair.buy_pressure_1h
        active = bp >= 0.55
        
        result.signals.append(ConfluenceSignal(
            name="buy_pressure_high",
            active=active,
            weight=self.signal_weights["buy_pressure_high"] if active else 0,
            reason=f"Buy pressure: {bp*100:.0f}%",
            data={"buy_pressure": bp}
        ))
        
        if bp < 0.4:
            result.rejection_reasons.append(f"Heavy selling: {bp*100:.0f}% buys")
    
    def _check_momentum(self, result: ConfluenceResult, momentum: MomentumSignal):
        """Check momentum signal"""
        active = momentum.trend == "BULLISH" or momentum.signal in ["BUY", "STRONG_BUY"]
        
        result.signals.append(ConfluenceSignal(
            name="momentum_bullish",
            active=active,
            weight=self.signal_weights["momentum_bullish"] if active else 0,
            reason=f"Momentum: {momentum.signal} ({momentum.confidence:.0f}%)",
            data={"signal": momentum.signal, "confidence": momentum.confidence}
        ))
        
        if momentum.is_dumping:
            result.rejection_reasons.append(f"Price dumping: {momentum.price_change_5m:.1f}%")
    
    def _check_smart_money(self, result: ConfluenceResult, smart_money: Dict):
        """Check smart wallet signal"""
        if not smart_money:
            result.signals.append(ConfluenceSignal(
                name="smart_money_buying", active=False, weight=0,
                reason="No smart wallet data"
            ))
            return
        
        buying = smart_money.get("smart_wallets_buying", 0)
        active = buying >= 2
        
        result.signals.append(ConfluenceSignal(
            name="smart_money_buying",
            active=active,
            weight=self.signal_weights["smart_money_buying"] if active else 0,
            reason=f"{buying} smart wallets buying" if buying > 0 else "No smart wallet activity",
            data=smart_money
        ))
        
        if active:
            result.entry_reasons.append(f"Smart money: {buying} wallets buying")
    
    def _check_social(self, result: ConfluenceResult):
        """Check social signals (placeholder)"""
        # Would integrate with Twitter/Telegram APIs
        result.signals.append(ConfluenceSignal(
            name="social_buzz", active=False, weight=0,
            reason="Social data not available"
        ))
    
    def _check_age(self, result: ConfluenceResult, pair: TokenPair):
        """Check token age signal"""
        age = pair.age_minutes
        
        # Fresh for HUNT pool (0-30 min), or established for SAFE pool (30-240 min)
        fresh = age <= 30
        established = 30 <= age <= 240
        active = fresh or established
        
        result.signals.append(ConfluenceSignal(
            name="fresh_token",
            active=active,
            weight=self.signal_weights["fresh_token"] if active else 0,
            reason=f"Age: {age:.0f} min ({'fresh' if fresh else 'established'})",
            data={"age_minutes": age, "fresh": fresh}
        ))
        
        if age > 240:
            result.rejection_reasons.append(f"Token too old: {age:.0f} min")
    
    def _check_red_flags(self, result: ConfluenceResult, safety: SafetyReport, pair: TokenPair):
        """Check for red flags"""
        red_flags = []
        
        if safety.has_mint:
            red_flags.append("Mint function")
        if safety.is_proxy:
            red_flags.append("Proxy contract")
        if safety.can_pause:
            red_flags.append("Can pause trading")
        if safety.tax_buy > 5 or safety.tax_sell > 5:
            red_flags.append(f"High tax: {safety.tax_buy}/{safety.tax_sell}%")
        if pair.price_change_5m < -20:
            red_flags.append(f"Recent dump: {pair.price_change_5m:.1f}%")
        
        active = len(red_flags) == 0
        
        result.signals.append(ConfluenceSignal(
            name="no_red_flags",
            active=active,
            weight=self.signal_weights["no_red_flags"] if active else 0,
            reason="No red flags" if active else f"Red flags: {', '.join(red_flags)}",
            data={"flags": red_flags}
        ))
        
        for flag in red_flags:
            result.rejection_reasons.append(f"Red flag: {flag}")
    
    def _make_decision(self, result: ConfluenceResult, score: ScoreBreakdown, pair: TokenPair):
        """Make entry decision based on signals"""
        
        # Check for hard rejections
        if result.rejection_reasons:
            # Check if any are critical
            critical_rejections = [r for r in result.rejection_reasons 
                                  if any(k in r.lower() for k in ["honeypot", "safety", "concentrated", "dump"])]
            if critical_rejections:
                result.should_enter = False
                result.confidence = 0
                return
        
        # Calculate confidence
        weight_ratio = result.total_weight / result.max_weight if result.max_weight > 0 else 0
        result.confidence = weight_ratio * 100
        
        # Determine pool
        age = pair.age_minutes
        if age <= 30:
            # HUNT pool candidate
            if (result.active_signals >= HUNT_POOL.min_confluence and 
                score.total_score >= HUNT_POOL.min_score):
                result.should_enter = True
                result.recommended_pool = "HUNT"
                result.position_size_percent = HUNT_POOL.position_size_percent
                result.risk_level = "HIGH"
                result.entry_reasons.append(f"Fresh token ({age:.0f}m) with {result.active_signals} signals")
        else:
            # SAFE pool candidate
            if (result.active_signals >= SAFE_POOL.min_confluence and 
                score.total_score >= SAFE_POOL.min_score):
                result.should_enter = True
                result.recommended_pool = "SAFE"
                result.position_size_percent = SAFE_POOL.position_size_percent
                result.risk_level = "MEDIUM"
                result.entry_reasons.append(f"Established token with {result.active_signals} signals")
        
        # Adjust position size based on confidence
        if result.should_enter:
            if result.confidence >= 80:
                result.position_size_percent *= 1.2  # Increase size
                result.risk_level = "LOW" if result.recommended_pool == "SAFE" else "MEDIUM"
            elif result.confidence < 60:
                result.position_size_percent *= 0.8  # Reduce size
                result.risk_level = "HIGH"
            
            # Cap position size
            result.position_size_percent = min(result.position_size_percent, 20)
    
    def get_entry_summary(self, result: ConfluenceResult) -> str:
        """Generate human-readable entry summary"""
        if not result.should_enter:
            reasons = result.rejection_reasons[:3]
            return f"❌ SKIP: {', '.join(reasons)}"
        
        return (f"✅ ENTER {result.recommended_pool} | "
                f"Confidence: {result.confidence:.0f}% | "
                f"Signals: {result.active_signals} | "
                f"Size: {result.position_size_percent:.1f}%")


# Singleton
_confluence_engine: Optional[ConfluenceEngine] = None

def get_confluence_engine() -> ConfluenceEngine:
    global _confluence_engine
    if _confluence_engine is None:
        _confluence_engine = ConfluenceEngine()
    return _confluence_engine
