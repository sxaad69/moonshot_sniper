"""
Moonshot Sniper Bot - RPC Manager
Multi-chain RPC with rotation, failover, health monitoring, and caching
"""

import asyncio
import aiohttp
import time
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
import logging

from config.settings import Chain, ChainConfig, RPCEndpoint, CHAIN_CONFIGS, WalletConfig

logger = logging.getLogger(__name__)

@dataclass
class RPCHealth:
    endpoint: RPCEndpoint
    is_healthy: bool = True
    last_success: float = 0
    last_failure: float = 0
    consecutive_failures: int = 0
    avg_latency_ms: float = 0
    total_requests: int = 0
    failed_requests: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0: return 1.0
        return (self.total_requests - self.failed_requests) / self.total_requests
    
    def record_success(self, latency_ms: float):
        self.last_success = time.time()
        self.consecutive_failures = 0
        self.is_healthy = True
        self.total_requests += 1
        self.avg_latency_ms = (self.avg_latency_ms * (self.total_requests - 1) + latency_ms) / self.total_requests
    
    def record_failure(self):
        self.last_failure = time.time()
        self.consecutive_failures += 1
        self.total_requests += 1
        self.failed_requests += 1
        if self.consecutive_failures >= 3:
            self.is_healthy = False
            logger.warning(f"RPC {self.endpoint.name} marked unhealthy")


