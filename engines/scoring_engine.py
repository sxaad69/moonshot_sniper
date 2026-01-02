"""
Moonshot Sniper Bot - Scoring Engine
Quality scoring algorithm with weighted metrics
"""

from typing import Dict, Optional, List
from dataclasses import dataclass, field
import logging

from config.settings import Chain, SCORING_WEIGHTS, TRADING_CONFIG
from scanners.dexscreener import TokenPair
from engines.safety_engine import SafetyReport, SafetyStatus

logger = logging.getLogger(__name__)

@dataclass
class ScoreBreakdown:
    """Detailed breakdown of quality score"""
    liquidity_score: int = 0
    holders_score: int = 0
    trading_score: int = 0
    momentum_score: int = 0
    social_score: int = 0
    dev_score: int = 0
    
    total_score: int = 0
    max_possible: int = 100
    
    details: Dict[str, str] = field(default_factory=dict)
    bonuses: List[str] = field(default_factory=list)
    penalties: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "total": self.total_score,
            "liquidity": self.liquidity_score,
            "holders": self.holders_score,
            "trading": self.trading_score,
            "momentum": self.momentum_score,
            "social": self.social_score,
            "dev": self.dev_score,
            "bonuses": self.bonuses,
            "penalties": self.penalties
        }


class ScoringEngine:
    """
    Token quality scoring engine
    Produces a 0-100 score based on weighted metrics
    """
    
    def __init__(self):
        self.weights = SCORING_WEIGHTS
    
    def score(self, pair: TokenPair, safety: SafetyReport,
              momentum_data: Dict = None, social_data: Dict = None,
              smart_money_data: Dict = None) -> ScoreBreakdown:
        """
        Calculate quality score for a token
        
        Args:
            pair: Token pair data from DEXScreener
            safety: Safety report from GoPlus
            momentum_data: Optional momentum analysis
            social_data: Optional social signals
            smart_money_data: Optional smart wallet data
        
        Returns:
            ScoreBreakdown with detailed scoring
        """
        breakdown = ScoreBreakdown()
        
        # 1. Liquidity Score (0-20)
        breakdown.liquidity_score = self._score_liquidity(pair, breakdown)
        
        # 2. Holders Score (0-20)
        breakdown.holders_score = self._score_holders(pair, safety, breakdown)
        
        # 3. Trading Activity Score (0-25)
        breakdown.trading_score = self._score_trading(pair, breakdown)
        
        # 4. Momentum Score (0-20)
        breakdown.momentum_score = self._score_momentum(pair, momentum_data, breakdown)
        
        # 5. Social Score (0-10)
        breakdown.social_score = self._score_social(social_data, smart_money_data, breakdown)
        
        # 6. Dev/Contract Score (0-5)
        breakdown.dev_score = self._score_dev(safety, breakdown)
        
        # Calculate total
        breakdown.total_score = (
            breakdown.liquidity_score +
            breakdown.holders_score +
            breakdown.trading_score +
            breakdown.momentum_score +
            breakdown.social_score +
            breakdown.dev_score
        )
        
        # Apply bonuses and penalties
        breakdown.total_score = self._apply_modifiers(pair, safety, breakdown)
        
        # Clamp to 0-100
        breakdown.total_score = max(0, min(100, breakdown.total_score))
        
        return breakdown
    
    def _score_liquidity(self, pair: TokenPair, breakdown: ScoreBreakdown) -> int:
        """Score liquidity (0-20)"""
        liq = pair.liquidity_usd
        max_score = self.weights.liquidity
        
        if liq < TRADING_CONFIG.min_liquidity_usd:
            breakdown.details["liquidity"] = f"Below minimum: ${liq:,.0f}"
            return 0
        
        # Scoring tiers
        if liq >= 100000:
            score = max_score
            breakdown.details["liquidity"] = f"Excellent: ${liq:,.0f}"
        elif liq >= 50000:
            score = int(max_score * 0.9)
            breakdown.details["liquidity"] = f"Very Good: ${liq:,.0f}"
        elif liq >= 20000:
            score = int(max_score * 0.75)
            breakdown.details["liquidity"] = f"Good: ${liq:,.0f}"
        elif liq >= 10000:
            score = int(max_score * 0.6)
            breakdown.details["liquidity"] = f"Adequate: ${liq:,.0f}"
        elif liq >= 5000:
            score = int(max_score * 0.4)
            breakdown.details["liquidity"] = f"Low: ${liq:,.0f}"
        else:
            score = int(max_score * 0.2)
            breakdown.details["liquidity"] = f"Very Low: ${liq:,.0f}"
        
        return score
    
    def _score_holders(self, pair: TokenPair, safety: SafetyReport,
                      breakdown: ScoreBreakdown) -> int:
        """Score holder distribution (0-20)"""
        max_score = self.weights.holders
        holders = safety.holder_count
        top_percent = safety.top_holder_percent
        
        # Holder count scoring
        if holders >= 1000:
            holder_score = max_score * 0.5
            breakdown.details["holder_count"] = f"Strong: {holders}"
        elif holders >= 500:
            holder_score = max_score * 0.4
            breakdown.details["holder_count"] = f"Good: {holders}"
        elif holders >= 200:
            holder_score = max_score * 0.3
            breakdown.details["holder_count"] = f"Moderate: {holders}"
        elif holders >= 50:
            holder_score = max_score * 0.2
            breakdown.details["holder_count"] = f"Low: {holders}"
        else:
            holder_score = max_score * 0.1
            breakdown.details["holder_count"] = f"Very Low: {holders}"
        
        # Distribution scoring
        if top_percent <= 5:
            dist_score = max_score * 0.5
            breakdown.details["distribution"] = f"Well distributed: {top_percent:.1f}%"
        elif top_percent <= 10:
            dist_score = max_score * 0.4
            breakdown.details["distribution"] = f"Good distribution: {top_percent:.1f}%"
        elif top_percent <= 15:
            dist_score = max_score * 0.25
            breakdown.details["distribution"] = f"Moderate: {top_percent:.1f}%"
        elif top_percent <= TRADING_CONFIG.max_top_holder_percent:
            dist_score = max_score * 0.1
            breakdown.details["distribution"] = f"Concentrated: {top_percent:.1f}%"
        else:
            dist_score = 0
            breakdown.penalties.append(f"Too concentrated: {top_percent:.1f}%")
        
        return int(holder_score + dist_score)
    
    def _score_trading(self, pair: TokenPair, breakdown: ScoreBreakdown) -> int:
        """Score trading activity (0-25)"""
        max_score = self.weights.trading_activity
        
        # Volume analysis
        vol_1h = pair.volume_1h
        vol_24h = pair.volume_24h
        
        # Volume to liquidity ratio (healthy = 0.5-2x daily)
        vol_liq_ratio = vol_24h / pair.liquidity_usd if pair.liquidity_usd > 0 else 0
        
        if vol_liq_ratio >= 1:
            vol_score = max_score * 0.4
            breakdown.details["volume"] = f"High activity: ${vol_1h:,.0f}/h"
        elif vol_liq_ratio >= 0.5:
            vol_score = max_score * 0.35
            breakdown.details["volume"] = f"Good activity: ${vol_1h:,.0f}/h"
        elif vol_liq_ratio >= 0.2:
            vol_score = max_score * 0.25
            breakdown.details["volume"] = f"Moderate: ${vol_1h:,.0f}/h"
        elif vol_liq_ratio >= 0.1:
            vol_score = max_score * 0.15
            breakdown.details["volume"] = f"Low: ${vol_1h:,.0f}/h"
        else:
            vol_score = max_score * 0.05
            breakdown.details["volume"] = f"Very low: ${vol_1h:,.0f}/h"
        
        # Buy pressure analysis
        buy_pressure = pair.buy_pressure_1h
        
        if buy_pressure >= 0.7:
            bp_score = max_score * 0.35
            breakdown.details["buy_pressure"] = f"Strong buying: {buy_pressure*100:.0f}%"
            breakdown.bonuses.append("Strong buy pressure")
        elif buy_pressure >= 0.6:
            bp_score = max_score * 0.3
            breakdown.details["buy_pressure"] = f"Bullish: {buy_pressure*100:.0f}%"
        elif buy_pressure >= 0.5:
            bp_score = max_score * 0.2
            breakdown.details["buy_pressure"] = f"Balanced: {buy_pressure*100:.0f}%"
        elif buy_pressure >= 0.4:
            bp_score = max_score * 0.1
            breakdown.details["buy_pressure"] = f"Bearish: {buy_pressure*100:.0f}%"
        else:
            bp_score = 0
            breakdown.details["buy_pressure"] = f"Heavy selling: {buy_pressure*100:.0f}%"
            breakdown.penalties.append("Heavy sell pressure")
        
        # Transaction count
        txn_count = pair.txns_buys_1h + pair.txns_sells_1h
        if txn_count >= 100:
            txn_score = max_score * 0.25
        elif txn_count >= 50:
            txn_score = max_score * 0.2
        elif txn_count >= 20:
            txn_score = max_score * 0.15
        else:
            txn_score = max_score * 0.05
        
        return int(vol_score + bp_score + txn_score)
    
    def _score_momentum(self, pair: TokenPair, momentum_data: Dict,
                       breakdown: ScoreBreakdown) -> int:
        """Score momentum indicators (0-20)"""
        max_score = self.weights.momentum
        
        # Price change analysis
        change_5m = pair.price_change_5m
        change_1h = pair.price_change_1h
        
        # Short-term momentum
        if change_5m > 10:
            short_score = max_score * 0.3
            breakdown.details["short_momentum"] = f"Strong pump: +{change_5m:.1f}%"
        elif change_5m > 5:
            short_score = max_score * 0.25
            breakdown.details["short_momentum"] = f"Rising: +{change_5m:.1f}%"
        elif change_5m > 0:
            short_score = max_score * 0.15
            breakdown.details["short_momentum"] = f"Slightly up: +{change_5m:.1f}%"
        elif change_5m > -5:
            short_score = max_score * 0.1
            breakdown.details["short_momentum"] = f"Flat: {change_5m:.1f}%"
        else:
            short_score = 0
            breakdown.details["short_momentum"] = f"Dumping: {change_5m:.1f}%"
        
        # Medium-term momentum
        if change_1h > 20:
            med_score = max_score * 0.35
            breakdown.bonuses.append(f"Strong 1h momentum: +{change_1h:.1f}%")
        elif change_1h > 10:
            med_score = max_score * 0.3
        elif change_1h > 0:
            med_score = max_score * 0.2
        elif change_1h > -10:
            med_score = max_score * 0.1
        else:
            med_score = 0
            breakdown.penalties.append(f"Weak 1h: {change_1h:.1f}%")
        
        # Volume trend
        vol_trend = pair.volume_trend
        if vol_trend == "INCREASING":
            trend_score = max_score * 0.35
            breakdown.details["volume_trend"] = "Volume increasing"
        elif vol_trend == "STABLE":
            trend_score = max_score * 0.2
            breakdown.details["volume_trend"] = "Volume stable"
        else:
            trend_score = max_score * 0.05
            breakdown.details["volume_trend"] = "Volume decreasing"
        
        return int(short_score + med_score + trend_score)
    
    def _score_social(self, social_data: Dict, smart_money_data: Dict,
                     breakdown: ScoreBreakdown) -> int:
        """Score social and smart money signals (0-10)"""
        max_score = self.weights.social_signals
        score = 0
        
        # Smart money signals
        if smart_money_data:
            buying = smart_money_data.get("smart_wallets_buying", 0)
            if buying >= 3:
                score += max_score * 0.5
                breakdown.bonuses.append(f"{buying} smart wallets buying")
            elif buying >= 1:
                score += max_score * 0.3
                breakdown.details["smart_money"] = f"{buying} smart wallet(s)"
        
        # Social signals (if available)
        if social_data:
            mentions = social_data.get("mentions", 0)
            sentiment = social_data.get("sentiment", 0)
            
            if mentions > 100:
                score += max_score * 0.3
                breakdown.details["social"] = f"Trending: {mentions} mentions"
            elif mentions > 20:
                score += max_score * 0.15
        
        return int(min(score, max_score))
    
    def _score_dev(self, safety: SafetyReport, breakdown: ScoreBreakdown) -> int:
        """Score developer/contract quality (0-5)"""
        max_score = self.weights.dev_reputation
        score = max_score  # Start with full score
        
        # Deduct for concerning factors
        if safety.has_mint:
            score -= 2
        if safety.is_proxy:
            score -= 2
        if not safety.lp_locked:
            score -= 1
        if not safety.is_renounced:
            score -= 1
        
        # Bonus for clean contract
        if safety.is_renounced and safety.lp_locked and not safety.has_mint:
            breakdown.bonuses.append("Clean contract")
        
        return max(0, score)
    
    def _apply_modifiers(self, pair: TokenPair, safety: SafetyReport,
                        breakdown: ScoreBreakdown) -> int:
        """Apply bonus and penalty modifiers"""
        score = breakdown.total_score
        
        # Age bonus/penalty
        age = pair.age_minutes
        if age < 10:
            score += 5
            breakdown.bonuses.append("Very fresh token")
        elif age < 30:
            score += 3
            breakdown.bonuses.append("Fresh token")
        elif age > 180:
            score -= 5
            breakdown.penalties.append("Token getting old")
        
        # Market cap consideration
        if pair.market_cap > 0:
            if pair.market_cap < 50000:
                score += 3
                breakdown.bonuses.append("Micro cap opportunity")
            elif pair.market_cap > 10000000:
                score -= 5
                breakdown.penalties.append("High cap, limited upside")
        
        # Safety status modifier
        if safety.status == SafetyStatus.SAFE:
            score += 5
        elif safety.status == SafetyStatus.WARNING:
            score -= 10
        elif safety.status == SafetyStatus.DANGEROUS:
            score -= 30
        
        return score
    
    def get_grade(self, score: int) -> str:
        """Convert score to letter grade"""
        if score >= 90: return "A+"
        if score >= 85: return "A"
        if score >= 80: return "A-"
        if score >= 75: return "B+"
        if score >= 70: return "B"
        if score >= 65: return "B-"
        if score >= 60: return "C+"
        if score >= 55: return "C"
        if score >= 50: return "C-"
        if score >= 40: return "D"
        return "F"


# Singleton
_scoring_engine: Optional[ScoringEngine] = None

def get_scoring_engine() -> ScoringEngine:
    global _scoring_engine
    if _scoring_engine is None:
        _scoring_engine = ScoringEngine()
    return _scoring_engine
