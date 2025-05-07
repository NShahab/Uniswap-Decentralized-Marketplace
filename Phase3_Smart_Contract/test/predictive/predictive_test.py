# test/predictive/predictive_test.py
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

# Precision for Decimal calculations
getcontext().prec = 78

# --- Adjust path imports ---
current_dir = Path(__file__).parent
project_root_guess = current_dir.parent.parent # Assumes predictive is in test, test is in root
utils_dir = project_root_guess / 'test' / 'utils' # Adjust if structure differs
sys.path.insert(0, str(project_root_guess))

try:
    from test.utils.test_base import LiquidityTestBase
    from test.utils.web3_utils import (
        send_transaction, init_web3, get_contract, load_contract_abi,
        wrap_eth_to_weth, w3
    )
except ImportError as e:
     print(f"ERROR importing utils: {e}. Check sys.path and folder structure.", file=sys.stderr)
     sys.exit(1)


# --- Constants ---
MIN_WETH_TO_FUND_CONTRACT = Web3.to_wei(0.02, 'ether') # Min WETH contract should have
MIN_USDC_TO_FUND_CONTRACT = 20 * (10**6) # Min USDC contract should have (20 USDC)
TWO_POW_96 = Decimal(2**96)
MIN_TICK_CONST = -887272
MAX_TICK_CONST = 887272

# --- Setup Logging ---
# (Keep your existing logging setup)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("predictive_test.log"), # Log to a file
        logging.StreamHandler() # Also log to console
    ]
)
logger = logging.getLogger('predictive_test')


# --- Define path for addresses and results ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent # Adjust if needed
ADDRESS_FILE_PREDICTIVE = PROJECT_ROOT / 'predictiveManager_address.json' # Dedicated file
RESULTS_FILE = PROJECT_ROOT / 'position_results_predictive.csv' # Dedicated results file
LSTM_API_URL = os.getenv('LSTM_API_URL', 'http://127.0.0.1:5000/predict') # Example URL

logger.info(f"Project Root: {PROJECT_ROOT}")
logger.info(f"Predictive Address File: {ADDRESS_FILE_PREDICTIVE}")
logger.info(f"Predictive Results File: {RESULTS_FILE}")


