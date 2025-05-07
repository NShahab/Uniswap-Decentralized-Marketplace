# test/baseline_test.py
import os
import sys
import json
import time
import logging
import csv
import math
from datetime import datetime
from pathlib import Path
from web3 import Web3
from eth_account import Account
from decimal import Decimal, getcontext

# Precision for Decimal calculations
getcontext().prec = 78

# --- Adjust path imports ---
current_dir = Path(__file__).parent
project_root_guess = current_dir.parent.parent # Assumes baseline is in test, test is in root
utils_dir = project_root_guess / 'test' / 'utils' # Adjust if structure differs
sys.path.insert(0, str(project_root_guess))

try:
    from test.utils.test_base import LiquidityTestBase
    from test.utils.web3_utils import (
        send_transaction, init_web3, get_contract, load_contract_abi,
        wrap_eth_to_weth, w3 # Import necessary utils
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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("baseline_test.log"), # Log to a file
        logging.StreamHandler() # Also log to console
    ]
)
logger = logging.getLogger('baseline_test')

# --- Define path for addresses and results ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent # Adjust if needed
ADDRESS_FILE_BASELINE = PROJECT_ROOT / 'baselineMinimal_address.json' # Dedicated file
RESULTS_FILE = PROJECT_ROOT / 'position_results_baseline.csv' # Dedicated results file

logger.info(f"Project Root: {PROJECT_ROOT}")
logger.info(f"Baseline Address File: {ADDRESS_FILE_BASELINE}")
logger.info(f"Baseline Results File: {RESULTS_FILE}")


