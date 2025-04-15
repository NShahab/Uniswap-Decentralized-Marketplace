"""Price-related utility functions."""

import math
import logging
import requests
from typing import Tuple

logger = logging.getLogger('price_utils')

class TickCalculator:
    # Constants for Uniswap V3
    MIN_TICK = -887272
    MAX_TICK = 887272
    MIN_SQRT_RATIO = 4295128739
    MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342
    TWO_POW_96 = 2**96
    LOG_1_0001 = math.log(1.0001)
    
    @staticmethod
    def floor_to_tick_spacing(tick: int, tick_spacing: int) -> int:
        """Floor a tick value to the nearest tick spacing."""
        if tick_spacing <= 0:
            return tick
            
        compressed = tick // tick_spacing
        if tick < 0 and tick % tick_spacing != 0:
            compressed -= 1
        return compressed * tick_spacing
        
    @classmethod
    def price_to_tick(cls, price: float, token0_decimals: int, token1_decimals: int) -> int:
        """Convert a price to its corresponding tick.
        
        Args:
            price: Price of token0 in terms of token1 (e.g. ETH/USDC)
            token0_decimals: Decimals of token0 (e.g. 18 for ETH)
            token1_decimals: Decimals of token1 (e.g. 6 for USDC)
            
        Returns:
            The calculated tick value
        """
        try:
            # Adjust for decimal differences
            decimal_adjustment = token1_decimals - token0_decimals
            price_adjusted = price * (10 ** decimal_adjustment)
            
            # Get sqrt_ratio_x96
            sqrt_price = math.sqrt(1 / price_adjusted)
            sqrt_ratio_x96 = int(sqrt_price * cls.TWO_POW_96)
            
            # Ensure within bounds
            sqrt_ratio_x96 = max(cls.MIN_SQRT_RATIO, min(cls.MAX_SQRT_RATIO, sqrt_ratio_x96))
            
            # Calculate tick
            tick = int(math.log(sqrt_price) / (0.5 * cls.LOG_1_0001))
            tick = max(cls.MIN_TICK, min(cls.MAX_TICK, tick))
            
            return tick
            
        except Exception as e:
            logger.error(f"Error in price_to_tick: {e}")
            return 0
            
    @classmethod
    def calculate_tick_range(cls, current_tick: int, tick_spacing: int, 
                           range_multiplier: int = 4) -> Tuple[int, int]:
        """Calculate lower and upper ticks for a position.
        
        Args:
            current_tick: The current tick from the pool
            tick_spacing: The pool's tick spacing
            range_multiplier: How many tick spacings to use for range (default 4)
            
        Returns:
            (lower_tick, upper_tick) tuple
        """
        # Calculate half width
        half_width = (tick_spacing * range_multiplier) // 2
        if half_width <= 0:
            half_width = tick_spacing
            
        # Calculate raw boundaries
        lower_tick = current_tick - half_width
        upper_tick = current_tick + half_width
        
        # Floor to tick spacing
        lower_tick = cls.floor_to_tick_spacing(lower_tick, tick_spacing)
        upper_tick = cls.floor_to_tick_spacing(upper_tick, tick_spacing)
        
        # Ensure proper spacing
        if upper_tick <= lower_tick:
            upper_tick = lower_tick + tick_spacing
            
        # Ensure within bounds
        lower_tick = max(cls.MIN_TICK, lower_tick)
        upper_tick = min(cls.MAX_TICK, upper_tick)
        
        return lower_tick, upper_tick
        
    @classmethod
    def tick_to_price(cls, tick: int, token0_decimals: int, token1_decimals: int) -> float:
        """Convert a tick to its corresponding price.
        
        Args:
            tick: The tick value
            token0_decimals: Decimals of token0
            token1_decimals: Decimals of token1
            
        Returns:
            The calculated price
        """
        try:
            # Calculate sqrt price
            sqrt_price = math.exp(tick * 0.5 * cls.LOG_1_0001)
            
            # Calculate price
            price = sqrt_price * sqrt_price
            
            # Adjust for decimals
            decimal_adjustment = token1_decimals - token0_decimals
            adjusted_price = price / (10 ** decimal_adjustment)
            
            return adjusted_price
            
        except Exception as e:
            logger.error(f"Error in tick_to_price: {e}")
            return 0.0

# Constants for tick calculation
LOG_1_0001 = math.log(1.0001)
TWO_POW_96 = 2**96
MIN_TICK = -887272
MAX_TICK = 887272

def get_predicted_price():
    """Get predicted ETH price from API or use fallback."""
    try:
        response = requests.get('https://api.coinbase.com/v2/prices/ETH-USD/spot', timeout=10)
        response.raise_for_status()
        price = float(response.json()['data']['amount'])
        logger.info(f"Fetched ETH price: {price} USD")
        return {"original": price}
    except Exception as e:
        logger.warning(f"Error getting price from Coinbase: {e}")
        fallback_price = 3000.0
        logger.warning(f"Using fallback price: {fallback_price} USD")
        return {"original": fallback_price}

def calculate_tick_range(center_tick, tick_spacing, range_multiplier=4):
    """Calculate lower and upper ticks for a position."""
    half_width = (tick_spacing * range_multiplier) // 2
    if half_width <= 0:
        half_width = tick_spacing

    lower_tick = center_tick - half_width
    upper_tick = center_tick + half_width

    # Ensure ticks are within bounds
    lower_tick = max(MIN_TICK, lower_tick)
    upper_tick = min(MAX_TICK, upper_tick)

    # Align to tick spacing
    lower_tick = (lower_tick // tick_spacing) * tick_spacing
    upper_tick = (upper_tick // tick_spacing) * tick_spacing

    return lower_tick, upper_tick

def price_to_tick(price, token0_decimals, token1_decimals):
    """Convert a price to its corresponding tick."""
    # Adjust for decimal differences
    decimal_adjustment = token1_decimals - token0_decimals
    price_adjusted = price * (10 ** decimal_adjustment)
    
    # Calculate sqrt price
    sqrt_price = math.sqrt(1 / price_adjusted)
    sqrt_price_x96 = int(sqrt_price * TWO_POW_96)
    
    # Calculate tick
    tick = int(math.log(sqrt_price) / LOG_1_0001)
    return tick