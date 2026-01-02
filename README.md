# 🎯 Moonshot Sniper Bot - Complete Edition

A sophisticated multi-chain meme coin sniper bot with advanced safety analysis, dual-pool trading strategy, smart wallet tracking, momentum detection, and comprehensive position management.

## ✨ Features

### 🔍 Token Discovery
- **Multi-Chain Support**: Solana, BSC, and Base
- **DEXScreener Integration**: Real-time new token discovery
- **Smart Wallet Tracking**: Follow winning wallets
- **Volume & Momentum Analysis**: Detect early pumps

### 🛡️ Safety Engine
- **GoPlus Integration**: Comprehensive contract analysis
- **Honeypot Detection**: Never get trapped
- **Tax Verification**: Avoid high-tax tokens
- **LP Lock Check**: Verify liquidity safety
- **Holder Analysis**: Detect concentrated holdings

### 📊 Quality Scoring
- **Weighted Algorithm**: 0-100 score based on multiple factors
- **Liquidity Analysis**: Depth and sustainability
- **Trading Patterns**: Buy/sell pressure, volume trends
- **Momentum Indicators**: EMA crossovers, price action
- **Social Signals**: Smart money activity

### 🎯 Confluence Engine
- **10 Signal Types**: Combined for entry decisions
- **Pool Routing**: SAFE (conservative) vs HUNT (aggressive)
- **Confidence Scoring**: Position sizing based on signal strength

### 💰 Position Management
- **Automatic TP Ladder**: 4-level take profit system
- **Trailing Stop Loss**: Lock in profits
- **Time-Based Exits**: Avoid stagnant positions
- **Circuit Breakers**: Daily loss limits, pause on consecutive losses

### 📱 Telegram Integration
- **4-Channel System**: Organized by priority
- **Real-Time Alerts**: Entry, exit, TP/SL hits
- **Daily Summaries**: Performance reports
- **Full Transparency**: Every decision logged

## 📁 Project Structure

```
moonshot_bot_complete/
├── main.py                 # Bot orchestrator
├── requirements.txt        # Dependencies
├── .env.example           # Configuration template
│
├── config/
│   └── settings.py        # All configuration
│
├── core/
│   ├── rpc_manager.py     # Multi-chain RPC
│   └── database.py        # SQLite persistence
│
├── scanners/
│   ├── dexscreener.py     # Token discovery
│   └── wallet_tracker.py  # Smart wallet tracking
│
├── engines/
│   ├── safety_engine.py   # Contract analysis
│   ├── scoring_engine.py  # Quality scoring
│   ├── momentum_engine.py # Technical analysis
│   ├── confluence_engine.py # Signal aggregation
│   ├── execution_engine.py # Trade execution
│   └── position_manager.py # Position lifecycle
│
├── utils/
│   └── telegram_logger.py # Logging system
│
├── data/                  # SQLite database
└── logs/                  # Log files
```

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- pip

### Installation

```bash
# Clone/download the project
cd moonshot_bot_complete

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your values
```

### Configuration

1. **Wallets**: Add your wallet addresses (only active chains will scan)
2. **API Keys**: Get free keys from Helius, Alchemy
3. **Telegram**: Create bot with @BotFather, create 4 channels
4. **Risk Settings**: Adjust based on your tolerance

### Running

```bash
# Simulation mode (default - no real money)
python main.py

# The bot will:
# 1. Connect to configured chains
# 2. Start scanning for new tokens
# 3. Analyze safety, quality, momentum
# 4. Log all decisions to Telegram
# 5. Execute virtual trades in simulation
```

## 📊 Trading Strategy

### Dual-Pool System

| Pool | Allocation | Min Score | Token Age | Stop Loss |
|------|------------|-----------|-----------|-----------|
| SAFE | 60% | 75+ | 30-240 min | -20% |
| HUNT | 40% | 65+ | 0-30 min | -30% |

### Take Profit Ladder

| Level | Trigger | Sell | New Stop Loss |
|-------|---------|------|---------------|
| TP1 | +50% | 20% | Breakeven |
| TP2 | +100% | 30% | +25% |
| TP3 | +200% | 25% | +75% |
| TP4 | +500% | 15% | +150% |
| Moon | Trail | 10% | 25% trailing |

### Safety Requirements

- ❌ No honeypots
- ❌ No mint function
- ❌ No proxy contracts
- ✅ Tax < 5%
- ✅ LP locked
- ✅ 20+ holders
- ✅ Top holder < 20%

## 🔧 Free Tier Infrastructure

| Service | Usage | Limit |
|---------|-------|-------|
| Helius | Solana RPC | 100K/month |
| Alchemy | Multi-chain RPC | 300M CU/month |
| DEXScreener | Token data | 300 req/min |
| GoPlus | Security | 100 req/min |
| Jupiter | Swaps | Unlimited |
| Telegram | Alerts | Unlimited |

**Estimated Cost: $5-10/month (VPS only)**

## 📈 Confluence Signals

1. **safety_passed** - Contract verified safe
2. **liquidity_healthy** - Meets minimums
3. **holders_distributed** - No whale concentration
4. **volume_increasing** - Growing activity
5. **buy_pressure_high** - More buys than sells
6. **momentum_bullish** - EMA/trend positive
7. **smart_money_buying** - Tracked wallets entering
8. **social_buzz** - Twitter/Telegram mentions
9. **fresh_token** - Within age window
10. **no_red_flags** - Clean contract

## ⚙️ Configuration Options

### Pool Settings
```python
SAFE_POOL = {
    "allocation": 60%,
    "min_score": 75,
    "min_confluence": 3,
    "stop_loss": -20%,
    "position_size": 15%,
    "max_positions": 3
}
```

### Risk Settings
```python
TRADING_CONFIG = {
    "daily_loss_limit": 15%,
    "consecutive_loss_pause": 3,
    "max_slippage": 5%,
    "max_tax": 5%,
    "min_holders": 20
}
```

## 📱 Telegram Channels

| Channel | Purpose | Priority |
|---------|---------|----------|
| 🔴 Main Alerts | Entries, exits, TP/SL | Critical |
| 📊 Positions | Updates, status | Medium |
| ❌ Rejections | Why tokens skipped | Low |
| ⚠️ System | Errors, health | Debug |

## 🛡️ Security Notes

- **NEVER** commit private keys to git
- Use dedicated trading wallets
- Start with simulation mode
- Test with small amounts first
- Monitor daily reports

## 📊 Database Schema

- **positions** - Open and closed positions
- **trades** - All executed trades
- **smart_wallets** - Tracked winning wallets
- **daily_stats** - Performance history
- **token_cache** - Temporary token data

## 🔄 Development Roadmap

- [x] Phase 1: Foundation (Scanner, Safety, Logger)
- [x] Phase 2: Intelligence (Scoring, Momentum, Confluence)
- [x] Phase 3: Execution (Position Manager, TP/SL)
- [x] Phase 4: Integration (Complete System)
- [ ] Phase 5: Optimization (ML patterns, backtesting)

## ⚠️ Disclaimer

This bot is for educational purposes only. Cryptocurrency trading involves substantial risk of loss. Never trade with money you cannot afford to lose. Past performance does not guarantee future results. The developers are not responsible for any financial losses incurred from using this software.

## 📝 License

Private use only. Not for redistribution.

---

**Happy Hunting! 🎯🚀**