class RPCManager:
    """Multi-chain RPC manager with rotation, failover, and caching"""
    
    def __init__(self, wallets: WalletConfig):
        self.wallets = wallets
        self.active_chains = wallets.get_active_chains()
        self.session: Optional[aiohttp.ClientSession] = None
        self.health: Dict[Chain, List[RPCHealth]] = {}
        self.current_index: Dict[Chain, int] = {}
        self.request_times: Dict[str, List[float]] = {}
        self.cache: Dict[str, tuple] = {}
        self.cache_ttl: float = 2.0
        self._initialize()
        logger.info(f"RPC Manager initialized for {[c.value for c in self.active_chains]}")
    
    def _initialize(self):
        for chain in self.active_chains:
            config = CHAIN_CONFIGS[chain]
            self.health[chain] = [RPCHealth(endpoint=rpc) for rpc in config.rpcs]
            self.current_index[chain] = 0
            for rpc in config.rpcs:
                self.request_times[rpc.url] = []
    
    async def start(self):
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self.session = aiohttp.ClientSession(timeout=timeout)
        logger.info("RPC Manager started")
    
    async def stop(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    def _get_healthy_endpoint(self, chain: Chain) -> Optional[RPCHealth]:
        if chain not in self.health: return None
        endpoints = self.health[chain]
        start_idx = self.current_index[chain]
        for i in range(len(endpoints)):
            idx = (start_idx + i) % len(endpoints)
            if endpoints[idx].is_healthy:
                self.current_index[chain] = (idx + 1) % len(endpoints)
                return endpoints[idx]
        oldest = min(endpoints, key=lambda e: e.last_failure)
        oldest.is_healthy = True
        return oldest
    
    def _check_rate_limit(self, url: str, limit: int) -> bool:
        now = time.time()
        self.request_times[url] = [t for t in self.request_times.get(url, []) if now - t < 1]
        return len(self.request_times[url]) < limit
    
    def _record_request(self, url: str):
        if url not in self.request_times: self.request_times[url] = []
        self.request_times[url].append(time.time())
    
    def _get_cache(self, key: str) -> Optional[Any]:
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.cache_ttl:
                return value
            del self.cache[key]
        return None
    
    def _set_cache(self, key: str, value: Any):
        self.cache[key] = (value, time.time())
        # Clean old cache entries
        if len(self.cache) > 1000:
            now = time.time()
            self.cache = {k: v for k, v in self.cache.items() if now - v[1] < self.cache_ttl}
    
    async def request(self, chain: Chain, method: str = "POST", 
                      payload: Optional[Dict] = None, use_cache: bool = True) -> Optional[Dict]:
        if chain not in self.active_chains:
            return None
        if not self.session: await self.start()
        
        cache_key = f"{chain.value}:{str(payload)}"
        if use_cache:
            cached = self._get_cache(cache_key)
            if cached: return cached
        
        for attempt in range(3):
            rpc_health = self._get_healthy_endpoint(chain)
            if not rpc_health: return None
            
            endpoint = rpc_health.endpoint
            if not self._check_rate_limit(endpoint.url, endpoint.rate_limit):
                rpc_health.is_healthy = False
                continue
            
            try:
                start_time = time.time()
                self._record_request(endpoint.url)
                
                async with self.session.request(method, endpoint.url, json=payload,
                    headers={"Content-Type": "application/json"}) as response:
                    latency_ms = (time.time() - start_time) * 1000
                    if response.status == 200:
                        data = await response.json()
                        rpc_health.record_success(latency_ms)
                        if use_cache: self._set_cache(cache_key, data)
                        return data
                    else:
                        rpc_health.record_failure()
            except asyncio.TimeoutError:
                rpc_health.record_failure()
            except Exception as e:
                logger.warning(f"RPC error: {e}")
                rpc_health.record_failure()
        
        return None
    
    async def get_balance(self, chain: Chain, address: str) -> Optional[float]:
        if chain == Chain.SOL:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}
            response = await self.request(chain, payload=payload)
            if response and "result" in response:
                return response["result"]["value"] / 1e9
        else:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [address, "latest"]}
            response = await self.request(chain, payload=payload)
            if response and "result" in response:
                return int(response["result"], 16) / 1e18
        return None
    
    async def get_token_balance(self, chain: Chain, wallet: str, token: str) -> Optional[float]:
        if chain == Chain.SOL:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [wallet, {"mint": token}, {"encoding": "jsonParsed"}]
            }
            response = await self.request(chain, payload=payload)
            if response and "result" in response:
                accounts = response["result"]["value"]
                if accounts:
                    info = accounts[0]["account"]["data"]["parsed"]["info"]
                    return float(info["tokenAmount"]["uiAmount"])
        return None
    
    async def get_latest_blockhash(self, chain: Chain) -> Optional[str]:
        if chain != Chain.SOL: return None
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash",
                   "params": [{"commitment": "finalized"}]}
        response = await self.request(chain, payload=payload, use_cache=False)
        if response and "result" in response:
            return response["result"]["value"]["blockhash"]
        return None
    
    async def send_transaction(self, chain: Chain, signed_tx: str) -> Optional[str]:
        if chain == Chain.SOL:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
                       "params": [signed_tx, {"encoding": "base64", "skipPreflight": False,
                                              "preflightCommitment": "confirmed"}]}
        else:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_sendRawTransaction",
                       "params": [signed_tx]}
        
        response = await self.request(chain, payload=payload, use_cache=False)
        if response and "result" in response:
            return response["result"]
        if response and "error" in response:
            logger.error(f"TX error: {response['error']}")
        return None
    
    def get_health_report(self) -> Dict[str, Any]:
        report = {}
        for chain in self.active_chains:
            report[chain.value] = [{
                "name": h.endpoint.name, "healthy": h.is_healthy,
                "success_rate": f"{h.success_rate*100:.1f}%",
                "latency_ms": f"{h.avg_latency_ms:.0f}"
            } for h in self.health[chain]]
        return report


_rpc_manager: Optional[RPCManager] = None

def get_rpc_manager(wallets: Optional[WalletConfig] = None) -> RPCManager:
    global _rpc_manager
    if _rpc_manager is None:
        _rpc_manager = RPCManager(wallets or WalletConfig())
    return _rpc_manager

async def shutdown_rpc_manager():
    global _rpc_manager
    if _rpc_manager:
        await _rpc_manager.stop()
        _rpc_manager = None
