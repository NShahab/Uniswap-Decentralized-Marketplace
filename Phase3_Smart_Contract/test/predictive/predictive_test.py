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

# اضافه کردن پوشه test به sys.path برای ایمپورت صحیح utils
sys.path.append(str(Path(__file__).resolve().parent.parent))

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
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # اشاره به Phase3_Smart_Contract
ADDRESS_FILE = PROJECT_ROOT / 'deployed_addresses.json'
RESULTS_FILE = PROJECT_ROOT / 'position_results.csv'
LSTM_API_URL = os.getenv('LSTM_API_URL', 'http://127.0.0.1:5000/predict') # Get from ENV or default
logger.info(f"Looking for deployed_addresses.json at: {ADDRESS_FILE}")

def get_predictive_address():
    """اگر فایل وجود داشت، آخرین آدرس predictiveManager را بخوان، اگر نبود None برگردان. همچنین محتوای فایل را لاگ کن برای دیباگ."""
    import time
    if ADDRESS_FILE.exists():
        # تاخیر کوتاه برای اطمینان از آماده بودن فایل
        time.sleep(1)
        try:
            with open(ADDRESS_FILE, 'r') as f:
                content = f.read()
                logger.info(f"deployed_addresses.json content: {content}")
                addresses = json.loads(content)
                return addresses.get('predictiveManager')
        except Exception as e:
            logger.error(f"Error reading deployed_addresses.json: {e}")
            return None
    else:
        logger.error(f"Address file not found: {ADDRESS_FILE}")
    return None

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
            price_decimal = Decimal(str(price))
            adjusted_ratio = price_decimal * (Decimal(10) ** (self.token0_decimals - self.token1_decimals))
            sqrt_ratio = adjusted_ratio.sqrt()
            sqrt_price_x96 = sqrt_ratio * TWO_POW_96
            log_arg = float(sqrt_price_x96 / TWO_POW_96)
            if log_arg <= 0:
                logger.error(f"Cannot calculate log for non-positive sqrtPrice ratio: {log_arg}")
                return None

            tick = math.floor(math.log(log_arg, 1.0001))
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
            if self.pool_contract:
                slot0 = self.pool_contract.functions.slot0().call()
                sqrt_price_x96_pool = slot0[0]
                current_tick_pool = slot0[1]
                self.metrics['sqrtPriceX96_pool'] = sqrt_price_x96_pool
                self.metrics['currentTick_pool'] = current_tick_pool

                price_ratio = (Decimal(sqrt_price_x96_pool) / TWO_POW_96) ** 2
                price_t1_t0_adj = price_ratio / (Decimal(10)**(self.token0_decimals - self.token1_decimals))
                actual_price = float(price_t1_t0_adj) if price_t1_t0_adj else 0.0
                self.metrics['actualPrice_pool'] = actual_price
                logger.info(f"Pool State: Tick={current_tick_pool}, SqrtPriceX96={sqrt_price_x96_pool}, ActualPrice={actual_price:.2f}")
            else:
                logger.warning("Pool contract not available, cannot fetch pool state.")

            position_info = self.get_position_info()
            if position_info:
                self.metrics['finalTickLower_contract'] = position_info.get('tickLower', 0)
                self.metrics['finalTickUpper_contract'] = position_info.get('tickUpper', 0)
                self.metrics['liquidity_contract'] = position_info.get('liquidity', 0)
                logger.info(f"Contract Position: Active={position_info.get('active')}, Liq={position_info.get('liquidity')}, Range=[{position_info.get('tickLower')}, {position_info.get('tickUpper')}]")
            else:
                logger.warning("Could not get position info from contract.")

        except Exception as e:
            logger.exception(f"Error updating pool/position metrics: {e}")
            if not self.metrics['error_message']:
                self.metrics['error_message'] = f"MetricsUpdateError: {e}"

    def fund_contract_if_needed(self, min_weth=Web3.to_wei(0.05, 'ether'), min_usdc=50 * 10**6):
        """Ensure the contract has at least min_weth and min_usdc. If not, fund it from deployer."""
        from utils.web3_utils import get_contract, send_transaction, wrap_eth_to_weth, w3, init_web3
        import os
        from eth_account import Account
        if not w3 or not w3.is_connected():
            if not init_web3():
                logger.error("Web3 initialization failed in fund_contract_if_needed.")
                return False

        # Get deployer account
        private_key = os.getenv('PRIVATE_KEY')
        if not private_key:
            logger.error("PRIVATE_KEY environment variable not set.")
            return False
        account = Account.from_key(private_key)
        contract_addr = self.contract_address

        # Token addresses
        token0 = self.token0
        token1 = self.token1
        token0_decimals = self.token0_decimals
        token1_decimals = self.token1_decimals

        # Identify which token is WETH and which is USDC by decimals (WETH=18, USDC=6)
        if token0_decimals == 18:
            weth_token = token0
            usdc_token = token1
        else:
            weth_token = token1
            usdc_token = token0

        weth_contract = get_contract(weth_token, "IERC20")
        usdc_contract = get_contract(usdc_token, "IERC20")

        # Check contract balances
        weth_balance = weth_contract.functions.balanceOf(contract_addr).call()
        usdc_balance = usdc_contract.functions.balanceOf(contract_addr).call()

        # Fund WETH if needed
        if weth_balance < min_weth:
            # Check deployer WETH balance
            deployer_weth = weth_contract.functions.balanceOf(account.address).call()
            if deployer_weth < (min_weth - weth_balance):
                # Try to wrap ETH to WETH if possible
                needed = min_weth - weth_balance - deployer_weth
                eth_balance = w3.eth.get_balance(account.address)
                if eth_balance > needed:
                    wrap_eth_to_weth(needed)
                    deployer_weth = weth_contract.functions.balanceOf(account.address).call()
            # Transfer WETH to contract
            amount = min_weth - weth_balance
            if deployer_weth >= amount:
                tx = weth_contract.functions.transfer(contract_addr, amount).build_transaction({
                    'from': account.address,
                    'nonce': w3.eth.get_transaction_count(account.address),
                    'chainId': int(w3.net.version)
                })
                send_transaction(tx)
                logger.info(f"Funded contract with {Web3.from_wei(amount, 'ether')} WETH.")
            else:
                logger.error("Not enough WETH to fund contract.")

        # Fund USDC if needed
        if usdc_balance < min_usdc:
            deployer_usdc = usdc_contract.functions.balanceOf(account.address).call()
            amount = min_usdc - usdc_balance
            if deployer_usdc >= amount:
                tx = usdc_contract.functions.transfer(contract_addr, amount).build_transaction({
                    'from': account.address,
                    'nonce': w3.eth.get_transaction_count(account.address),
                    'chainId': int(w3.net.version)
                })
                send_transaction(tx)
                logger.info(f"Funded contract with {amount / 10**6} USDC.")
            else:
                logger.error("Not enough USDC to fund contract.")

        # Log final balances
        weth_balance = weth_contract.functions.balanceOf(contract_addr).call()
        usdc_balance = usdc_contract.functions.balanceOf(contract_addr).call()
        logger.info(f"Final contract balances: WETH={Web3.from_wei(weth_balance, 'ether')}, USDC={usdc_balance / 10**6}")
        return True

    def adjust_position(self) -> bool:
        self.fund_contract_if_needed()  # Ensure contract is funded before adjustment
        from utils.web3_utils import w3, init_web3
        if not w3 or not w3.is_connected():
            if not init_web3():
                logger.error("Web3 initialization failed in adjust_position.")
                self.metrics['action_taken'] = 'adjusted_failed'
                self.metrics['error_message'] = 'Web3 initialization failed.'
                self.save_metrics(receipt=None, success=False, error_message=self.metrics['error_message'])
                return False

        self.metrics = self._reset_metrics() # Reset metrics at the start of adjustment
        receipt = None # Initialize receipt to None
        adjustment_success = False

        try:
            predicted_price = self.get_predicted_price_from_api()
            if predicted_price is None:
                logger.error("Failed to get predicted price from API. Skipping adjustment.")
                self.metrics['action_taken'] = 'skipped'
                self.save_metrics(receipt=None, success=False, error_message=self.metrics['error_message'] or "API prediction failed")
                return False

            predicted_tick = self.calculate_tick_from_price(predicted_price)
            if predicted_tick is None:
                logger.error("Failed to calculate target tick from prediction. Skipping adjustment.")
                self.metrics['action_taken'] = 'skipped'
                self.save_metrics(receipt=None, success=False, error_message=self.metrics['error_message'] or "Tick calculation failed")
                return False

            self.update_pool_and_position_metrics()

            logger.info(f"Calling updatePredictionAndAdjust with predictedTick: {predicted_tick}")
            private_key = os.getenv('PRIVATE_KEY')
            if not private_key:
                raise ValueError("PRIVATE_KEY environment variable not set.")
            account = Account.from_key(private_key)
            nonce = w3.eth.get_transaction_count(account.address)

            tx_function = self.contract.functions.updatePredictionAndAdjust(predicted_tick)
            tx_params = {
                'from': account.address,
                'nonce': nonce,
                'chainId': int(w3.net.version)
            }
            try:
                estimated_gas = tx_function.estimate_gas({'from': account.address})
                tx_params['gas'] = int(estimated_gas * 1.2)
                logger.info(f"Estimated gas for adjustment: {estimated_gas}, using: {tx_params['gas']}")
            except Exception as est_err:
                logger.warning(f"Gas estimation failed for adjustment: {est_err}. Using default 1,500,000")
                tx_params['gas'] = 1500000

            built_tx = tx_function.build_transaction(tx_params)
            receipt = send_transaction(built_tx)

            if receipt and receipt.status == 1:
                logger.info("Position adjustment transaction successful.")
                self.metrics['action_taken'] = 'adjusted_success'
                adjustment_success = True
            else:
                logger.error("Position adjustment transaction failed or reverted.")
                self.metrics['action_taken'] = 'adjusted_failed'
                if not self.metrics['error_message']:
                    self.metrics['error_message'] = "TransactionRevertedOnChain"
                adjustment_success = False

        except Exception as e:
            logger.exception(f"An error occurred during the adjustment process: {e}")
            self.metrics['action_taken'] = 'adjusted_failed'
            self.metrics['error_message'] = f"AdjustmentProcessError: {str(e)}"
            adjustment_success = False

        finally:
            self.update_pool_and_position_metrics()
            self.save_metrics(receipt=receipt, success=adjustment_success, error_message=self.metrics['error_message'])

        return adjustment_success

    def save_metrics(self, receipt: dict = None, success: bool = False, error_message: str = None):
        """Save collected metrics to the CSV file."""
        try:
            self.metrics['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if error_message and not self.metrics['error_message']:
                self.metrics['error_message'] = error_message

            if receipt:
                tx_hash = receipt.get('transactionHash')
                self.metrics['tx_hash'] = tx_hash.hex() if tx_hash else None
                self.metrics['gas_used'] = receipt.get('gasUsed', 0)
                effective_gas_price = receipt.get('effectiveGasPrice')
                if effective_gas_price:
                    gas_cost_wei = self.metrics['gas_used'] * effective_gas_price
                    self.metrics['gas_cost_eth'] = float(Web3.from_wei(gas_cost_wei, 'ether'))
                else:
                    gas_price = receipt.get('gasPrice')
                    if gas_price:
                        gas_cost_wei = self.metrics['gas_used'] * gas_price
                        self.metrics['gas_cost_eth'] = float(Web3.from_wei(gas_cost_wei, 'ether'))

            RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            file_exists = RESULTS_FILE.is_file()

            columns = [
                'timestamp', 'contract_type', 'action_taken', 'tx_hash',
                'predictedPrice_api', 'predictedTick_calculated',
                'actualPrice_pool', 'sqrtPriceX96_pool', 'currentTick_pool',
                'finalTickLower_contract', 'finalTickUpper_contract', 'liquidity_contract',
                'gas_used', 'gas_cost_eth', 'error_message'
            ]

            row_data = {col: self.metrics.get(col, "") for col in columns}

            with open(RESULTS_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row_data)

            logger.info(f"Metrics saved to {RESULTS_FILE}")

        except Exception as e:
            logger.exception(f"Failed to save metrics: {e}")

def main():
    """Main test execution function."""
    logger.info("="*50)
    logger.info("Starting Predictive Liquidity Manager Test on Fork")
    logger.info("="*50)

    if not init_web3():
        logger.error("Web3 initialization failed. Exiting test.")
        return

    try:
        predictive_address = get_predictive_address()
        if predictive_address is None:
            if ADDRESS_FILE.exists():
                ADDRESS_FILE.unlink()
            logger.error(f"Address 'predictiveManager' not found in address file. New file will be created on next deploy.")
            raise FileNotFoundError(f"Address 'predictiveManager' not found in address file.")
        logger.info(f"Loaded Predictive Manager Address: {predictive_address}")

        test = PredictiveTest(predictive_address)
        success = test.execute_test_steps()

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