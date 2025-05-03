# predictive_test.py

import os
import sys
import json
import time
import logging
import requests
import math
import csv
from datetime import datetime
from pathlib import Path
from web3 import Web3
from eth_account import Account
from decimal import Decimal, getcontext

# Set precision for Decimal calculations
getcontext().prec = 50 # Set precision high enough for sqrt price calculations

# --- Adjust path to import from sibling 'utils' directory ---
# Assumes predictive_test.py is in 'tests' folder and utils is also in 'tests'
# ProjectRoot -> tests -> predictive_test.py
# ProjectRoot -> tests -> utils -> ...
current_dir = Path(__file__).parent
utils_dir = current_dir / 'utils'
sys.path.append(str(utils_dir.parent)) # Add 'tests' folder to sys.path

from utils.test_base import LiquidityTestBase
from utils.web3_utils import send_transaction, init_web3, get_contract, wrap_eth_to_weth, w3 # Import w3

# Constants
MIN_WETH_BALANCE = Web3.to_wei(0.01, 'ether') # Adjust if needed for mainnet fork amounts
MIN_USDC_BALANCE = 10 * (10**6)  # 10 USDC (assuming 6 decimals for mainnet USDC)
TWO_POW_96 = Decimal(2**96)

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("predictive_test.log"), # Log to a file
        logging.StreamHandler() # Also log to console
    ]
)
logger = logging.getLogger('predictive_test')

# --- Define path for deployed addresses and results ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent # Goes up from tests folder to project root
ADDRESS_FILE = PROJECT_ROOT / 'deployed_addresses.json'
RESULTS_FILE = PROJECT_ROOT / 'position_results.csv'
LSTM_API_URL = os.getenv('LSTM_API_URL', 'http://127.0.0.1:5000/predict') # Get from ENV or default

