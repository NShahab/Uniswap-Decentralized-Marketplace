"""Base class for step-by-step contract testing."""

import os
import logging
from abc import ABC, abstractmethod
from web3 import Web3
from .web3_utils import init_web3, get_contract
from .price_utils import TickCalculator

logger = logging.getLogger('test_base')

class LiquidityTestBase(ABC):
    """Base class for liquidity position testing."""
    
    def __init__(self, contract_address: str, contract_name: str):
        """Initialize test with contract info."""
        self.contract_address = contract_address
        self.contract_name = contract_name
        self.contract = None
        self.token0 = None
        self.token1 = None
        self.tick_calculator = TickCalculator()
        
    def setup(self) -> bool:
        """مرحله اول: راه‌اندازی و اتصال"""
        try:
            # تست اتصال به شبکه
            if not init_web3():
                logger.error("Web3 initialization failed")
                return False
                
            # لود کردن قرارداد
            self.contract = get_contract(self.contract_address, self.contract_name)
            
            # دریافت آدرس توکن‌ها
            self.token0 = self.contract.functions.token0().call()
            self.token1 = self.contract.functions.token1().call()
            
            logger.info(f"Setup completed for {self.contract_name}")
            return True
            
        except Exception as e:
            logger.error(f"Setup failed: {e}")
            return False
            
    def check_balances(self) -> bool:
        """مرحله دوم: بررسی موجودی"""
        try:
            # دریافت موجودی توکن‌ها
            token0_contract = get_contract(self.token0, "IERC20")
            token1_contract = get_contract(self.token1, "IERC20")
            
            balance0 = token0_contract.functions.balanceOf(self.contract_address).call()
            balance1 = token1_contract.functions.balanceOf(self.contract_address).call()
            
            # دریافت تعداد اعشار
            decimals0 = token0_contract.functions.decimals().call()
            decimals1 = token1_contract.functions.decimals().call()
            
            # تبدیل به مقادیر قابل خواندن
            readable_balance0 = balance0 / (10 ** decimals0)
            readable_balance1 = balance1 / (10 ** decimals1)
            
            logger.info(f"Token0 balance: {readable_balance0}")
            logger.info(f"Token1 balance: {readable_balance1}")
            
            return balance0 > 0 and balance1 > 0
            
        except Exception as e:
            logger.error(f"Balance check failed: {e}")
            return False
            
    @abstractmethod
    def calculate_ticks(self) -> tuple:
        """مرحله سوم: محاسبه تیک‌ها - باید در کلاس فرزند پیاده‌سازی شود"""
        pass
        
    @abstractmethod
    def adjust_position(self) -> bool:
        """مرحله چهارم: تنظیم موقعیت - باید در کلاس فرزند پیاده‌سازی شود"""
        pass
        
    def execute_test_steps(self) -> bool:
        """اجرای تمام مراحل تست به صورت پله به پله"""
        try:
            # مرحله 1: راه‌اندازی
            logger.info("Step 1: Setup")
            if not self.setup():
                return False
                
            # مرحله 2: بررسی موجودی
            logger.info("Step 2: Balance Check")
            if not self.check_balances():
                logger.warning("Low or zero balances detected")
                # ادامه می‌دهیم چون ممکن است نیاز به تامین موجودی باشد
                
            # مرحله 3: محاسبه تیک‌ها
            logger.info("Step 3: Tick Calculation")
            lower_tick, upper_tick = self.calculate_ticks()
            if lower_tick is None or upper_tick is None:
                return False
                
            # مرحله 4: تنظیم موقعیت
            logger.info("Step 4: Position Adjustment")
            if not self.adjust_position():
                return False
                
            logger.info("All test steps completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            return False

    def get_position_info(self) -> dict:
        """دریافت اطلاعات موقعیت فعلی"""
        try:
            if hasattr(self.contract.functions, 'getCurrentPosition'):
                pos = self.contract.functions.getCurrentPosition().call()
                return {
                    'tokenId': pos[0],
                    'hasPosition': pos[1],
                    'tickLower': pos[2],
                    'tickUpper': pos[3],
                    'liquidity': pos[4]
                }
            elif hasattr(self.contract.functions, 'currentPosition'):
                pos = self.contract.functions.currentPosition().call()
                return {
                    'tokenId': pos[0],
                    'liquidity': pos[1],
                    'tickLower': pos[2],
                    'tickUpper': pos[3],
                    'active': pos[4]
                }
            else:
                raise AttributeError("Contract has no position query method")
                
        except Exception as e:
            logger.error(f"Failed to get position info: {e}")
            return None