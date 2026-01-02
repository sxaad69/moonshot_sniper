"""
Moonshot Sniper Bot - Momentum Engine
Technical analysis and momentum detection
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime
import logging

from config.settings import Chain, MOMENTUM_CONFIG
from scanners.dexscreener import TokenPair

logger = logging.getLogger(__name__)

@dataclass
class PricePoint:
    """Single price data point"""
    price: float
    volume: float
    timestamp: datetime
    buys: int = 0
    sells: int = 0

@dataclass
class MomentumSignal:
    """Momentum analysis result"""
    token_address: str
    chain: str
    
    # Trend
    trend: str = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL
    trend_strength: float = 0  # 0-100
    
    # EMA
    ema_fast: float = 0
    ema_slow: float = 0
    ema_crossover: bool = False
    ema_signal: str = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL
    
    # Volume
    volume_surge: bool = False
    volume_trend: str = "STABLE"  # INCREASING, DECREASING, STABLE
    avg_volume: float = 0
    current_volume: float = 0
    
    # Price action
    price_change_5m: float = 0
    price_change_1h: float = 0
    is_pumping: bool = False
    is_dumping: bool = False
    
    # Buy pressure
    buy_pressure: float = 0.5
    buy_pressure_trend: str = "STABLE"
    
    # Overall
    signal: str = "NEUTRAL"  # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
    confidence: float = 0  # 0-100
    
    def to_dict(self) -> Dict:
        return {
            "token": self.token_address, "chain": self.chain,
            "signal": self.signal, "confidence": self.confidence,
            "trend": self.trend, "strength": self.trend_strength,
            "ema_signal": self.ema_signal, "crossover": self.ema_crossover,
            "volume_surge": self.volume_surge, "volume_trend": self.volume_trend,
            "pumping": self.is_pumping, "dumping": self.is_dumping,
            "buy_pressure": self.buy_pressure
        }


class MomentumEngine:
    """
    Momentum analysis engine
    Calculates EMAs, detects trends, and generates signals
    """
    
    def __init__(self):
        self.config = MOMENTUM_CONFIG
        self.price_history: Dict[str, deque] = {}
        self.max_history = 100  # Keep last 100 data points
    
    def _get_key(self, chain: Chain, token: str) -> str:
        return f"{chain.value}:{token}"
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return sum(prices) / len(prices) if prices else 0
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # SMA for first period
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def update_price(self, chain: Chain, token: str, pair: TokenPair):
        """Update price history with new data"""
        key = self._get_key(chain, token)
        
        if key not in self.price_history:
            self.price_history[key] = deque(maxlen=self.max_history)
        
        point = PricePoint(
            price=pair.price_usd,
            volume=pair.volume_5m,
            timestamp=datetime.utcnow(),
            buys=pair.txns_buys_5m,
            sells=pair.txns_sells_5m
        )
        
        self.price_history[key].append(point)
    
    def analyze(self, chain: Chain, token: str, pair: TokenPair) -> MomentumSignal:
        """
        Analyze momentum for a token
        
        Args:
            chain: Blockchain
            token: Token address
            pair: Current pair data
        
        Returns:
            MomentumSignal with analysis results
        """
        key = self._get_key(chain, token)
        signal = MomentumSignal(token_address=token, chain=chain.value)
        
        # Update with current data
        self.update_price(chain, token, pair)
        
        history = list(self.price_history.get(key, []))
        prices = [p.price for p in history] if history else [pair.price_usd]
        
        # EMA Analysis
        signal.ema_fast = self._calculate_ema(prices, self.config.ema_fast)
        signal.ema_slow = self._calculate_ema(prices, self.config.ema_slow)
        
        if signal.ema_fast > signal.ema_slow * 1.02:
            signal.ema_signal = "BULLISH"
        elif signal.ema_fast < signal.ema_slow * 0.98:
            signal.ema_signal = "BEARISH"
        
        # Check for crossover
        if len(history) >= 2:
            prev_fast = self._calculate_ema(prices[:-1], self.config.ema_fast)
            prev_slow = self._calculate_ema(prices[:-1], self.config.ema_slow)
            
            if prev_fast <= prev_slow and signal.ema_fast > signal.ema_slow:
                signal.ema_crossover = True
                signal.ema_signal = "BULLISH"
            elif prev_fast >= prev_slow and signal.ema_fast < signal.ema_slow:
                signal.ema_crossover = True
                signal.ema_signal = "BEARISH"
        
        # Volume Analysis
        volumes = [p.volume for p in history] if history else [pair.volume_5m]
        signal.avg_volume = sum(volumes) / len(volumes) if volumes else 0
        signal.current_volume = pair.volume_5m
        
        if signal.avg_volume > 0:
            vol_ratio = signal.current_volume / signal.avg_volume
            signal.volume_surge = vol_ratio >= self.config.volume_surge_multiplier
            
            if vol_ratio > 1.5:
                signal.volume_trend = "INCREASING"
            elif vol_ratio < 0.5:
                signal.volume_trend = "DECREASING"
        
        # Price Action
        signal.price_change_5m = pair.price_change_5m
        signal.price_change_1h = pair.price_change_1h
        signal.is_pumping = pair.price_change_5m >= self.config.price_pump_threshold
        signal.is_dumping = pair.price_change_5m <= self.config.price_dump_threshold
        
        # Buy Pressure
        signal.buy_pressure = pair.buy_pressure_5m
        
        if len(history) >= 3:
            recent_pressure = [p.buys / (p.buys + p.sells + 1) for p in list(history)[-3:]]
            if recent_pressure[-1] > recent_pressure[0] + 0.1:
                signal.buy_pressure_trend = "INCREASING"
            elif recent_pressure[-1] < recent_pressure[0] - 0.1:
                signal.buy_pressure_trend = "DECREASING"
        
        # Overall Trend
        signal.trend, signal.trend_strength = self._calculate_trend(signal, pair)
        
        # Generate Signal
        signal.signal, signal.confidence = self._generate_signal(signal)
        
        return signal
    
    def _calculate_trend(self, signal: MomentumSignal, pair: TokenPair) -> Tuple[str, float]:
        """Calculate overall trend and strength"""
        bullish_points = 0
        bearish_points = 0
        max_points = 10
        
        # EMA signal
        if signal.ema_signal == "BULLISH":
            bullish_points += 2
            if signal.ema_crossover:
                bullish_points += 1
        elif signal.ema_signal == "BEARISH":
            bearish_points += 2
            if signal.ema_crossover:
                bearish_points += 1
        
        # Price change
        if signal.price_change_5m > 5:
            bullish_points += 2
        elif signal.price_change_5m > 0:
            bullish_points += 1
        elif signal.price_change_5m < -5:
            bearish_points += 2
        elif signal.price_change_5m < 0:
            bearish_points += 1
        
        if signal.price_change_1h > 10:
            bullish_points += 2
        elif signal.price_change_1h > 0:
            bullish_points += 1
        elif signal.price_change_1h < -10:
            bearish_points += 2
        elif signal.price_change_1h < 0:
            bearish_points += 1
        
        # Volume
        if signal.volume_surge and signal.buy_pressure > 0.6:
            bullish_points += 2
        elif signal.volume_surge and signal.buy_pressure < 0.4:
            bearish_points += 2
        
        # Buy pressure
        if signal.buy_pressure >= self.config.buy_pressure_threshold:
            bullish_points += 1
        elif signal.buy_pressure < 0.4:
            bearish_points += 1
        
        # Calculate
        if bullish_points > bearish_points + 2:
            trend = "BULLISH"
            strength = min(100, (bullish_points / max_points) * 100)
        elif bearish_points > bullish_points + 2:
            trend = "BEARISH"
            strength = min(100, (bearish_points / max_points) * 100)
        else:
            trend = "NEUTRAL"
            strength = 50
        
        return trend, strength
    
    def _generate_signal(self, signal: MomentumSignal) -> Tuple[str, float]:
        """Generate trading signal and confidence"""
        score = 50  # Neutral start
        
        # Trend contribution
        if signal.trend == "BULLISH":
            score += signal.trend_strength * 0.3
        elif signal.trend == "BEARISH":
            score -= signal.trend_strength * 0.3
        
        # EMA contribution
        if signal.ema_signal == "BULLISH":
            score += 10
            if signal.ema_crossover:
                score += 10
        elif signal.ema_signal == "BEARISH":
            score -= 10
            if signal.ema_crossover:
                score -= 10
        
        # Volume contribution
        if signal.volume_surge:
            if signal.buy_pressure > 0.6:
                score += 15
            elif signal.buy_pressure < 0.4:
                score -= 15
        
        # Buy pressure contribution
        score += (signal.buy_pressure - 0.5) * 20
        
        # Price action
        if signal.is_pumping:
            score += 10
        elif signal.is_dumping:
            score -= 20
        
        # Clamp and determine signal
        score = max(0, min(100, score))
        
        if score >= 80:
            return "STRONG_BUY", score
        elif score >= 65:
            return "BUY", score
        elif score >= 35:
            return "NEUTRAL", score
        elif score >= 20:
            return "SELL", score
        else:
            return "STRONG_SELL", score
    
    def quick_momentum_check(self, pair: TokenPair) -> Dict:
        """Quick momentum assessment without full analysis"""
        return {
            "bullish": pair.price_change_5m > 0 and pair.buy_pressure_5m > 0.55,
            "strong": pair.price_change_5m > 5 and pair.buy_pressure_5m > 0.6,
            "volume_surge": pair.volume_5m > pair.volume_1h / 12 * 2,
            "buy_pressure": pair.buy_pressure_5m,
            "change_5m": pair.price_change_5m,
            "change_1h": pair.price_change_1h
        }
    
    def clear_history(self, chain: Chain, token: str):
        """Clear price history for a token"""
        key = self._get_key(chain, token)
        if key in self.price_history:
            del self.price_history[key]
    
    def get_history_size(self, chain: Chain, token: str) -> int:
        """Get number of data points for a token"""
        key = self._get_key(chain, token)
        return len(self.price_history.get(key, []))


# Singleton
_momentum_engine: Optional[MomentumEngine] = None

def get_momentum_engine() -> MomentumEngine:
    global _momentum_engine
    if _momentum_engine is None:
        _momentum_engine = MomentumEngine()
    return _momentum_engine