class PredictiveTest(LiquidityTestBase):
    """Implementation for PredictiveLiquidityManager contract testing on a fork."""

    def __init__(self, contract_address: str):
        super().__init__(contract_address, "PredictiveLiquidityManager")
        self.metrics = self._reset_metrics() # Initialize metrics
        self.pool_address = None
        self.pool_contract = None

    def _reset_metrics(self):
        """Resets the metrics dictionary for a new run."""
        return {
            'timestamp': None,
            'contract_type': 'Predictive',
            'action_taken': 'init', # 'init', 'skipped', 'adjusted_success', 'adjusted_failed', 'funding_failed'
            'tx_hash': None,
            # 'input_price': 0, # Removed, using actualPrice from pool
            'predictedPrice_api': None, # Price from LSTM API
            'predictedTick_calculated': None, # Tick calculated from API price
            'actualPrice_pool': None, # Price derived from pool's sqrtPriceX96
            'sqrtPriceX96_pool': 0, # sqrtPriceX96 from pool slot0
            'currentTick_pool': 0, # Current tick from pool slot0
            'targetTickLower_calculated': 0, # Calculated lower tick for adjustment
            'targetTickUpper_calculated': 0, # Calculated upper tick for adjustment
            'finalTickLower_contract': 0, # Actual lower tick of position after adjustment (if any)
            'finalTickUpper_contract': 0, # Actual upper tick of position after adjustment (if any)
            'liquidity_contract': 0, # Liquidity of position after adjustment (if any)
            'gas_used': 0,
            'gas_cost_eth': 0.0,
            'error_message': ""
        }

    def setup(self) -> bool:
        """Override setup to also get pool contract."""
        if not super().setup():
            return False
        try:
            # Get the pool address associated with the manager contract
            factory_address = self.contract.functions.factory().call()
            factory_contract = get_contract(factory_address, "IUniswapV3Factory")
            fee = self.contract.functions.fee().call()
            self.pool_address = factory_contract.functions.getPool(self.token0, self.token1, fee).call()

            if self.pool_address == '0x0000000000000000000000000000000000000000':
                logger.error(f"Uniswap V3 Pool not found for {self.token0}/{self.token1} fee {fee}")
                return False

            self.pool_contract = get_contract(self.pool_address, "IUniswapV3Pool")
            logger.info(f"Uniswap V3 Pool found at: {self.pool_address}")
            return True
        except Exception as e:
            logger.exception(f"Failed to get Uniswap pool during setup: {e}")
            return False

    def get_predicted_price_from_api(self) -> float | None:
        """Get predicted ETH price from the LSTM API."""
        try:
            logger.info(f"Querying LSTM API at {LSTM_API_URL}...")
            # --- ADJUST API CALL AS NEEDED ---
            # This assumes your API returns JSON like {'predicted_price': 3450.67}
            response = requests.get(LSTM_API_URL, timeout=15) # Increased timeout
            response.raise_for_status() # Raise exception for bad status codes
            data = response.json()
            predicted_price = float(data['predicted_price']) # Adjust key if needed
            logger.info(f"Received predicted ETH price from API: {predicted_price:.2f} USD")
            self.metrics['predictedPrice_api'] = predicted_price
            return predicted_price
        except requests.exceptions.RequestException as e:
            logger.error(f"Error contacting LSTM API: {e}")
            self.metrics['error_message'] = f"API_RequestError: {e}"
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Error parsing API response: {e}. Response: {response.text[:200]}")
            self.metrics['error_message'] = f"API_ResponseParseError: {e}"
            return None
        except Exception as e:
            logger.exception(f"Unexpected error getting prediction from API: {e}")
            self.metrics['error_message'] = f"API_UnexpectedError: {e}"
            return None

    def calculate_tick_from_price(self, price: float) -> int | None:
        """Convert price (e.g., ETH/USD) to Uniswap v3 tick (ETH/USDC).
        Assumes token0 is USDC (decimals 6) and token1 is WETH (decimals 18).
        Handles potential ordering differences.
        """
        if not self.token0_decimals or not self.token1_decimals:
            logger.error("Token decimals not set. Run setup first.")
            return None
        try:
            # Determine which token corresponds to the 'price' (e.g., ETH in ETH/USD)
            # This logic assumes price is Price(Token1)/Price(Token0), e.g. WETH/USDC
            # If your price prediction is USD/ETH, you need to invert it first.
            price_decimal = Decimal(str(price))

            # Calculate price ratio considering decimals: P_t1/P_t0 * 10^(dec0 - dec1)
            adjusted_ratio = price_decimal * (Decimal(10) ** (self.token0_decimals - self.token1_decimals))

            # Calculate sqrtPriceX96 = sqrt(adjusted_ratio) * 2^96
            sqrt_ratio = adjusted_ratio.sqrt()
            sqrt_price_x96 = sqrt_ratio * TWO_POW_96

            # Calculate tick = floor(log_sqrt(1.0001)(sqrtPriceX96 / 2^96))
            # Using Decimal for logarithm calculation might be overly complex,
            # standard math log should be sufficient given the scale.
            # Ensure sqrt_price_x96 is converted to float for math.log
            log_arg = float(sqrt_price_x96 / TWO_POW_96)
            if log_arg <= 0:
                logger.error(f"Cannot calculate log for non-positive sqrtPrice ratio: {log_arg}")
                return None

            tick = math.floor(math.log(log_arg, 1.0001))

            # Clamp tick to valid range
            MIN_TICK = -887272
            MAX_TICK = 887272
            tick = max(MIN_TICK, min(MAX_TICK, tick))

            logger.info(f"Calculated tick {tick} from price {price:.2f}")
            self.metrics['predictedTick_calculated'] = tick
            return tick
        except Exception as e:
            logger.exception(f"Failed to calculate predicted tick from price {price}: {e}")
            self.metrics['error_message'] = f"TickCalculationError: {e}"
            return None

    def update_pool_and_position_metrics(self):
        """Fetches current pool price/tick and contract position state."""
        try:
            # Get Pool State (Slot0)
            if self.pool_contract:
                slot0 = self.pool_contract.functions.slot0().call()
                sqrt_price_x96_pool = slot0[0]
                current_tick_pool = slot0[1]
                self.metrics['sqrtPriceX96_pool'] = sqrt_price_x96_pool
                self.metrics['currentTick_pool'] = current_tick_pool

                # Calculate actual price from pool sqrtPriceX96
                price_ratio = (Decimal(sqrt_price_x96_pool) / TWO_POW_96) ** 2
                price_t1_t0_adj = price_ratio / (Decimal(10)**(self.token0_decimals - self.token1_decimals))
                actual_price = float(price_t1_t0_adj) if price_t1_t0_adj else 0.0
                self.metrics['actualPrice_pool'] = actual_price
                logger.info(f"Pool State: Tick={current_tick_pool}, SqrtPriceX96={sqrt_price_x96_pool}, ActualPrice={actual_price:.2f}")
            else:
                logger.warning("Pool contract not available, cannot fetch pool state.")

            # Get Contract Position State
            position_info = self.get_position_info() # Uses method from base class
            if position_info:
                self.metrics['finalTickLower_contract'] = position_info.get('tickLower', 0)
                self.metrics['finalTickUpper_contract'] = position_info.get('tickUpper', 0)
                self.metrics['liquidity_contract'] = position_info.get('liquidity', 0)
                logger.info(f"Contract Position: Active={position_info.get('active')}, Liq={position_info.get('liquidity')}, Range=[{position_info.get('tickLower')}, {position_info.get('tickUpper')}]")
            else:
                logger.warning("Could not get position info from contract.")

        except Exception as e:
            logger.exception(f"Error updating pool/position metrics: {e}")
            # Store error in metrics if needed, but don't stop the flow yet
            if not self.metrics['error_message']: # Don't overwrite previous errors
                self.metrics['error_message'] = f"MetricsUpdateError: {e}"


    # --- Funding Logic Removed ---
    # Remove the fund_contract method from here.
    # Ensure the deployer account is funded with ETH, WETH, and USDC
    # *before* running this Python script, ideally during the fork setup.
    # You can use Hardhat tasks or RPC methods like `hardhat_setBalance`
    # and `hardhat_setStorageAt` (for token balances) in your setup script.

    def adjust_position(self) -> bool:
        """Adjusts the liquidity position based on the prediction."""
        self.metrics = self._reset_metrics() # Reset metrics at the start of adjustment
        receipt = None # Initialize receipt to None
        adjustment_success = False

        try:
            # --- 1. Get Prediction ---
            predicted_price = self.get_predicted_price_from_api()
            if predicted_price is None:
                logger.error("Failed to get predicted price from API. Skipping adjustment.")
                self.metrics['action_taken'] = 'skipped'
                self.save_metrics(receipt=None, success=False, error_message=self.metrics['error_message'] or "API prediction failed")
                return False

            # --- 2. Calculate Target Tick ---
            predicted_tick = self.calculate_tick_from_price(predicted_price)
            if predicted_tick is None:
                logger.error("Failed to calculate target tick from prediction. Skipping adjustment.")
                self.metrics['action_taken'] = 'skipped'
                self.save_metrics(receipt=None, success=False, error_message=self.metrics['error_message'] or "Tick calculation failed")
                return False

            # --- 3. Update current pool/position metrics (before potential adjustment) ---
            self.update_pool_and_position_metrics()

            # --- 4. Check if Adjustment is Needed (using contract's logic preview) ---
            # Optional: You could call `_calculateTicks` view function if you add it to the contract
            # or replicate the logic here to decide if the call is needed, potentially saving gas.
            # For now, we rely on the contract's internal check.

            # --- 5. Ensure Sufficient Balances (Optional Check) ---
            # Add checks here if you suspect the initial funding might be insufficient
            # logger.info("Checking deployer token balances...")
            # Sufficient funds are assumed to be set during fork initialization.

            # --- 6. Call Contract to Adjust ---
            logger.info(f"Calling updatePredictionAndAdjust with predictedTick: {predicted_tick}")
            private_key = os.getenv('PRIVATE_KEY')
            if not private_key:
                raise ValueError("PRIVATE_KEY environment variable not set.")
            account = Account.from_key(private_key)
            nonce = w3.eth.get_transaction_count(account.address)

            # Build Transaction using contract instance
            tx_function = self.contract.functions.updatePredictionAndAdjust(predicted_tick)
            tx_params = {
                'from': account.address,
                'nonce': nonce,
                'chainId': int(w3.net.version)
                # Gas/GasPrice added by send_transaction
            }
            # Estimate gas specifically for this function call for better accuracy
            try:
                estimated_gas = tx_function.estimate_gas({'from': account.address})
                tx_params['gas'] = int(estimated_gas * 1.2) # Add 20% buffer
                logger.info(f"Estimated gas for adjustment: {estimated_gas}, using: {tx_params['gas']}")
            except Exception as est_err:
                logger.warning(f"Gas estimation failed for adjustment: {est_err}. Using default 1,500,000")
                tx_params['gas'] = 1500000 # Fallback

            built_tx = tx_function.build_transaction(tx_params)

            # Send transaction using utility function
            receipt = send_transaction(built_tx)

            # --- 7. Process Result ---
            if receipt and receipt.status == 1:
                logger.info("Position adjustment transaction successful.")
                self.metrics['action_taken'] = 'adjusted_success'
                adjustment_success = True
            else:
                logger.error("Position adjustment transaction failed or reverted.")
                self.metrics['action_taken'] = 'adjusted_failed'
                # Try to capture revert reason if possible (send_transaction might already log it)
                if not self.metrics['error_message']:
                    self.metrics['error_message'] = "TransactionRevertedOnChain"
                adjustment_success = False

        except Exception as e:
            logger.exception(f"An error occurred during the adjustment process: {e}")
            self.metrics['action_taken'] = 'adjusted_failed'
            self.metrics['error_message'] = f"AdjustmentProcessError: {str(e)}"
            adjustment_success = False

        finally:
            # --- 8. Update Metrics and Save (Always run) ---
            # Fetch final state after transaction attempt
            self.update_pool_and_position_metrics()
            # Save all collected metrics
            self.save_metrics(receipt=receipt, success=adjustment_success, error_message=self.metrics['error_message'])

        return adjustment_success


    def save_metrics(self, receipt: dict = None, success: bool = False, error_message: str = None):
        """Save collected metrics to the CSV file."""
        try:
            self.metrics['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # action_taken is set during the adjust_position flow

            if error_message and not self.metrics['error_message']:
                # Use error message passed in if metrics one is empty
                self.metrics['error_message'] = error_message

            if receipt:
                tx_hash = receipt.get('transactionHash')
                self.metrics['tx_hash'] = tx_hash.hex() if tx_hash else None
                self.metrics['gas_used'] = receipt.get('gasUsed', 0)
                effective_gas_price = receipt.get('effectiveGasPrice')
                if effective_gas_price:
                    gas_cost_wei = self.metrics['gas_used'] * effective_gas_price
                    self.metrics['gas_cost_eth'] = float(Web3.from_wei(gas_cost_wei, 'ether'))
                else: # Handle legacy txns if needed (less likely on fork)
                    gas_price = receipt.get('gasPrice')
                    if gas_price:
                        gas_cost_wei = self.metrics['gas_used'] * gas_price
                        self.metrics['gas_cost_eth'] = float(Web3.from_wei(gas_cost_wei, 'ether'))

            # Ensure RESULTS_FILE path exists
            RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            file_exists = RESULTS_FILE.is_file()

            # Define explicit columns order matching the metrics dict keys used
            columns = [
                'timestamp', 'contract_type', 'action_taken', 'tx_hash',
                'predictedPrice_api', 'predictedTick_calculated',
                'actualPrice_pool', 'sqrtPriceX96_pool', 'currentTick_pool',
                # 'targetTickLower_calculated', 'targetTickUpper_calculated', # Removed as less important than final
                'finalTickLower_contract', 'finalTickUpper_contract', 'liquidity_contract',
                'gas_used', 'gas_cost_eth', 'error_message'
            ]

            # Prepare row data, ensuring all columns exist in metrics or default to ""
            row_data = {col: self.metrics.get(col, "") for col in columns}

            with open(RESULTS_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                if not file_exists:
                    writer.writeheader() # Write header only if file is new
                writer.writerow(row_data)

            logger.info(f"Metrics saved to {RESULTS_FILE}")

        except Exception as e:
            logger.exception(f"Failed to save metrics: {e}")

def main():
    """Main test execution function."""
    logger.info("="*50)
    logger.info("Starting Predictive Liquidity Manager Test on Fork")
    logger.info("="*50)

    try:
        # --- 1. Load Contract Address ---
        if not ADDRESS_FILE.exists():
            logger.error(f"Address file not found: {ADDRESS_FILE}")
            raise FileNotFoundError(f"Address file not found: {ADDRESS_FILE}")

        with open(ADDRESS_FILE, 'r') as f:
            addresses = json.load(f)
            predictive_address = addresses.get('predictiveManager')
            if not predictive_address:
                logger.error("Address 'predictiveManager' not found in address file.")
                raise ValueError("Address 'predictiveManager' not found in address file.")
        logger.info(f"Loaded Predictive Manager Address: {predictive_address}")

        # --- 2. Initialize and Run Test Steps ---
        test = PredictiveTest(predictive_address)
        success = test.execute_test_steps() # This now includes setup, balance check, and adjustment

        if success:
            logger.info("="*50)
            logger.info("Predictive test completed successfully.")
            logger.info("="*50)
        else:
            logger.error("="*50)
            logger.error("Predictive test failed.")
            logger.error("="*50)

    except FileNotFoundError as e:
        logger.error(f"Setup Error: {e}")
    except ValueError as e:
        logger.error(f"Configuration Error: {e}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred during main execution: {e}")

if __name__ == "__main__":
    main()