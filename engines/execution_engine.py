"""
Moonshot Sniper Bot - Execution Engine
Trade execution for Solana (Jupiter) and EVM chains
"""

import asyncio
import aiohttp
import base64
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging

from config.settings import (
    Chain, TradingMode, CHAIN_CONFIGS, API_CONFIG, TRADING_CONFIG, WalletConfig
)
from core.rpc_manager import get_rpc_manager

logger = logging.getLogger(__name__)

@dataclass
class SwapQuote:
    """Swap quote details"""
    input_token: str
    output_token: str
    input_amount: float
    output_amount: float
    price_impact: float
    slippage: float
    route: str
    fee: float
    expires_at: datetime
    raw_quote: Dict = None

@dataclass
class SwapResult:
    """Result of swap execution"""
    success: bool
    tx_hash: Optional[str] = None
    input_amount: float = 0
    output_amount: float = 0
    actual_price: float = 0
    slippage: float = 0
    fee: float = 0
    error: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class ExecutionEngine:
    """
    Trade execution engine
    Supports Jupiter (Solana) and EVM DEX routers
    """
    
    def __init__(self, wallets: WalletConfig, mode: TradingMode = TradingMode.SIMULATION):
        self.wallets = wallets
        self.mode = mode
        self.session: Optional[aiohttp.ClientSession] = None
        self.rpc = get_rpc_manager(wallets)
    
    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        await self.rpc.start()
        logger.info(f"Execution Engine started in {self.mode.value} mode")
    
    async def stop(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    # ============================================================
    # QUOTE FUNCTIONS
    # ============================================================
    
    async def get_quote(self, chain: Chain, input_token: str, output_token: str,
                       amount: float, slippage: float = None) -> Optional[SwapQuote]:
        """
        Get swap quote for any chain
        
        Args:
            chain: Target chain
            input_token: Input token address
            output_token: Output token address
            amount: Amount in input token decimals
            slippage: Max slippage percentage
        
        Returns:
            SwapQuote or None
        """
        slippage = slippage or TRADING_CONFIG.max_slippage_percent
        
        if chain == Chain.SOL:
            return await self._get_jupiter_quote(input_token, output_token, amount, slippage)
        else:
            return await self._get_evm_quote(chain, input_token, output_token, amount, slippage)
    
    async def _get_jupiter_quote(self, input_token: str, output_token: str,
                                 amount: float, slippage: float) -> Optional[SwapQuote]:
        """Get quote from Jupiter aggregator"""
        if not self.session:
            await self.start()
        
        # Convert amount to lamports (assuming 9 decimals for most tokens)
        amount_raw = int(amount * 1e9)
        slippage_bps = int(slippage * 100)  # Convert to basis points
        
        url = f"{API_CONFIG.jupiter_quote}/quote"
        params = {
            "inputMint": input_token,
            "outputMint": output_token,
            "amount": str(amount_raw),
            "slippageBps": slippage_bps,
            "onlyDirectRoutes": "false"
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    out_amount = int(data.get("outAmount", 0)) / 1e9
                    in_amount = int(data.get("inAmount", 0)) / 1e9
                    
                    return SwapQuote(
                        input_token=input_token,
                        output_token=output_token,
                        input_amount=in_amount,
                        output_amount=out_amount,
                        price_impact=float(data.get("priceImpactPct", 0)),
                        slippage=slippage,
                        route=data.get("routePlan", [{}])[0].get("swapInfo", {}).get("label", "Jupiter"),
                        fee=float(data.get("platformFee", {}).get("amount", 0)) / 1e9,
                        expires_at=datetime.utcnow(),
                        raw_quote=data
                    )
                else:
                    logger.warning(f"Jupiter quote failed: {response.status}")
        except Exception as e:
            logger.error(f"Jupiter quote error: {e}")
        
        return None
    
    async def _get_evm_quote(self, chain: Chain, input_token: str, output_token: str,
                            amount: float, slippage: float) -> Optional[SwapQuote]:
        """Get quote for EVM chains (simplified - would use 1inch or similar)"""
        # Placeholder - in production, integrate with 1inch or Paraswap
        return SwapQuote(
            input_token=input_token,
            output_token=output_token,
            input_amount=amount,
            output_amount=amount * 0.99,  # Placeholder
            price_impact=0.5,
            slippage=slippage,
            route="PancakeSwap" if chain == Chain.BSC else "Uniswap",
            fee=0.003,
            expires_at=datetime.utcnow()
        )
    
    # ============================================================
    # EXECUTION FUNCTIONS
    # ============================================================
    
    async def execute_swap(self, chain: Chain, quote: SwapQuote) -> SwapResult:
        """
        Execute a swap
        
        Args:
            chain: Target chain
            quote: Quote to execute
        
        Returns:
            SwapResult with execution details
        """
        # Check mode
        if self.mode == TradingMode.SIMULATION:
            return await self._simulate_swap(chain, quote)
        
        # Live execution
        if chain == Chain.SOL:
            return await self._execute_jupiter_swap(quote)
        else:
            return await self._execute_evm_swap(chain, quote)
    
    async def _simulate_swap(self, chain: Chain, quote: SwapQuote) -> SwapResult:
        """Simulate swap execution (paper trading)"""
        # Simulate some slippage
        import random
        actual_slippage = random.uniform(0, quote.slippage)
        actual_output = quote.output_amount * (1 - actual_slippage / 100)
        
        logger.info(f"[SIM] Swap executed: {quote.input_amount:.6f} -> {actual_output:.6f}")
        
        return SwapResult(
            success=True,
            tx_hash=f"sim_{datetime.utcnow().timestamp()}",
            input_amount=quote.input_amount,
            output_amount=actual_output,
            actual_price=quote.input_amount / actual_output if actual_output > 0 else 0,
            slippage=actual_slippage,
            fee=quote.fee
        )
    
    async def _execute_jupiter_swap(self, quote: SwapQuote) -> SwapResult:
        """Execute swap on Jupiter"""
        if not quote.raw_quote:
            return SwapResult(success=False, error="No raw quote data")
        
        wallet = self.wallets.SOL
        private_key = self.wallets.SOL_PRIVATE_KEY
        
        if not wallet or not private_key:
            return SwapResult(success=False, error="No wallet configured")
        
        try:
            # Get swap transaction
            swap_url = f"{API_CONFIG.jupiter_swap}"
            payload = {
                "quoteResponse": quote.raw_quote,
                "userPublicKey": wallet,
                "wrapAndUnwrapSol": True,
                "prioritizationFeeLamports": TRADING_CONFIG.priority_fee_lamports
            }
            
            async with self.session.post(swap_url, json=payload) as response:
                if response.status != 200:
                    return SwapResult(success=False, error=f"Swap request failed: {response.status}")
                
                data = await response.json()
                swap_tx = data.get("swapTransaction")
                
                if not swap_tx:
                    return SwapResult(success=False, error="No swap transaction returned")
                
                # Sign and send transaction
                # Note: This requires proper signing implementation
                # tx_hash = await self._sign_and_send_solana(swap_tx, private_key)
                
                # Placeholder for actual implementation
                return SwapResult(
                    success=False,
                    error="Live execution requires wallet signing implementation"
                )
                
        except Exception as e:
            logger.error(f"Jupiter swap error: {e}")
            return SwapResult(success=False, error=str(e))
    
    async def _execute_evm_swap(self, chain: Chain, quote: SwapQuote) -> SwapResult:
        """Execute swap on EVM chain"""
        # Placeholder - requires web3 integration
        return SwapResult(
            success=False,
            error="EVM execution requires web3 implementation"
        )
    
    # ============================================================
    # BUY/SELL HELPERS
    # ============================================================
    
    async def buy_token(self, chain: Chain, token_address: str, 
                       amount_in_native: float, max_slippage: float = None) -> SwapResult:
        """
        Buy a token with native currency
        
        Args:
            chain: Target chain
            token_address: Token to buy
            amount_in_native: Amount of native token to spend
            max_slippage: Maximum acceptable slippage
        
        Returns:
            SwapResult
        """
        config = CHAIN_CONFIGS[chain]
        native_token = config.wrapped_native
        
        if not native_token:
            return SwapResult(success=False, error="Native token not configured")
        
        # Get quote
        quote = await self.get_quote(
            chain, native_token, token_address, 
            amount_in_native, max_slippage
        )
        
        if not quote:
            return SwapResult(success=False, error="Failed to get quote")
        
        # Check price impact
        if quote.price_impact > 5:
            logger.warning(f"High price impact: {quote.price_impact}%")
            if quote.price_impact > 10:
                return SwapResult(success=False, error=f"Price impact too high: {quote.price_impact}%")
        
        # Execute
        return await self.execute_swap(chain, quote)
    
    async def sell_token(self, chain: Chain, token_address: str,
                        amount: float, max_slippage: float = None) -> SwapResult:
        """
        Sell a token for native currency
        
        Args:
            chain: Target chain
            token_address: Token to sell
            amount: Amount of token to sell
            max_slippage: Maximum acceptable slippage
        
        Returns:
            SwapResult
        """
        config = CHAIN_CONFIGS[chain]
        native_token = config.wrapped_native
        
        if not native_token:
            return SwapResult(success=False, error="Native token not configured")
        
        # Get quote
        quote = await self.get_quote(
            chain, token_address, native_token,
            amount, max_slippage
        )
        
        if not quote:
            return SwapResult(success=False, error="Failed to get quote")
        
        # Execute
        return await self.execute_swap(chain, quote)
    
    async def sell_percent(self, chain: Chain, token_address: str,
                          percent: float, max_slippage: float = None) -> SwapResult:
        """
        Sell a percentage of token holdings
        
        Args:
            chain: Target chain
            token_address: Token to sell
            percent: Percentage to sell (0-100)
            max_slippage: Maximum acceptable slippage
        
        Returns:
            SwapResult
        """
        wallet = getattr(self.wallets, chain.value.upper(), None)
        if not wallet:
            return SwapResult(success=False, error="No wallet for chain")
        
        # Get balance
        balance = await self.rpc.get_token_balance(chain, wallet, token_address)
        if not balance or balance <= 0:
            return SwapResult(success=False, error="No balance to sell")
        
        # Calculate amount
        amount = balance * (percent / 100)
        
        return await self.sell_token(chain, token_address, amount, max_slippage)
    
    # ============================================================
    # UTILITIES
    # ============================================================
    
    async def get_token_price(self, chain: Chain, token_address: str) -> Optional[float]:
        """Get current token price in USD"""
        if chain == Chain.SOL:
            url = f"{API_CONFIG.jupiter_price}/price?ids={token_address}"
            try:
                async with self.session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("data", {}).get(token_address, {}).get("price")
            except:
                pass
        return None
    
    async def check_balance(self, chain: Chain) -> float:
        """Check native token balance"""
        wallet = getattr(self.wallets, chain.value.upper(), None)
        if not wallet:
            return 0
        
        balance = await self.rpc.get_balance(chain, wallet)
        return balance or 0


# Singleton
_execution_engine: Optional[ExecutionEngine] = None

def get_execution_engine(wallets: WalletConfig = None, 
                        mode: TradingMode = None) -> ExecutionEngine:
    global _execution_engine
    if _execution_engine is None:
        _execution_engine = ExecutionEngine(
            wallets or WalletConfig(),
            mode or TradingMode.SIMULATION
        )
    return _execution_engine

async def shutdown_execution_engine():
    global _execution_engine
    if _execution_engine:
        await _execution_engine.stop()
        _execution_engine = None
