import asyncio
import random
import signal

from lib.config import logger
from lib.state import stats
from lib.constants import MAX_RETRIES

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    logger.info("Received shutdown signal, finishing current tasks...")
    stats.running = False
    
# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Decorator for retry logic with adaptive backoff
def retry(max_attempts: int = MAX_RETRIES, initial_delay: float = 1.0):
    """Retry decorator with exponential backoff for async functions."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < max_attempts:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    stats.retries += 1
                    if attempts == max_attempts:
                        logger.error(f"Function {func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                        
                    # Calculate backoff with jitter
                    base_delay = initial_delay * (2 ** attempts)
                    jitter = base_delay * random.uniform(0.5, 1.0)
                    wait_time = base_delay + jitter
                    
                    logger.warning(f"Retrying {func.__name__} in {wait_time:.2f}s after error: {e}")
                    
                    # Check for rate limiting indicators
                    rate_limit_terms = ["too many", "too fast", "slow down", "wait", "limit", "temporarily"]
                    if any(term in str(e).lower() for term in rate_limit_terms):
                        stats.throttles += 1
                        # Add extra delay for rate limiting
                        wait_time += random.uniform(5.0, 15.0)
                        logger.warning(f"Possible rate limiting detected, adding extra delay ({wait_time:.2f}s total)")
                        
                    await asyncio.sleep(wait_time)
        return wrapper
    return decorator