class BaselineTest(LiquidityTestBase):
    """Test implementation for BaselineMinimal with token funding."""

    def __init__(self, contract_address: str):
        super().__init__(contract_address, "BaselineMinimal")
        self.factory_contract = None
        self.tick_spacing = None
        self.pool_address = None
        self.pool_contract = None
        # Define action states for logging/tracking
        self.ACTION_STATES = {
            "INIT": "init", "SETUP_FAILED": "setup_failed",
            "POOL_READ_FAILED": "pool_read_failed", "CALCULATION_FAILED": "calculation_failed",
            "SKIPPED_PROXIMITY": "skipped_proximity", "FUNDING_FAILED": "funding_failed",
            "TX_SENT": "tx_sent", "TX_SUCCESS_ADJUSTED": "tx_success_adjusted",
            "TX_SUCCESS_SKIPPED_ONCHAIN": "tx_success_skipped_onchain",
            "TX_REVERTED": "tx_reverted", "TX_WAIT_FAILED": "tx_wait_failed",
            "METRICS_UPDATE_FAILED": "metrics_update_failed",
            "UNEXPECTED_ERROR": "unexpected_error"
        }
        self.metrics = self._reset_metrics()

    def _reset_metrics(self):
        """Resets metrics for a new run."""
        # (Keep your detailed metrics structure)
        return {
            'timestamp': None, 'contract_type': 'Baseline',
            'action_taken': self.ACTION_STATES["INIT"], 'tx_hash': None,
            'actualPrice_pool': None, 'sqrtPriceX96_pool': None, 'currentTick_pool': None,
            'targetTickLower_offchain': None, 'targetTickUpper_offchain': None,
            'currentTickLower': None, 'currentTickUpper': None, 'currentLiquidity': None,
            'finalTickLower': None, 'finalTickUpper': None, 'finalLiquidity': None,
            'gas_used': None, 'gas_cost_eth': None, 'error_message': ""
        }

    def setup(self) -> bool:
        """Initialize base, factory, pool and get tickSpacing."""
        # (Same setup logic as predictive, just logging context differs slightly)
        if not super().setup():
            self.metrics['action_taken'] = self.ACTION_STATES["SETUP_FAILED"]
            self.metrics['error_message'] = "Base setup failed"
            # self.save_metrics() # Avoid saving here
            return False
        try:
            factory_address = self.contract.functions.factory().call()
            self.factory_contract = get_contract(factory_address, "IUniswapV3Factory")
            fee = self.contract.functions.fee().call()
            self.pool_address = self.factory_contract.functions.getPool(self.token0, self.token1, fee).call()
            if self.pool_address == '0x' + '0'*40:
                 raise ValueError(f"Baseline pool address not found for {self.token0}/{self.token1} fee {fee}")
            self.pool_contract = get_contract(self.pool_address, "IUniswapV3Pool")
            logger.info(f"Baseline Pool contract initialized at {self.pool_address}")
            self.tick_spacing = self.pool_contract.functions.tickSpacing().call()
            if not self.tick_spacing or self.tick_spacing <= 0:
                 raise ValueError(f"Invalid tickSpacing read from pool: {self.tick_spacing}")
            logger.info(f"Baseline Tick spacing from pool: {self.tick_spacing}")
            return True
        except Exception as e:
            logger.exception(f"Baseline setup failed getting pool/tickSpacing: {e}")
            self.metrics['action_taken'] = self.ACTION_STATES["SETUP_FAILED"]
            self.metrics['error_message'] = f"Setup pool/tick error: {str(e)}"
            # self.save_metrics() # Avoid saving here
            return False

    def get_pool_state(self) -> tuple[int | None, int | None]:
        """Reads current sqrtPriceX96 and tick from the pool."""
        # (Same logic as predictive)
        if not self.pool_contract: return None, None
        try:
            slot0 = self.pool_contract.functions.slot0().call()
            sqrt_price_x96, tick = slot0[0], slot0[1]
            self.metrics['sqrtPriceX96_pool'] = sqrt_price_x96
            self.metrics['currentTick_pool'] = tick
            self.metrics['actualPrice_pool'] = self._calculate_actual_price(sqrt_price_x96)
            # logger.debug(f"Pool State: Tick={tick}, ActualPrice={self.metrics['actualPrice_pool']:.2f}")
            return sqrt_price_x96, tick
        except Exception as e:
            logger.exception(f"Failed to get pool state: {e}")
            return None, None

    def _calculate_actual_price(self, sqrt_price_x96):
        """Calculates readable price from sqrtPriceX96 off-chain."""
        # (Same logic as predictive)
        if not sqrt_price_x96 or sqrt_price_x96 == 0: return 0.0
        try:
            sqrt_price_x96_dec = Decimal(sqrt_price_x96)
            price_ratio = (sqrt_price_x96_dec / TWO_POW_96)**2
            price_t1_t0_adj = price_ratio * (Decimal(10)**(self.token1_decimals - self.token0_decimals))
            return float(price_t1_t0_adj)
        except Exception: return 0.0


    def calculate_target_ticks_offchain(self, current_tick: int) -> tuple[int | None, int | None]:
        """Calculates target ticks off-chain based on contract logic (width=4)."""
        # (Same logic as predictive)
        if self.tick_spacing is None or current_tick is None: return None, None
        try:
            width_multiplier = 4
            half_width = (self.tick_spacing * width_multiplier) // 2
            if half_width < self.tick_spacing: half_width = self.tick_spacing
            target_lower_tick = math.floor((current_tick - half_width) / self.tick_spacing) * self.tick_spacing
            target_upper_tick = math.floor((current_tick + half_width) / self.tick_spacing) * self.tick_spacing
            if target_lower_tick >= target_upper_tick: target_upper_tick = target_lower_tick + self.tick_spacing
            target_lower_tick = max(MIN_TICK_CONST, target_lower_tick)
            target_upper_tick = min(MAX_TICK_CONST, target_upper_tick)
            if target_lower_tick >= target_upper_tick:
                 if target_upper_tick == MAX_TICK_CONST: target_lower_tick = target_upper_tick - self.tick_spacing
                 else: target_upper_tick = target_lower_tick + self.tick_spacing
                 target_lower_tick = max(MIN_TICK_CONST, target_lower_tick)
            if target_lower_tick >= target_upper_tick or target_lower_tick < MIN_TICK_CONST or target_upper_tick > MAX_TICK_CONST:
                 raise ValueError("Invalid tick range")
            logger.info(f"Off-chain calculated target ticks: Lower={target_lower_tick}, Upper={target_upper_tick}")
            self.metrics['targetTickLower_offchain'] = target_lower_tick
            self.metrics['targetTickUpper_offchain'] = target_upper_tick
            return target_lower_tick, target_upper_tick
        except Exception as e:
            logger.exception(f"Error calculating target ticks off-chain: {e}")
            return None, None

    def fund_contract_if_needed(self, min_weth=MIN_WETH_TO_FUND_CONTRACT, min_usdc=MIN_USDC_TO_FUND_CONTRACT) -> bool:
        """Checks contract WETH/USDC balance and funds from deployer if needed."""
        # Use the *exact same* funding logic as implemented in the corrected predictive_test.py
        # --- Start copied/adapted funding logic ---
        if not w3 or not w3.is_connected():
            if not init_web3(): return False

        private_key = os.getenv('PRIVATE_KEY')
        if not private_key:
             logger.error("PRIVATE_KEY needed for funding.")
             return False
        account = Account.from_key(private_key)
        contract_addr = self.contract_address

        try:
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

            if fund_weth:
                needed_weth = min_weth - contract_weth_bal
                logger.info(f"Contract needs {Web3.from_wei(needed_weth, 'ether')} WETH.")
                deployer_weth_bal = weth_contract.functions.balanceOf(account.address).call()
                if deployer_weth_bal < needed_weth:
                    logger.warning(f"Deployer low on WETH ({Web3.from_wei(deployer_weth_bal, 'ether')}). Wrapping ETH...")
                    eth_needed = needed_weth - deployer_weth_bal + Web3.to_wei(0.001, 'ether')
                    if wrap_eth_to_weth(eth_needed):
                         time.sleep(2)
                         deployer_weth_bal = weth_contract.functions.balanceOf(account.address).call()
                    else:
                         logger.error("Failed to wrap ETH.")
                         return False
                if deployer_weth_bal >= needed_weth:
                    logger.info(f"Transferring {Web3.from_wei(needed_weth, 'ether')} WETH to contract...")
                    tx_params = weth_contract.functions.transfer(contract_addr, needed_weth).build_transaction({'from': account.address, 'nonce': nonce, 'chainId': int(w3.net.version)})
                    receipt = send_transaction(tx_params)
                    if receipt and receipt.status == 1:
                        logger.info("WETH transfer successful.")
                        nonce += 1; funded_something = True; time.sleep(2)
                    else: logger.error("WETH transfer failed."); return False
                else: logger.error("Deployer still has insufficient WETH."); return False

            if fund_usdc:
                needed_usdc = min_usdc - contract_usdc_bal
                logger.info(f"Contract needs {needed_usdc / (10**6)} USDC.")
                deployer_usdc_bal = usdc_contract.functions.balanceOf(account.address).call()
                if deployer_usdc_bal >= needed_usdc:
                    logger.info(f"Transferring {needed_usdc / (10**6)} USDC to contract...")
                    tx_params = usdc_contract.functions.transfer(contract_addr, needed_usdc).build_transaction({'from': account.address, 'nonce': nonce, 'chainId': int(w3.net.version)})
                    receipt = send_transaction(tx_params)
                    if receipt and receipt.status == 1:
                         logger.info("USDC transfer successful."); funded_something = True; time.sleep(2)
                         # Nonce already handled if WETH was sent
                    else: logger.error("USDC transfer failed."); return False
                else: logger.error(f"Deployer has insufficient USDC."); return False

            # Log final balances
            final_weth = weth_contract.functions.balanceOf(contract_addr).call()
            final_usdc = usdc_contract.functions.balanceOf(contract_addr).call()
            logger.info(f"Balances after funding: WETH={Web3.from_wei(final_weth, 'ether')}, USDC={final_usdc / 10**6}")
            if final_weth < min_weth or final_usdc < min_usdc:
                 logger.error("Contract balances still below minimum after funding.")
                 return False
            return True
        except Exception as e:
            logger.exception(f"Error during fund_contract_if_needed: {e}")
            return False
        # --- End copied/adapted funding logic ---


    def adjust_position(self) -> bool:
        """Checks proximity, funds contract, calls adjustment function, saves metrics."""
        self.metrics = self._reset_metrics() # Reset metrics
        receipt = None
        adjustment_call_success = False
        adjusted_onchain = False # Did the contract state it adjusted?

        try:
            # --- 1. Get Pool State ---
            _, current_tick = self.get_pool_state()
            if current_tick is None:
                self.metrics['action_taken'] = self.ACTION_STATES["POOL_READ_FAILED"]
                self.metrics['error_message'] = "Failed to read pool state"
                self.save_metrics(); return False

            # --- 2. Get Current Position State ---
            position_info = self.get_position_info()
            has_current_position = position_info.get('active', False) if position_info else False
            self.metrics['currentTickLower'] = position_info.get('tickLower') if has_current_position else None
            self.metrics['currentTickUpper'] = position_info.get('tickUpper') if has_current_position else None
            self.metrics['currentLiquidity'] = position_info.get('liquidity', 0) if has_current_position else 0

            # --- 3. Calculate Target Ticks Off-chain ---
            target_lower_tick, target_upper_tick = self.calculate_target_ticks_offchain(current_tick)
            if target_lower_tick is None:
                self.metrics['action_taken'] = self.ACTION_STATES["CALCULATION_FAILED"]
                self.metrics['error_message'] = "Failed to calculate target ticks"
                self.save_metrics(); return False

            # --- 4. Proximity Check ---
            if has_current_position:
                TICK_PROXIMITY_THRESHOLD = self.tick_spacing
                is_close = (abs(target_lower_tick - self.metrics['currentTickLower']) <= TICK_PROXIMITY_THRESHOLD and
                            abs(target_upper_tick - self.metrics['currentTickUpper']) <= TICK_PROXIMITY_THRESHOLD)
                if is_close:
                    logger.info("Off-chain proximity check: Target ticks close. Skipping adjustment call.")
                    self.metrics['action_taken'] = self.ACTION_STATES["SKIPPED_PROXIMITY"]
                    self.metrics['finalTickLower'] = self.metrics['currentTickLower']
                    self.metrics['finalTickUpper'] = self.metrics['currentTickUpper']
                    self.metrics['finalLiquidity'] = self.metrics['currentLiquidity']
                    self.save_metrics(); return True # Successful skip

            # --- 5. Fund Contract If Needed ---
            if not self.fund_contract_if_needed():
                 logger.error("Funding failed. Skipping adjustment.")
                 self.metrics['action_taken'] = self.ACTION_STATES["FUNDING_FAILED"]
                 self.metrics['error_message'] = "Contract funding failed"
                 self.metrics['finalTickLower'] = self.metrics['currentTickLower'] # Keep current state
                 self.metrics['finalTickUpper'] = self.metrics['currentTickUpper']
                 self.metrics['finalLiquidity'] = self.metrics['currentLiquidity']
                 self.save_metrics(); return False


            # --- 6. Call Contract ---
            logger.info(f"Calling adjustLiquidityWithCurrentPrice...")
            private_key = os.getenv('PRIVATE_KEY')
            account = Account.from_key(private_key)
            nonce = w3.eth.get_transaction_count(account.address)

            try:
                tx_function = self.contract.functions.adjustLiquidityWithCurrentPrice()
                tx_params = {'from': account.address, 'nonce': nonce, 'chainId': int(w3.net.version)}
                try: # Estimate Gas
                    estimated_gas = tx_function.estimate_gas({'from': account.address})
                    tx_params['gas'] = int(estimated_gas * 1.25)
                    logger.info(f"Est. gas: {estimated_gas}, using: {tx_params['gas']}")
                except Exception as est_err:
                    logger.warning(f"Gas estimation failed: {est_err}. Using 1.5M")
                    tx_params['gas'] = 1500000

                receipt = send_transaction(tx_function.build_transaction(tx_params))
                self.metrics['tx_hash'] = receipt.transactionHash.hex() if receipt else None
                self.metrics['action_taken'] = self.ACTION_STATES["TX_SENT"]

                if receipt and receipt.status == 1:
                    logger.info("Tx successful. Processing events...")
                    self.metrics['gas_used'] = receipt.gasUsed
                    if receipt.effectiveGasPrice: self.metrics['gas_cost_eth'] = float(Web3.from_wei(receipt.gasUsed * receipt.effectiveGasPrice, 'ether'))
                    # Process Event
                    try:
                        logs = self.contract.events.BaselineAdjustmentMetrics().process_receipt(receipt, errors=logging.WARN)
                        if logs:
                            adjusted_onchain = logs[0]['args']['adjusted']
                            logger.info(f"Event: Adjusted={adjusted_onchain}")
                            self.metrics['action_taken'] = self.ACTION_STATES["TX_SUCCESS_ADJUSTED"] if adjusted_onchain else self.ACTION_STATES["TX_SUCCESS_SKIPPED_ONCHAIN"]
                        else: logger.warning("Event not found."); self.metrics['action_taken'] = self.ACTION_STATES["TX_SUCCESS_ADJUSTED"]
                    except Exception as log_exc: logger.warning(f"Event error: {log_exc}"); self.metrics['action_taken'] = self.ACTION_STATES["TX_SUCCESS_ADJUSTED"]
                    adjustment_call_success = True
                elif receipt:
                    logger.error(f"Tx reverted (Status 0). Tx: {self.metrics['tx_hash']}")
                    self.metrics['action_taken'] = self.ACTION_STATES["TX_REVERTED"]; self.metrics['error_message'] = "tx_reverted_onchain"
                    self.metrics['gas_used'] = receipt.gasUsed; # Record gas
                    if receipt.effectiveGasPrice: self.metrics['gas_cost_eth'] = float(Web3.from_wei(receipt.gasUsed * receipt.effectiveGasPrice, 'ether'))
                    adjustment_call_success = False
                else:
                     logger.error("Tx sending failed.")
                     if self.metrics['action_taken'] == self.ACTION_STATES["TX_SENT"]: self.metrics['action_taken'] = self.ACTION_STATES["TX_WAIT_FAILED"]; self.metrics['error_message'] = "send_transaction failed"
                     adjustment_call_success = False
            except Exception as tx_err:
                 logger.exception(f"Error during tx call/wait: {tx_err}")
                 self.metrics['action_taken'] = self.ACTION_STATES["UNEXPECTED_ERROR"]; self.metrics['error_message'] = f"TxError: {str(tx_err)}"
                 self.save_metrics(); return False

            # --- 7. Read Final State & Save ---
            final_position_info = self.get_position_info()
            if final_position_info:
                self.metrics['finalLiquidity'] = final_position_info.get('liquidity', 0)
                self.metrics['finalTickLower'] = final_position_info.get('tickLower')
                self.metrics['finalTickUpper'] = final_position_info.get('tickUpper')
            else: # Best guess if read fails
                 logger.warning("Could not read final position info.")
                 if adjustment_call_success and adjusted_onchain: self.metrics['finalTickLower'], self.metrics['finalTickUpper'] = target_lower_tick, target_upper_tick
                 else: self.metrics['finalTickLower'], self.metrics['finalTickUpper'] = self.metrics['currentTickLower'], self.metrics['currentTickUpper']
                 self.metrics['finalLiquidity'] = self.metrics['currentLiquidity'] # Assume no change

            self.save_metrics()
            return adjustment_call_success

        except Exception as e:
            logger.exception("Unexpected error in adjust_position:")
            self.metrics['action_taken'] = self.ACTION_STATES["UNEXPECTED_ERROR"]; self.metrics['error_message'] = str(e)
            self.save_metrics(); return False

    def save_metrics(self):
        """Saves the current state of self.metrics to the CSV file."""
        # (Keep your existing save_metrics logic, ensure columns match _reset_metrics)
        self.metrics['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        columns = [
            'timestamp', 'contract_type', 'action_taken', 'tx_hash',
            'actualPrice_pool', 'sqrtPriceX96_pool', 'currentTick_pool',
            'targetTickLower_offchain', 'targetTickUpper_offchain',
            'currentTickLower', 'currentTickUpper', 'currentLiquidity',
            'finalTickLower', 'finalTickUpper', 'finalLiquidity',
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
            logger.info(f"Baseline metrics saved to {RESULTS_FILE}")
        except Exception as e:
            logger.exception(f"Failed to save baseline metrics: {e}")

    # execute_test_steps is inherited


# --- Main Function ---
def main():
    """Main test execution function."""
    logger.info("="*50)
    logger.info("Starting Baseline Minimal Liquidity Manager Test on Fork")
    logger.info("="*50)

    if not init_web3():
        logger.critical("Web3 failed. Exiting baseline test.")
        return

    baseline_address = None
    try:
        # --- Read Contract Address from JSON ---
        if not ADDRESS_FILE_BASELINE.exists():
             logger.error(f"Baseline address file not found: {ADDRESS_FILE_BASELINE}")
             raise FileNotFoundError(f"{ADDRESS_FILE_BASELINE}")

        logger.info(f"Reading baseline address from: {ADDRESS_FILE_BASELINE}")
        with open(ADDRESS_FILE_BASELINE, 'r') as f:
             content = f.read()
             logger.debug(f"Baseline address file content: {content}")
             addresses = json.loads(content)
             baseline_address = addresses.get('address') # Read the 'address' key
             if not baseline_address:
                  logger.error(f"Key 'address' not found in {ADDRESS_FILE_BASELINE}")
                  raise ValueError(f"Key 'address' not found")
        logger.info(f"Loaded Baseline Minimal Address: {baseline_address}")

        # --- Initialize and Run Test ---
        test = BaselineTest(baseline_address)
        test.execute_test_steps()

    except FileNotFoundError as e: logger.error(f"Setup Error: {e}")
    except ValueError as e: logger.error(f"Config Error: {e}")
    except Exception as e: logger.exception(f"Unexpected baseline main error:")
    finally:
        logger.info("="*50); logger.info("Baseline test run finished."); logger.info("="*50)


if __name__ == "__main__":
    main()