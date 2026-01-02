"""
Moonshot Sniper Bot - Complete Configuration
All configurable parameters for the entire system
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
import os

class TradingMode(Enum):
    SIMULATION = "simulation"
    LIVE = "live"

class Chain(Enum):
    SOL = "solana"
    BSC = "bsc"
    BASE = "base"

class PoolType(Enum):
    SAFE = "safe"
    HUNT = "hunt"

# ============================================================
# WALLET CONFIGURATION
# ============================================================

@dataclass
class WalletConfig:
    """Wallet addresses per chain - only chains with wallets are active"""
    SOL: Optional[str] = None
    BSC: Optional[str] = None
    BASE: Optional[str] = None
    
    # Private keys (NEVER commit these - use .env)
    SOL_PRIVATE_KEY: Optional[str] = None
    BSC_PRIVATE_KEY: Optional[str] = None
    BASE_PRIVATE_KEY: Optional[str] = None
    
    def get_active_chains(self) -> List[Chain]:
        active = []
        if self.SOL: active.append(Chain.SOL)
        if self.BSC: active.append(Chain.BSC)
        if self.BASE: active.append(Chain.BASE)
        return active
    
    def get_private_key(self, chain: Chain) -> Optional[str]:
        return {
            Chain.SOL: self.SOL_PRIVATE_KEY,
            Chain.BSC: self.BSC_PRIVATE_KEY,
            Chain.BASE: self.BASE_PRIVATE_KEY
        }.get(chain)

# ============================================================
# RPC CONFIGURATION
# ============================================================

@dataclass
class RPCEndpoint:
    url: str
    priority: int
    name: str
    rate_limit: int = 100

SOLANA_RPCS = [
    RPCEndpoint("https://mainnet.helius-rpc.com/?api-key=YOUR_KEY", 1, "Helius", 50),
    RPCEndpoint("https://solana-mainnet.g.alchemy.com/v2/YOUR_KEY", 2, "Alchemy", 30),
    RPCEndpoint("https://api.mainnet-beta.solana.com", 3, "Public", 10),
]

BSC_RPCS = [
    RPCEndpoint("https://bsc-dataseed1.binance.org", 1, "Binance1", 50),
    RPCEndpoint("https://bsc-dataseed2.binance.org", 2, "Binance2", 50),
    RPCEndpoint("https://rpc.ankr.com/bsc", 3, "Ankr", 30),
]

BASE_RPCS = [
    RPCEndpoint("https://base-mainnet.g.alchemy.com/v2/YOUR_KEY", 1, "Alchemy", 30),
    RPCEndpoint("https://mainnet.base.org", 2, "Public", 20),
    RPCEndpoint("https://base.blockpi.network/v1/rpc/public", 3, "BlockPi", 20),
]

@dataclass
class ChainConfig:
    chain: Chain
    rpcs: List[RPCEndpoint]
    native_token: str
    explorer_url: str
    min_liquidity: float
    dex_router: str = ""
    wrapped_native: str = ""

CHAIN_CONFIGS = {
    Chain.SOL: ChainConfig(
        chain=Chain.SOL, rpcs=SOLANA_RPCS, native_token="SOL",
        explorer_url="https://solscan.io", min_liquidity=3000,
        wrapped_native="So11111111111111111111111111111111111111112"
    ),
    Chain.BSC: ChainConfig(
        chain=Chain.BSC, rpcs=BSC_RPCS, native_token="BNB",
        explorer_url="https://bscscan.com", min_liquidity=5000,
        dex_router="0x10ED43C718714eb63d5aA57B78B54704E256024E",
        wrapped_native="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    ),
    Chain.BASE: ChainConfig(
        chain=Chain.BASE, rpcs=BASE_RPCS, native_token="ETH",
        explorer_url="https://basescan.org", min_liquidity=5000,
        dex_router="0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
        wrapped_native="0x4200000000000000000000000000000000000006"
    ),
}

# ============================================================
# API CONFIGURATION
# ============================================================

@dataclass
class APIConfig:
    # DEXScreener - Free, 300 req/min
    dexscreener_base: str = "https://api.dexscreener.com/latest"
    dexscreener_rate_limit: int = 300
    
    # GoPlus Security - Free, 100 req/min
    goplus_base: str = "https://api.gopluslabs.io/api/v1"
    goplus_rate_limit: int = 100
    
    # Birdeye - Free tier
    birdeye_base: str = "https://public-api.birdeye.so"
    birdeye_api_key: str = ""
    birdeye_rate_limit: int = 100
    
    # Jupiter - Free, unlimited
    jupiter_quote: str = "https://quote-api.jup.ag/v6"
    jupiter_swap: str = "https://quote-api.jup.ag/v6/swap"
    jupiter_price: str = "https://price.jup.ag/v6"
    
    # Pump.fun
    pumpfun_base: str = "https://frontend-api.pump.fun"
    
    # Solscan - For holder data
    solscan_base: str = "https://public-api.solscan.io"

API_CONFIG = APIConfig()

# ============================================================
# TELEGRAM CONFIGURATION
# ============================================================

@dataclass
class TelegramConfig:
    bot_token: str = ""
    main_alerts_channel: str = ""
    positions_channel: str = ""
    rejections_channel: str = ""
    system_channel: str = ""
    admin_user_id: str = ""
    log_rejections: bool = True
    log_scans: bool = False

TELEGRAM_CONFIG = TelegramConfig()

# ============================================================
# POOL CONFIGURATION
# ============================================================

@dataclass
class PoolConfig:
    name: str
    pool_type: PoolType
    allocation_percent: float
    min_score: int
    min_confluence: int
    stop_loss_percent: float
    position_size_percent: float
    max_positions: int
    # Token age requirements (minutes)
    min_age: int = 0
    max_age: int = 240
    # Risk parameters
    trailing_stop_percent: float = 25.0
    flat_exit_minutes: int = 120

SAFE_POOL = PoolConfig(
    name="SAFE", pool_type=PoolType.SAFE, allocation_percent=60,
    min_score=75, min_confluence=3, stop_loss_percent=-20,
    position_size_percent=15, max_positions=3,
    min_age=30, max_age=240, trailing_stop_percent=20, flat_exit_minutes=120
)

HUNT_POOL = PoolConfig(
    name="HUNT", pool_type=PoolType.HUNT, allocation_percent=40,
    min_score=65, min_confluence=2, stop_loss_percent=-30,
    position_size_percent=15, max_positions=2,
    min_age=0, max_age=30, trailing_stop_percent=25, flat_exit_minutes=240
)

# ============================================================
# TAKE PROFIT CONFIGURATION
# ============================================================

@dataclass
class TakeProfitLevel:
    level: int
    trigger_percent: float
    sell_percent: float
    move_sl_to_percent: Optional[float] = None  # Move SL after this TP

TAKE_PROFIT_LADDER = [
    TakeProfitLevel(1, 50, 20, 0),      # TP1: +50% → sell 20%, move SL to breakeven
    TakeProfitLevel(2, 100, 30, 25),    # TP2: +100% → sell 30%, move SL to +25%
    TakeProfitLevel(3, 200, 25, 75),    # TP3: +200% → sell 25%, move SL to +75%
    TakeProfitLevel(4, 500, 15, 150),   # TP4: +500% → sell 15%, move SL to +150%
    # Remaining 10% = moon bag with trailing stop
]

# ============================================================
# SCORING WEIGHTS
# ============================================================

@dataclass
class ScoringWeights:
    """Weights for quality score (must sum to 100)"""
    liquidity: int = 20
    holders: int = 20
    trading_activity: int = 25
    momentum: int = 20
    social_signals: int = 10
    dev_reputation: int = 5

SCORING_WEIGHTS = ScoringWeights()

# ============================================================
# MOMENTUM CONFIGURATION
# ============================================================

@dataclass
class MomentumConfig:
    # EMA periods
    ema_fast: int = 5
    ema_slow: int = 20
    
    # Volume thresholds
    volume_surge_multiplier: float = 2.0  # 2x average = surge
    
    # Price thresholds
    price_pump_threshold: float = 10.0  # 10% in 5 min = pump
    price_dump_threshold: float = -15.0  # -15% in 5 min = dump
    
    # Buy pressure
    buy_pressure_threshold: float = 0.6  # 60% buys = bullish

MOMENTUM_CONFIG = MomentumConfig()

# ============================================================
# SMART WALLET CONFIGURATION
# ============================================================

@dataclass
class SmartWalletConfig:
    # Tracking settings
    max_tracked_wallets: int = 100
    min_win_rate: float = 0.6  # 60% minimum win rate
    min_total_trades: int = 10
    
    # Signal thresholds
    smart_money_buy_threshold: int = 2  # 2+ smart wallets buying
    whale_size_threshold: float = 5000  # $5k+ = whale buy
    
    # Data sources
    track_pump_graduates: bool = True
    track_dex_winners: bool = True

SMART_WALLET_CONFIG = SmartWalletConfig()

# ============================================================
# CONFLUENCE SIGNALS
# ============================================================

@dataclass
class ConfluenceConfig:
    """Minimum signals required for each pool"""
    # Signal types
    signals = [
        "safety_passed",        # Contract verified safe
        "liquidity_healthy",    # Above minimum, not suspicious
        "holders_distributed",  # No whale concentration
        "volume_increasing",    # Volume trend up
        "buy_pressure_high",    # More buys than sells
        "momentum_bullish",     # EMA crossover or strong trend
        "smart_money_buying",   # Tracked wallets entering
        "social_buzz",          # Twitter/Telegram mentions
        "fresh_token",          # Within age window
        "no_red_flags",         # No concerning patterns
    ]
    
    # Weights for each signal
    weights = {
        "safety_passed": 2,
        "liquidity_healthy": 1,
        "holders_distributed": 1,
        "volume_increasing": 1,
        "buy_pressure_high": 1,
        "momentum_bullish": 2,
        "smart_money_buying": 2,
        "social_buzz": 1,
        "fresh_token": 1,
        "no_red_flags": 1,
    }

CONFLUENCE_CONFIG = ConfluenceConfig()

# ============================================================
# TRADING CONFIGURATION
# ============================================================

@dataclass
class TradingConfig:
    mode: TradingMode = TradingMode.SIMULATION
    starting_capital: float = 100.0
    
    # Circuit breakers
    daily_loss_limit_percent: float = 15
    consecutive_loss_pause: int = 3
    pause_duration_hours: int = 4
    
    # Position limits
    max_position_size: float = 20.0
    min_position_size: float = 5.0
    max_total_positions: int = 5
    
    # Execution settings
    max_slippage_percent: float = 5.0
    priority_fee_lamports: int = 10000  # For Solana
    gas_multiplier: float = 1.2  # For EVM chains
    
    # Safety requirements
    max_tax_percent: float = 5.0
    min_holders: int = 20
    max_top_holder_percent: float = 20.0
    min_liquidity_usd: float = 3000
    
    # Time settings
    scan_interval_seconds: int = 5
    price_update_seconds: int = 10
    position_check_seconds: int = 30

TRADING_CONFIG = TradingConfig()

# ============================================================
# DATABASE CONFIGURATION
# ============================================================

@dataclass
class DatabaseConfig:
    path: str = "data/moonshot.db"
    backup_interval_hours: int = 24
    max_history_days: int = 30

DATABASE_CONFIG = DatabaseConfig()

# ============================================================
# LOGGING CONFIGURATION
# ============================================================

@dataclass
class LoggingConfig:
    level: str = "INFO"
    file_path: str = "logs/bot.log"
    max_file_size_mb: int = 10
    backup_count: int = 5
    console_output: bool = True

LOGGING_CONFIG = LoggingConfig()

# ============================================================
# MASTER BOT CONFIG
# ============================================================

@dataclass
class BotConfig:
    wallets: WalletConfig = field(default_factory=WalletConfig)
    trading: TradingConfig = field(default_factory=lambda: TRADING_CONFIG)
    telegram: TelegramConfig = field(default_factory=lambda: TELEGRAM_CONFIG)
    api: APIConfig = field(default_factory=lambda: API_CONFIG)
    safe_pool: PoolConfig = field(default_factory=lambda: SAFE_POOL)
    hunt_pool: PoolConfig = field(default_factory=lambda: HUNT_POOL)
    scoring: ScoringWeights = field(default_factory=lambda: SCORING_WEIGHTS)
    momentum: MomentumConfig = field(default_factory=lambda: MOMENTUM_CONFIG)
    smart_wallet: SmartWalletConfig = field(default_factory=lambda: SMART_WALLET_CONFIG)
    confluence: ConfluenceConfig = field(default_factory=lambda: CONFLUENCE_CONFIG)
    database: DatabaseConfig = field(default_factory=lambda: DATABASE_CONFIG)
    logging: LoggingConfig = field(default_factory=lambda: LOGGING_CONFIG)

def load_config_from_env() -> BotConfig:
    """Load configuration from environment variables"""
    config = BotConfig()
    
    # Wallets
    config.wallets.SOL = os.getenv("WALLET_SOL")
    config.wallets.BSC = os.getenv("WALLET_BSC")
    config.wallets.BASE = os.getenv("WALLET_BASE")
    config.wallets.SOL_PRIVATE_KEY = os.getenv("SOL_PRIVATE_KEY")
    config.wallets.BSC_PRIVATE_KEY = os.getenv("BSC_PRIVATE_KEY")
    config.wallets.BASE_PRIVATE_KEY = os.getenv("BASE_PRIVATE_KEY")
    
    # Trading mode
    mode = os.getenv("TRADING_MODE", "simulation")
    config.trading.mode = TradingMode.LIVE if mode.lower() == "live" else TradingMode.SIMULATION
    config.trading.starting_capital = float(os.getenv("STARTING_CAPITAL", "100"))
    
    # Telegram
    config.telegram.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    config.telegram.main_alerts_channel = os.getenv("TELEGRAM_MAIN_ALERTS", "")
    config.telegram.positions_channel = os.getenv("TELEGRAM_POSITIONS", "")
    config.telegram.rejections_channel = os.getenv("TELEGRAM_REJECTIONS", "")
    config.telegram.system_channel = os.getenv("TELEGRAM_SYSTEM", "")
    config.telegram.admin_user_id = os.getenv("TELEGRAM_ADMIN_ID", "")
    
    # API Keys
    config.api.birdeye_api_key = os.getenv("BIRDEYE_API_KEY", "")
    
    return config

# Create default config instance
BOT_CONFIG = BotConfig()
