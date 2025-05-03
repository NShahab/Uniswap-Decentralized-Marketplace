# test_base.py

import os
import logging
from abc import ABC, abstractmethod
from web3 import Web3
from decimal import Decimal  # Add this import for Decimal
from .web3_utils import init_web3, get_contract, w3  # Import w3 instance

logger = logging.getLogger('test_base')

class LiquidityTestBase(ABC):
    """Base class for liquidity position testing."""

    def __init__(self, contract_address: str, contract_name: str):
        """Initialize test with contract info."""
        if not contract_address:
            raise ValueError("Contract address cannot be empty")
        self.contract_address = Web3.to_checksum_address(contract_address)  # Store checksummed
        self.contract_name = contract_name
        self.contract = None
        self.token0 = None
        self.token1 = None
        self.token0_decimals = None
        self.token1_decimals = None

    def setup(self) -> bool:
        """Initialize connection and contracts."""
        try:
            if not init_web3():  # Ensure Web3 is initialized and connected
                logger.error("Web3 initialization failed")
                return False

            logger.info(f"Setting up test for {self.contract_name} at {self.contract_address}")
            # Load main contract
            self.contract = get_contract(self.contract_address, self.contract_name)
            if not self.contract:
                logger.error(f"Failed to load contract {self.contract_name}")
                return False

            # Get token addresses and decimals
            self.token0 = Web3.to_checksum_address(self.contract.functions.token0().call())
            self.token1 = Web3.to_checksum_address(self.contract.functions.token1().call())
            # Get decimals directly from the main contract if available (as per your contract)
            if hasattr(self.contract.functions, 'token0Decimals'):
                self.token0_decimals = self.contract.functions.token0Decimals().call()
            else:  # Fallback to calling token directly
                token0_contract = get_contract(self.token0, "IERC20")
                self.token0_decimals = token0_contract.functions.decimals().call()

            if hasattr(self.contract.functions, 'token1Decimals'):
                self.token1_decimals = self.contract.functions.token1Decimals().call()
            else:  # Fallback
                token1_contract = get_contract(self.token1, "IERC20")
                self.token1_decimals = token1_contract.functions.decimals().call()

            logger.info(f"Token0: {self.token0} (Decimals: {self.token0_decimals})")
            logger.info(f"Token1: {self.token1} (Decimals: {self.token1_decimals})")

            # Basic check if contract methods exist (example)
            if not hasattr(self.contract.functions, 'updatePredictionAndAdjust'):  # Check a key method
                logger.warning(f"Method 'updatePredictionAndAdjust' not found on contract {self.contract_name}. Adapt if needed.")
                # Add checks for other essential methods used in your test logic

            logger.info(f"Setup completed for {self.contract_name}")
            return True

        except Exception as e:
            logger.exception(f"Setup failed for {self.contract_name} at {self.contract_address}: {e}")  # Use logger.exception for traceback
            return False

    # fund_contract is removed from base, handle in derived class if needed

    def check_balances(self) -> bool:
        """Step 2: Check contract's token balances."""
        if not self.contract or not self.token0 or not self.token1:
            logger.error("Contract or tokens not initialized. Run setup first.")
            return False
        try:
            token0_contract = get_contract(self.token0, "IERC20")
            token1_contract = get_contract(self.token1, "IERC20")

            balance0_wei = token0_contract.functions.balanceOf(self.contract_address).call()
            balance1_wei = token1_contract.functions.balanceOf(self.contract_address).call()

            readable_balance0 = Decimal(balance0_wei) / (10 ** self.token0_decimals)
            readable_balance1 = Decimal(balance1_wei) / (10 ** self.token1_decimals)

            logger.info(f"Contract Token0 ({self.token0[-6:]}) balance: {readable_balance0:.6f}")
            logger.info(f"Contract Token1 ({self.token1[-6:]}) balance: {readable_balance1:.6f}")

            # Return True even if balances are zero, adjustment logic should handle this
            return True

        except Exception as e:
            logger.exception(f"Balance check failed: {e}")
            return False

    @abstractmethod
    def adjust_position(self) -> bool:
        """Abstract method for adjusting the position. Implement in derived class."""
        pass

    @abstractmethod
    def save_metrics(self, receipt: dict = None, success: bool = False, error_message: str = None):
        """Abstract method for saving metrics. Implement in derived class."""
        pass

    def execute_test_steps(self) -> bool:
        """Execute all test steps sequentially."""
        try:
            # Step 1: Setup
            logger.info("--- Test Step 1: Setup ---")
            if not self.setup():
                logger.error("Setup failed. Aborting test.")
                return False

            # Step 2: Balance Check (Informational)
            logger.info("--- Test Step 2: Balance Check ---")
            self.check_balances()  # Log balances, don't abort if zero

            # Step 3: Position Adjustment (Core Logic)
            logger.info("--- Test Step 3: Position Adjustment ---")
            if not self.adjust_position():
                logger.error("Position adjustment failed.")
                # Metrics should be saved within adjust_position or its called methods
                return False

            logger.info("--- All test steps completed successfully ---")
            return True

        except Exception as e:
            logger.exception(f"Test execution failed during steps: {e}")
            # Attempt to save failure state if possible
            try:
                self.save_metrics(success=False, error_message=f"Test Execution Aborted: {str(e)}")
            except Exception as save_err:
                logger.error(f"Also failed to save metrics during exception handling: {save_err}")
            return False

    def get_position_info(self) -> dict:
        """Get current position info from the contract's 'currentPosition' state variable."""
        if not self.contract:
            logger.error("Contract not initialized. Run setup first.")
            return None
        try:
            # Access the public state variable 'currentPosition'
            # The order of returned values matches the struct definition:
            # (tokenId, liquidity, tickLower, tickUpper, active)
            pos_data = self.contract.functions.currentPosition().call()
            position = {
                'tokenId': pos_data[0],
                'liquidity': pos_data[1],
                'tickLower': pos_data[2],
                'tickUpper': pos_data[3],
                'active': pos_data[4]  # Use the 'active' flag from the struct
            }
            logger.debug(f"Fetched Position Info: {position}")
            return position
        except Exception as e:
            logger.exception(f"Failed to get position info using currentPosition(): {e}")
            return None