class PredictiveTest(LiquidityTestBase):
    """Test implementation for PredictiveLiquidityManager contract testing on a fork."""

    def __init__(self, contract_address: str):
        super().__init__(contract_address, "PredictiveLiquidityManager")
        # Reset metrics using a method to ensure clean state
        self.metrics = self._reset_metrics()
        self.pool_address = None
        self.pool_contract = None
        # Add action states for clarity
        self.ACTION_STATES = {
            "INIT": "init", "SETUP_FAILED": "setup_failed",
            "POOL_READ_FAILED": "pool_read_failed", "API_FAILED": "api_failed",
            "CALCULATION_FAILED": "calculation_failed", "FUNDING_FAILED": "funding_failed",
            "TX_SENT": "tx_sent", "TX_SUCCESS_ADJUSTED": "tx_success_adjusted",
            "TX_REVERTED": "tx_reverted", "TX_WAIT_FAILED": "tx_wait_failed",
             "METRICS_UPDATE_FAILED": "metrics_update_failed",
            "UNEXPECTED_ERROR": "unexpected_error"
        }


    def _reset_metrics(self):
        """Resets the metrics dictionary for a new run."""
        # (Keep your detailed metrics structure)
        return {
            'timestamp': None, 'contract_type': 'Predictive',
            'action_taken': self.ACTION_STATES["INIT"], 'tx_hash': None,
            'predictedPrice_api': None, 'predictedTick_calculated': None,
            'actualPrice_pool': None, 'sqrtPriceX96_pool': 0, 'currentTick_pool': 0,
            'targetTickLower_calculated': 0, 'targetTickUpper_calculated': 0, # Calculated before sending TX
            'finalTickLower_contract': 0, 'finalTickUpper_contract': 0, 'liquidity_contract': 0, # Read after TX
            'gas_used': 0, 'gas_cost_eth': 0.0, 'error_message': ""
        }

    def setup(self) -> bool:
        """Override setup to also get pool contract."""
        # (Keep the setup logic from baseline_test.py, as it's good practice)
        if not super().setup():
            self.metrics['action_taken'] = self.ACTION_STATES["SETUP_FAILED"]
            self.metrics['error_message'] = "Base setup failed"
            # Avoid saving metrics here, let execute_test_steps handle final save
            return False
        try:
            factory_address = self.contract.functions.factory().call()
            factory_contract = get_contract(factory_address, "IUniswapV3Factory")
            fee = self.contract.functions.fee().call()
            self.pool_address = factory_contract.functions.getPool(self.token0, self.token1, fee).call()
            if self.pool_address == '0x' + '0'*40:
                 raise ValueError(f"Predictive pool address not found for {self.token0}/{self.token1} fee {fee}")
            self.pool_contract = get_contract(self.pool_address, "IUniswapV3Pool")
            logger.info(f"Predictive Pool contract initialized at {self.pool_address}")
            return True
        except Exception as e:
            logger.exception(f"Predictive setup failed getting pool: {e}")
            self.metrics['action_taken'] = self.ACTION_STATES["SETUP_FAILED"]
            self.metrics['error_message'] = f"Setup pool error: {str(e)}"
            # self.save_metrics() # Avoid saving here
            return False

    def get_predicted_price_from_api(self) -> float | None:
        """Get predicted ETH price from the LSTM API."""
        # (Keep your existing API call logic)
        try:
            logger.info(f"Querying LSTM API at {LSTM_API_URL}...")
            response = requests.get(LSTM_API_URL, timeout=15)
            response.raise_for_status()
            data = response.json()
            predicted_price = float(data['predicted_price']) # Adjust key if needed
            logger.info(f"Received predicted ETH price from API: {predicted_price:.2f} USD")
            self.metrics['predictedPrice_api'] = predicted_price
            return predicted_price
        except Exception as e:
            logger.exception(f"Error getting prediction from API: {e}")
            self.metrics['action_taken'] = self.ACTION_STATES["API_FAILED"]
            self.metrics['error_message'] = f"API Error: {str(e)}"
            return None


    def calculate_tick_from_price(self, price: float) -> int | None:
        """Convert price (e.g., ETH/USD) to Uniswap v3 tick."""
        # (Keep your existing tick calculation logic)
        if not self.token0_decimals or not self.token1_decimals: return None
        try:
            price_decimal = Decimal(str(price))
            # Assuming price = T1/T0 (e.g. WETH/USDC)
            adjusted_ratio = price_decimal * (Decimal(10) ** (self.token0_decimals - self.token1_decimals))
            sqrt_ratio = adjusted_ratio.sqrt()
            sqrt_price_x96 = sqrt_ratio * TWO_POW_96
            log_arg = float(sqrt_price_x96 / TWO_POW_96)
            if log_arg <= 0: return None
            tick = math.floor(math.log(log_arg, 1.0001))
            tick = max(MIN_TICK_CONST, min(MAX_TICK_CONST, tick))
            logger.info(f"Calculated tick {tick} from price {price:.2f}")
            self.metrics['predictedTick_calculated'] = tick
            return tick
        except Exception as e:
            logger.exception(f"Failed to calculate predicted tick: {e}")
            self.metrics['action_taken'] = self.ACTION_STATES["CALCULATION_FAILED"]
            self.metrics['error_message'] = f"Tick Calculation Error: {str(e)}"
            return None

    def update_pool_and_position_metrics(self, final_update=False):
        """Fetches current pool price/tick and contract position state."""
        # (Keep your existing logic, use final_update flag if needed)
        try:
            if self.pool_contract:
                slot0 = self.pool_contract.functions.slot0().call()
                sqrt_price_x96_pool, current_tick_pool = slot0[0], slot0[1]
                self.metrics['sqrtPriceX96_pool'] = sqrt_price_x96_pool
                self.metrics['currentTick_pool'] = current_tick_pool
                self.metrics['actualPrice_pool'] = self._calculate_actual_price(sqrt_price_x96_pool)
                # logger.debug(f"Pool State: Tick={current_tick_pool}, ActualPrice={self.metrics['actualPrice_pool']:.2f}")
            else: logger.warning("Pool contract not available for metrics update.")

            position_info = self.get_position_info() # Uses method from base class
            if position_info:
                 # Only update final values if final_update is True
                 if final_update:
                     self.metrics['finalTickLower_contract'] = position_info.get('tickLower', 0)
                     self.metrics['finalTickUpper_contract'] = position_info.get('tickUpper', 0)
                     self.metrics['liquidity_contract'] = position_info.get('liquidity', 0)
                 # logger.debug(f"Contract Position: Active={position_info.get('active')}, Liq={position_info.get('liquidity')}")
            else: logger.warning("Could not get position info from contract for metrics.")

        except Exception as e:
            logger.exception(f"Error updating pool/position metrics: {e}")
            self.metrics['action_taken'] = self.ACTION_STATES["METRICS_UPDATE_FAILED"]
            if not self.metrics['error_message']: self.metrics['error_message'] = f"Metrics Update Error: {str(e)}"


    def fund_contract_if_needed(self, min_weth=MIN_WETH_TO_FUND_CONTRACT, min_usdc=MIN_USDC_TO_FUND_CONTRACT) -> bool:
        """Checks contract WETH/USDC balance and funds from deployer if needed."""
        # Use the *exact same* funding logic as implemented in the corrected baseline_test.py
        # This ensures consistency.
        # --- Start copied/adapted funding logic ---
        if not w3 or not w3.is_connected():
            if not init_web3(): return False # Ensure connected

        private_key = os.getenv('PRIVATE_KEY')
        if not private_key:
             logger.error("PRIVATE_KEY environment variable not set for funding.")
             return False
        account = Account.from_key(private_key)
        contract_addr = self.contract_address

        try:
            # Identify WETH/USDC based on decimals
            token0_is_usdc = self.token0_decimals == 6
            weth_token_addr = self.token1 if token0_is_usdc else self.token0
            usdc_token_addr = self.token0 if token0_is_usdc else self.token1

            weth_contract = get_contract(weth_token_addr, "IERC20")
            usdc_contract = get_contract(usdc_token_addr, "IERC20")

            contract_weth_bal = weth_contract.functions.balanceOf(contract_addr).call()
            contract_usdc_bal = usdc_contract.functions.balanceOf(contract_addr).call()
            logger.info(f"Contract balances before funding check: WETH={Web3.from_wei(contract_weth_bal, 'ether')}, USDC={contract_usdc_bal / 10**6}")


            fund_weth = contract_weth_bal < min_weth
            fund_usdc = contract_usdc_bal < min_usdc

            if not fund_weth and not fund_usdc:
                logger.info("Contract already has sufficient WETH and USDC.")
                return True

            logger.info("Attempting to fund contract...")
            nonce = w3.eth.get_transaction_count(account.address)
            funded_something = False

            # Fund WETH
            if fund_weth:
                needed_weth = min_weth - contract_weth_bal
                logger.info(f"Contract needs {Web3.from_wei(needed_weth, 'ether')} WETH.")
                deployer_weth_bal = weth_contract.functions.balanceOf(account.address).call()

                if deployer_weth_bal < needed_weth:
                    logger.warning(f"Deployer has insufficient WETH ({Web3.from_wei(deployer_weth_bal, 'ether')}). Attempting to wrap ETH...")
                    eth_needed_for_wrap = needed_weth - deployer_weth_bal + Web3.to_wei(0.001, 'ether') # Add small buffer
                    # Call the corrected wrap_eth_to_weth from web3_utils
                    if wrap_eth_to_weth(eth_needed_for_wrap):
                         time.sleep(2) # Give wrap time to reflect
                         deployer_weth_bal = weth_contract.functions.balanceOf(account.address).call() # Refresh balance
                    else:
                         logger.error("Failed to wrap ETH for WETH funding.")
                         return False # Stop funding if wrap fails

                if deployer_weth_bal >= needed_weth:
                    logger.info(f"Transferring {Web3.from_wei(needed_weth, 'ether')} WETH from deployer to contract...")
                    tx_params = weth_contract.functions.transfer(contract_addr, needed_weth).build_transaction({
                        'from': account.address, 'nonce': nonce, 'chainId': int(w3.net.version)
                    })
                    receipt = send_transaction(tx_params) # Use helper
                    if receipt and receipt.status == 1:
                        logger.info("WETH transfer successful.")
                        nonce += 1
                        funded_something = True
                        time.sleep(2) # Allow state change
                    else:
                        logger.error("WETH transfer to contract failed.")
                        return False # Stop if transfer fails
                else:
                     logger.error(f"Deployer still has insufficient WETH after wrap attempt ({Web3.from_wei(deployer_weth_bal, 'ether')}).")
                     return False


            # Fund USDC
            if fund_usdc:
                needed_usdc = min_usdc - contract_usdc_bal
                logger.info(f"Contract needs {needed_usdc / (10**6)} USDC.")
                deployer_usdc_bal = usdc_contract.functions.balanceOf(account.address).call()

                if deployer_usdc_bal >= needed_usdc:
                    logger.info(f"Transferring {needed_usdc / (10**6)} USDC from deployer to contract...")
                    tx_params = usdc_contract.functions.transfer(contract_addr, needed_usdc).build_transaction({
                        'from': account.address, 'nonce': nonce, 'chainId': int(w3.net.version)
                    })
                    receipt = send_transaction(tx_params) # Use helper
                    if receipt and receipt.status == 1:
                         logger.info("USDC transfer successful.")
                         # nonce += 1 # Nonce already incremented if WETH was sent
                         funded_something = True
                         time.sleep(2) # Allow state change
                    else:
                         logger.error("USDC transfer to contract failed.")
                         return False # Stop if transfer fails
                else:
                    logger.error(f"Deployer has insufficient USDC ({deployer_usdc_bal / (10**6)}).")
                    return False

            contract_weth_bal_final = weth_contract.functions.balanceOf(contract_addr).call()
            contract_usdc_bal_final = usdc_contract.functions.balanceOf(contract_addr).call()
            logger.info(f"Balances after funding attempt: WETH={Web3.from_wei(contract_weth_bal_final, 'ether')}, USDC={contract_usdc_bal_final / 10**6}")
            # Check again if funding actually met the minimums
            if contract_weth_bal_final < min_weth or contract_usdc_bal_final < min_usdc:
                 logger.error("Contract balances still below minimum after funding attempt.")
                 return False

            return True # Return True if successful

        except Exception as e:
            logger.exception(f"Error during fund_contract_if_needed: {e}")
            return False
        # --- End copied/adapted funding logic ---


    def adjust_position(self) -> bool:
        """Adjusts the liquidity position based on the prediction."""
        self.metrics = self._reset_metrics() # Reset metrics
        receipt = None
        adjustment_call_success = False

        try:
            # --- 1. Get Prediction ---
            predicted_price = self.get_predicted_price_from_api()
            if predicted_price is None:
                # Error already logged and action_taken set in helper
                self.save_metrics() # Save the error state
                return False

            # --- 2. Calculate Target Tick ---
            predicted_tick = self.calculate_tick_from_price(predicted_price)
            if predicted_tick is None:
                # Error already logged and action_taken set in helper
                self.save_metrics()
                return False

            # --- 3. Update current pool/position metrics (before potential adjustment) ---
            self.update_pool_and_position_metrics(final_update=False)

            # --- 4. Fund Contract If Needed ---
            # Ensure contract has tokens *before* calling the adjustment function
            if not self.fund_contract_if_needed():
                 logger.error("Funding contract failed. Cannot proceed with adjustment.")
                 self.metrics['action_taken'] = self.ACTION_STATES["FUNDING_FAILED"]
                 self.metrics['error_message'] = "Contract funding failed before adjustment call"
                 self.save_metrics() # Save funding failure state
                 return False

            # --- 5. Call Contract to Adjust ---
            logger.info(f"Calling updatePredictionAndAdjust with predictedTick: {predicted_tick}")
            private_key = os.getenv('PRIVATE_KEY')
            account = Account.from_key(private_key)
            nonce = w3.eth.get_transaction_count(account.address)

            try:
                tx_function = self.contract.functions.updatePredictionAndAdjust(predicted_tick)
                tx_params = {'from': account.address, 'nonce': nonce, 'chainId': int(w3.net.version)}
                # Estimate Gas
                try:
                    estimated_gas = tx_function.estimate_gas({'from': account.address})
                    tx_params['gas'] = int(estimated_gas * 1.25) # 25% buffer
                    logger.info(f"Estimated gas for adjustment: {estimated_gas}, using: {tx_params['gas']}")
                except Exception as est_err:
                    logger.warning(f"Gas estimation failed: {est_err}. Using default 1,500,000")
                    tx_params['gas'] = 1500000

                # Send Transaction using helper
                receipt = send_transaction(tx_function.build_transaction(tx_params))
                self.metrics['tx_hash'] = receipt.transactionHash.hex() if receipt else None
                self.metrics['action_taken'] = self.ACTION_STATES["TX_SENT"]

                if receipt and receipt.status == 1:
                    logger.info("Adjustment transaction successful (Status 1).")
                    self.metrics['gas_used'] = receipt.get('gasUsed', 0)
                    if receipt.get('effectiveGasPrice'):
                         self.metrics['gas_cost_eth'] = float(Web3.from_wei(receipt.gasUsed * receipt.effectiveGasPrice, 'ether'))
                    # We assume success means adjustment happened, event parsing could confirm
                    self.metrics['action_taken'] = self.ACTION_STATES["TX_SUCCESS_ADJUSTED"]
                    adjustment_call_success = True
                elif receipt: # Status 0
                    logger.error(f"Adjustment transaction reverted (Status 0). Tx: {self.metrics['tx_hash']}")
                    self.metrics['action_taken'] = self.ACTION_STATES["TX_REVERTED"]
                    self.metrics['error_message'] = "tx_reverted_onchain"
                    self.metrics['gas_used'] = receipt.get('gasUsed', 0)
                    if receipt.get('effectiveGasPrice'):
                         self.metrics['gas_cost_eth'] = float(Web3.from_wei(receipt.gasUsed * receipt.effectiveGasPrice, 'ether'))
                    adjustment_call_success = False
                else: # send_transaction returned None
                    logger.error("Adjustment transaction sending failed.")
                    if self.metrics['action_taken'] == self.ACTION_STATES["TX_SENT"]:
                         self.metrics['action_taken'] = self.ACTION_STATES["TX_WAIT_FAILED"] # Or TX_SEND_FAILED
                         self.metrics['error_message'] = "send_transaction failed"
                    adjustment_call_success = False

            except Exception as tx_err:
                 logger.exception(f"Error during adjustment transaction call/wait: {tx_err}")
                 self.metrics['action_taken'] = self.ACTION_STATES["UNEXPECTED_ERROR"]
                 self.metrics['error_message'] = f"TxError: {str(tx_err)}"
                 self.save_metrics() # Save error state
                 return False

            # --- 6. Update Final Metrics & Save ---
            self.update_pool_and_position_metrics(final_update=True) # Read final state
            self.save_metrics() # Save all collected metrics

            return adjustment_call_success # Return based on tx success

        except Exception as e:
            logger.exception("Unexpected error in adjust_position:")
            self.metrics['action_taken'] = self.ACTION_STATES["UNEXPECTED_ERROR"]
            self.metrics['error_message'] = str(e)
            self.save_metrics()
            return False


    def save_metrics(self):
        """Saves the current state of self.metrics to the CSV file."""
        # (Keep your existing save_metrics logic, ensure columns match _reset_metrics)
        self.metrics['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        columns = [
            'timestamp', 'contract_type', 'action_taken', 'tx_hash',
            'predictedPrice_api', 'predictedTick_calculated',
            'actualPrice_pool', 'sqrtPriceX96_pool', 'currentTick_pool',
            'targetTickLower_calculated', 'targetTickUpper_calculated', # Calculated target before TX
            'finalTickLower_contract', 'finalTickUpper_contract', 'liquidity_contract', # Actual final state
            'gas_used', 'gas_cost_eth', 'error_message'
        ]
        try:
            RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            file_exists = RESULTS_FILE.is_file()
            for col in columns: self.metrics.setdefault(col, None)
            row_data = {k: "" if self.metrics.get(k) is None else self.metrics.get(k) for k in columns}
            with open(RESULTS_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
                if not file_exists: writer.writeheader()
                writer.writerow(row_data)
            logger.info(f"Predictive metrics saved to {RESULTS_FILE}")
        except Exception as e:
            logger.exception(f"Failed to save predictive metrics: {e}")

    # execute_test_steps is inherited from LiquidityTestBase


# --- Main Function ---
def main():
    """Main test execution function."""
    logger.info("="*50)
    logger.info("Starting Predictive Liquidity Manager Test on Fork")
    logger.info("="*50)

    if not init_web3():
        logger.critical("Web3 initialization failed. Exiting predictive test.")
        return

    predictive_address = None
    try:
        # --- Read Contract Address from JSON ---
        if not ADDRESS_FILE_PREDICTIVE.exists():
             logger.error(f"Predictive address file not found: {ADDRESS_FILE_PREDICTIVE}")
             raise FileNotFoundError(f"{ADDRESS_FILE_PREDICTIVE}")

        logger.info(f"Reading predictive address from: {ADDRESS_FILE_PREDICTIVE}")
        with open(ADDRESS_FILE_PREDICTIVE, 'r') as f:
             content = f.read()
             logger.debug(f"Predictive address file content: {content}")
             addresses = json.loads(content)
             predictive_address = addresses.get('address') # Read the 'address' key
             if not predictive_address:
                  logger.error(f"Key 'address' not found in {ADDRESS_FILE_PREDICTIVE}")
                  raise ValueError(f"Key 'address' not found in {ADDRESS_FILE_PREDICTIVE}")
        logger.info(f"Loaded Predictive Manager Address: {predictive_address}")

        # --- Initialize and Run Test ---
        test = PredictiveTest(predictive_address)
        test.execute_test_steps() # Handles setup, adjust, save

    except FileNotFoundError as e:
        logger.error(f"Setup Error - Address file not found: {e}")
    except ValueError as e:
        logger.error(f"Configuration Error - Problem reading address file: {e}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred during predictive main execution:")
    finally:
        logger.info("="*50)
        logger.info("Predictive test run finished.")
        logger.info("="*50)


if __name__ == "__main__":
    main()