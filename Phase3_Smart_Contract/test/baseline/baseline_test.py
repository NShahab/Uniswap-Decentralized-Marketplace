# فایل: baseline_test.py

import os
import sys
import json
import time
import logging
import csv
import math # اضافه کردن math
from datetime import datetime
from pathlib import Path
from web3 import Web3
from eth_account import Account
from decimal import Decimal, getcontext # برای محاسبه قیمت واقعی (اختیاری)

# افزایش دقت Decimal اگر برای محاسبه قیمت واقعی لازم است
getcontext().prec = 78

sys.path.append(str(Path(__file__).parent.parent))
# فرض می‌کنیم اینها درست کار می‌کنند
from utils.test_base import LiquidityTestBase
from utils.web3_utils import send_transaction, init_web3, get_contract, load_contract_abi

# Constants
MIN_WETH_BALANCE = Web3.to_wei(0.02, 'ether')
MIN_USDC_BALANCE = 10 * (10**6)
TWO_POW_96 = Decimal(2**96)
MIN_TICK_CONST = -887272 # حدود TickMath.MIN_TICK
MAX_TICK_CONST = 887272  # حدود TickMath.MAX_TICK

logger = logging.getLogger('baseline_test')

class BaselineTest(LiquidityTestBase):
    """Test implementation for BaselineMinimal with off-chain proximity check."""

    def __init__(self, contract_address: str):
        super().__init__(contract_address, "BaselineMinimal")
        self.factory_contract = None
        self.tick_spacing = None # برای ذخیره tickSpacing
        # تعریف وضعیت‌های ممکن برای action_taken
        self.ACTION_STATES = {
            "INIT": "init",
            "SETUP_FAILED": "setup_failed",
            "POOL_READ_FAILED": "pool_read_failed",
            "CALCULATION_FAILED": "calculation_failed",
            "SKIPPED_PROXIMITY": "skipped_proximity",
            "FUNDING_FAILED": "funding_failed",
            "TX_SENT": "tx_sent",
            "TX_SUCCESS_ADJUSTED": "tx_success_adjusted", # قرارداد تنظیم کرد
            "TX_SUCCESS_SKIPPED_ONCHAIN": "tx_success_skipped_onchain", # قرارداد تنظیم نکرد
            "TX_REVERTED": "tx_reverted",
            "TX_WAIT_FAILED": "tx_wait_failed",
            "UNEXPECTED_ERROR": "unexpected_error"
        }
        # متریک‌ها با فیلدهای مرتبط‌تر به‌روز شدند
        self.metrics = {
            'timestamp': None,
            'contract_type': 'Baseline',
            'action_taken': self.ACTION_STATES["INIT"],
            'tx_hash': None,
            'actualPrice': None, # قیمت محاسبه شده آفچین
            'sqrtPriceX96': None, # خوانده شده از استخر
            'currentTick': None,  # خوانده شده از استخر
            'targetTickLower_offchain': None, # محاسبه شده آفچین
            'targetTickUpper_offchain': None, # محاسبه شده آفچین
            'currentTickLower': None, # تیک پایین پوزیشن قبل از تنظیم
            'currentTickUpper': None, # تیک بالای پوزیشن قبل از تنظیم
            'finalTickLower': None, # تیک پایین پوزیشن بعد از تنظیم (اگر تغییر کرد)
            'finalTickUpper': None, # تیک بالای پوزیشن بعد از تنظیم (اگر تغییر کرد)
            'liquidity': None,      # نقدینگی نهایی
            'gas_used': None,
            'gas_cost_eth': None,
            'error_message': ""
        }

    def setup(self) -> bool:
        """Initialize base, factory, and get tickSpacing."""
        if not super().setup():
             self.metrics['action_taken'] = self.ACTION_STATES["SETUP_FAILED"]
             self.metrics['error_message'] = "Base setup failed"
             self.save_metrics()
             return False
        try:
            factory_address = self.contract.functions.factory().call()
            self.factory_contract = get_contract(factory_address, "IUniswapV3Factory")
            logger.info(f"Factory contract initialized at {factory_address}")

            self.tick_spacing = self.contract.functions.tickSpacing().call()
            if not self.tick_spacing or self.tick_spacing <= 0:
                 raise ValueError(f"Invalid tickSpacing read from contract: {self.tick_spacing}")
            logger.info(f"Tick spacing: {self.tick_spacing}")
            return True
        except Exception as e:
            logger.error(f"Setup failed: {e}")
            self.metrics['action_taken'] = self.ACTION_STATES["SETUP_FAILED"]
            self.metrics['error_message'] = str(e)
            self.save_metrics()
            return False

    def get_pool_state(self) -> tuple[int | None, int | None]:
        """Reads current sqrtPriceX96 and tick from the pool."""
        try:
            pool_address = self.factory_contract.functions.getPool(
                self.token0, self.token1, self.contract.functions.fee().call()
            ).call()
            if pool_address == '0x' + '0'*40:
                logger.error("Pool address not found.")
                return None, None

            pool_contract = get_contract(pool_address, "IUniswapV3Pool")
            # خواندن اطلاعات از slot0
            slot0 = pool_contract.functions.slot0().call()
            sqrt_price_x96, tick = slot0[0], slot0[1]
            # به‌روزرسانی متریک‌ها
            self.metrics['sqrtPriceX96'] = sqrt_price_x96
            self.metrics['currentTick'] = tick
            self.metrics['actualPrice'] = self._calculate_actual_price(sqrt_price_x96)
            logger.info(f"Pool state read: Tick={tick}, SqrtPriceX96={sqrt_price_x96}")
            return sqrt_price_x96, tick
        except Exception as e:
            logger.error(f"Failed to get pool state: {e}")
            return None, None

    def calculate_target_ticks_offchain(self, current_tick: int) -> tuple[int | None, int | None]:
        """Calculates target ticks off-chain, replicating contract logic."""
        if self.tick_spacing is None:
             logger.error("Tick spacing not initialized.")
             return None, None
        if current_tick is None:
             logger.error("Current tick is None, cannot calculate target ticks.")
             return None, None
        try:
            # همان منطق محاسبه در قرارداد BaselineMinimal
            # Multiplier is hardcoded as 4 in contract's adjustLiquidityWithCurrentPrice
            width_multiplier = 4
            half_width = (self.tick_spacing * width_multiplier) // 2
            if half_width < self.tick_spacing:
                 half_width = self.tick_spacing # Ensure minimum width

            # محاسبه و هم‌ترازی با tickSpacing
            # Python's // operator behaves like floor for positive results
            target_lower_tick = math.floor((current_tick - half_width) / self.tick_spacing) * self.tick_spacing
            target_upper_tick = math.floor((current_tick + half_width) / self.tick_spacing) * self.tick_spacing

            # اطمینان از اینکه بالا > پایین و تنظیم در صورت نیاز
            if target_lower_tick >= target_upper_tick:
                target_upper_tick = target_lower_tick + self.tick_spacing

            # اعمال محدودیت‌های تیک
            target_lower_tick = max(target_lower_tick, MIN_TICK_CONST)
            target_upper_tick = min(target_upper_tick, MAX_TICK_CONST)

            # بررسی نهایی بعد از اعمال محدودیت
            if target_lower_tick >= target_upper_tick:
                 if target_upper_tick == MAX_TICK_CONST: # اگر به ماکسیمم رسیدیم
                      target_lower_tick = target_upper_tick - self.tick_spacing
                 else: # در غیر این صورت، بالا را افزایش بده
                      target_upper_tick = target_lower_tick + self.tick_spacing
                 # بررسی مجدد پایین ترین حد ممکن
                 target_lower_tick = max(target_lower_tick, MIN_TICK_CONST)

            # اطمینان نهایی از اعتبار
            if target_lower_tick >= target_upper_tick or \
               target_lower_tick < MIN_TICK_CONST or \
               target_upper_tick > MAX_TICK_CONST:
                raise ValueError("Tick calculation resulted in invalid range after adjustments.")

            logger.info(f"Off-chain calculated target ticks: Lower={target_lower_tick}, Upper={target_upper_tick}")
            # ذخیره در متریک‌ها
            self.metrics['targetTickLower_offchain'] = target_lower_tick
            self.metrics['targetTickUpper_offchain'] = target_upper_tick
            return target_lower_tick, target_upper_tick

        except Exception as e:
            logger.error(f"Error calculating target ticks off-chain: {e}")
            return None, None

    def check_token_balances(self) -> tuple:
         """Checks contract token balances."""
         # (کد شما برای check_token_balances)
         try:
            token0_contract = get_contract(self.token0, "IERC20")
            token1_contract = get_contract(self.token1, "IERC20")
            weth_balance = token1_contract.functions.balanceOf(self.contract_address).call()
            usdc_balance = token0_contract.functions.balanceOf(self.contract_address).call()
            has_enough_weth = weth_balance >= MIN_WETH_BALANCE
            has_enough_usdc = usdc_balance >= MIN_USDC_BALANCE
            logger.info(f"Contract Balances - USDC: {usdc_balance / (10**6)}, WETH: {Web3.from_wei(weth_balance, 'ether')}")
            return has_enough_weth, has_enough_usdc, weth_balance, usdc_balance
         except Exception as e:
            logger.error(f"Error checking token balances: {e}")
            return False, False, 0, 0


    def fund_contract(self) -> bool:
         """Funds contract with ETH if needed."""
         # (کد شما برای fund_contract)
         # ...
         try:
            weth_contract = get_contract(self.token1, "IERC20")
            usdc_contract = get_contract(self.token0, "IERC20")
            contract_weth_balance = weth_contract.functions.balanceOf(self.contract_address).call()
            contract_usdc_balance = usdc_contract.functions.balanceOf(self.contract_address).call()

            needs_funding = False
            # Note: Contract needs *some* balance, not necessarily minimums for both if price is skewed
            if contract_weth_balance < MIN_WETH_BALANCE / 2 or contract_usdc_balance < MIN_USDC_BALANCE / 2:
                 # Simple check: if either is very low, assume funding might be needed.
                 # A more complex check would involve price and target ticks.
                 logger.warning("Contract token balance is low, attempting to fund.")
                 needs_funding = True
            else:
                 logger.info("Contract seems to have sufficient token balances.")
                 return True # Already funded

            if needs_funding:
                 account = Account.from_key(os.getenv('PRIVATE_KEY'))
                 w3 = self.contract.w3
                 nonce = w3.eth.get_transaction_count(account.address)
                 gas_price = w3.eth.gas_price
                 eth_to_send = Web3.to_wei(0.04, 'ether') # Amount to send

                 # Check user ETH balance before sending
                 user_eth_balance = w3.eth.get_balance(account.address)
                 if user_eth_balance < eth_to_send + (200000 * gas_price): # Rough gas estimate
                      logger.error(f"Insufficient ETH in wallet {account.address} to fund contract.")
                      return False

                 logger.info(f"Sending {Web3.from_wei(eth_to_send, 'ether')} ETH to contract for auto-processing...")
                 tx = {
                     'from': account.address,
                     'to': self.contract_address,
                     'value': eth_to_send,
                     'nonce': nonce,
                     'gas': 300000, # Increased gas for receive + swap + adjust potential
                     'gasPrice': int(gas_price * 1.1),
                     'chainId': int(w3.net.version)
                 }
                 signed = w3.eth.account.sign_transaction(tx, os.getenv('PRIVATE_KEY'))
                 tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                 receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
                 if receipt.status == 1:
                      logger.info(f"Successfully sent ETH to contract. Tx: {tx_hash.hex()}")
                      time.sleep(5) # Allow time for internal swaps/potential adjustments if any
                      return True
                 else:
                      logger.error(f"Failed to send ETH to contract. Tx: {tx_hash.hex()}")
                      return False
            return True # Should not be reached if logic is correct
         except Exception as e:
            logger.error(f"Error funding contract with ETH: {e}", exc_info=True)
            return False


    def _calculate_actual_price(self, sqrt_price_x96):
         """Calculates readable price from sqrtPriceX96 off-chain."""
         if not sqrt_price_x96 or sqrt_price_x96 == 0:
              self.metrics['actualPrice'] = 0.0
              return 0.0
         try:
             # Ensure sqrt_price_x96 is Decimal for precision
             sqrt_price_x96_dec = Decimal(sqrt_price_x96)
             price_ratio = (sqrt_price_x96_dec / TWO_POW_96)**2
             # Assuming token0=USDC (6 decimals), token1=WETH (18 decimals)
             # price (T0/T1) = 1 / (ratio(T1/T0) * 10**(d0-d1)) = 1 / (ratio / 10**(d1-d0))
             price_t1_t0_adj = price_ratio / (Decimal(10)**(18 - 6))
             actual_price = float(1 / price_t1_t0_adj) if price_t1_t0_adj else 0.0
             self.metrics['actualPrice'] = actual_price
             return actual_price
         except Exception as e:
              logger.warning(f"Could not calculate actual price off-chain: {e}")
              self.metrics['actualPrice'] = 0.0
              return 0.0

    def adjust_position(self) -> bool:
        """
        Checks proximity, funds if needed, calls contract's adjustment function,
        and saves metrics.
        """
        try:
            self.metrics['action_taken'] = self.ACTION_STATES["INIT"]
            self.metrics['error_message'] = "" # Reset error message

            # --- 1. خواندن وضعیت فعلی استخر ---
            _, current_tick = self.get_pool_state() # sqrtPrice is stored in metrics by helper
            if current_tick is None:
                 self.metrics['action_taken'] = self.ACTION_STATES["POOL_READ_FAILED"]
                 self.metrics['error_message'] = "Failed to read pool state"
                 self.save_metrics()
                 return False

            # --- 2. خواندن وضعیت فعلی پوزیشن ---
            position_info = self.get_position_info() # Reads state vars
            has_current_position = position_info.get('active', False) if position_info else False
            current_lower_tick = position_info.get('tickLower') if has_current_position else None
            current_upper_tick = position_info.get('tickUpper') if has_current_position else None
            self.metrics['currentTickLower'] = current_lower_tick
            self.metrics['currentTickUpper'] = current_upper_tick
            self.metrics['liquidity'] = position_info.get('liquidity', 0) if has_current_position else 0

            # --- 3. محاسبه تیک‌های هدف آفچین ---
            target_lower_tick, target_upper_tick = self.calculate_target_ticks_offchain(current_tick)
            if target_lower_tick is None or target_upper_tick is None:
                 self.metrics['action_taken'] = self.ACTION_STATES["CALCULATION_FAILED"]
                 self.metrics['error_message'] = "Failed to calculate target ticks off-chain"
                 self.save_metrics()
                 return False
            # Note: target ticks are already stored in metrics by the helper function

            # --- 4. بررسی نزدیکی (Proximity Check) ---
            if has_current_position:
                TICK_PROXIMITY_THRESHOLD = self.tick_spacing # آستانه: یک برابر فاصله تیک
                # Check if BOTH lower and upper ticks are within the threshold
                is_close = (abs(target_lower_tick - current_lower_tick) <= TICK_PROXIMITY_THRESHOLD and
                            abs(target_upper_tick - current_upper_tick) <= TICK_PROXIMITY_THRESHOLD)

                if is_close:
                    logger.info(f"Off-chain check: Target ticks ({target_lower_tick}, {target_upper_tick}) "
                                f"are within proximity threshold ({TICK_PROXIMITY_THRESHOLD}) "
                                f"of current ticks ({current_lower_tick}, {current_upper_tick}). Skipping adjustment call.")
                    self.metrics['action_taken'] = self.ACTION_STATES["SKIPPED_PROXIMITY"]
                    # Fill final ticks with current ticks as no change happened
                    self.metrics['finalTickLower'] = current_lower_tick
                    self.metrics['finalTickUpper'] = current_upper_tick
                    self.save_metrics()
                    return True # Test step considered successful as no action needed

            # --- 5. تامین مالی (اگر منطق فاندینگ شما لازم است فعال شود) ---
            logger.info("Proximity check passed or no current position. Proceeding with contract call.")
            # Uncomment if explicit funding before adjust is needed
            # if not self.fund_contract():
            #     logger.error("Funding contract failed. Skipping adjustment.")
            #     self.metrics['action_taken'] = self.ACTION_STATES["FUNDING_FAILED"]
            #     self.metrics['error_message'] = "Funding attempt failed"
            #     self.save_metrics()
            #     return False

            # --- 6. فراخوانی تابع قرارداد ---
            logger.info(f"Calling adjustLiquidityWithCurrentPrice on contract {self.contract_address}...")
            account = Account.from_key(os.getenv('PRIVATE_KEY'))
            w3 = self.contract.w3
            gas_price = w3.eth.gas_price
            nonce = w3.eth.get_transaction_count(account.address)

            tx_hash_obj = None
            receipt = None
            adjusted_onchain = False # Flag to track if contract reported adjustment

            try:
                 tx = self.contract.functions.adjustLiquidityWithCurrentPrice().build_transaction({
                     'from': account.address,
                     'nonce': nonce,
                     'gas': 1500000, # Provide ample gas
                     'gasPrice': int(gas_price * 1.1),
                     'chainId': int(w3.net.version)
                 })
                 signed = w3.eth.account.sign_transaction(tx, os.getenv('PRIVATE_KEY'))
                 tx_hash_obj = w3.eth.send_raw_transaction(signed.raw_transaction)
                 self.metrics['tx_hash'] = tx_hash_obj.hex()
                 self.metrics['action_taken'] = self.ACTION_STATES["TX_SENT"]
                 logger.info(f"Transaction sent: {self.metrics['tx_hash']}")

                 receipt = w3.eth.wait_for_transaction_receipt(tx_hash_obj, timeout=180)
                 logger.info(f"Transaction confirmed. Status: {receipt.status if receipt else 'Unknown'}")

                 self.metrics['gas_used'] = receipt.get('gasUsed', 0)
                 if receipt.get('effectiveGasPrice'):
                      self.metrics['gas_cost_eth'] = float(Web3.from_wei(receipt.get('gasUsed', 0) * receipt.get('effectiveGasPrice', 0), 'ether'))

                 # Process receipt and events
                 if receipt.status == 1:
                      # Check the BaselineAdjustmentMetrics event
                      try:
                           logs = self.contract.events.BaselineAdjustmentMetrics().process_receipt(receipt, errors=logging.WARN)
                           if logs:
                                adjusted_onchain = logs[0]['args']['adjusted']
                                # Log the target ticks reported by the contract event
                                event_target_lower = logs[0]['args']['targetTickLower']
                                event_target_upper = logs[0]['args']['targetTickUpper']
                                logger.info(f"Contract event processed. Adjusted: {adjusted_onchain}. Event Target Ticks: ({event_target_lower}, {event_target_upper})")
                                # Check consistency (optional)
                                if event_target_lower != target_lower_tick or event_target_upper != target_upper_tick:
                                     logger.warning("Mismatch between off-chain calculated target ticks and event target ticks!")
                                # Update final action state based on event
                                self.metrics['action_taken'] = self.ACTION_STATES["TX_SUCCESS_ADJUSTED"] if adjusted_onchain else self.ACTION_STATES["TX_SUCCESS_SKIPPED_ONCHAIN"]
                           else:
                                logger.warning("BaselineAdjustmentMetrics event not found in successful transaction.")
                                self.metrics['action_taken'] = self.ACTION_STATES["TX_SUCCESS_ADJUSTED"] # Assume adjusted if event missing
                      except Exception as log_exc:
                           logger.warning(f"Error processing BaselineAdjustmentMetrics event: {log_exc}")
                           self.metrics['action_taken'] = self.ACTION_STATES["TX_SUCCESS_ADJUSTED"] # Assume adjusted

                 else: # receipt.status == 0
                      self.metrics['action_taken'] = self.ACTION_STATES["TX_REVERTED"]
                      self.metrics['error_message'] = "tx_reverted_onchain"
                      logger.error("Transaction reverted on-chain.")
                      # TODO: Add revert reason fetching if needed

            except Exception as e:
                 logger.error(f"Transaction failed (send or wait): {e}", exc_info=True)
                 if self.metrics['tx_hash']: # If tx was sent but wait failed
                      self.metrics['action_taken'] = self.ACTION_STATES["TX_WAIT_FAILED"]
                      self.metrics['error_message'] = f"tx_wait_failed: {str(e)}"
                 else: # If send itself failed
                      self.metrics['action_taken'] = self.ACTION_STATES["UNEXPECTED_ERROR"]
                      self.metrics['error_message'] = f"tx_send_failed: {str(e)}"
                 self.save_metrics() # Save error state
                 return False

            # --- 7. خواندن وضعیت نهایی و ذخیره متریک‌ها ---
            final_position_info = self.get_position_info()
            if final_position_info:
                 self.metrics['liquidity'] = final_position_info.get('liquidity', 0)
                 self.metrics['finalTickLower'] = final_position_info.get('tickLower') # تیک‌های نهایی پوزیشن
                 self.metrics['finalTickUpper'] = final_position_info.get('tickUpper')
            else: # If position info fails after tx, log warning
                 logger.warning("Could not read final position info after transaction.")
                 # Use target ticks as final if adjustment happened, else current
                 if adjusted_onchain:
                      self.metrics['finalTickLower'] = target_lower_tick
                      self.metrics['finalTickUpper'] = target_upper_tick
                 else:
                      self.metrics['finalTickLower'] = current_lower_tick
                      self.metrics['finalTickUpper'] = current_upper_tick


            self.save_metrics()
            return receipt.status == 1 # Return True if transaction succeeded

        except Exception as e:
            logger.exception("An unexpected error occurred in adjust_position:")
            self.metrics['action_taken'] = self.ACTION_STATES["UNEXPECTED_ERROR"]
            self.metrics['error_message'] = str(e)
            self.save_metrics()
            return False

    def save_metrics(self):
        """Saves the current state of self.metrics to the CSV file."""
        self.metrics['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        filepath = Path(__file__).parent.parent.parent / 'position_results_baseline_v2.csv' # نام فایل جدید
        file_exists = filepath.exists()

        # ستون‌های کلیدی برای فایل CSV
        columns = [
            'timestamp', 'contract_type', 'action_taken', 'tx_hash',
            'actualPrice', 'sqrtPriceX96', 'currentTick',
            'targetTickLower_offchain', 'targetTickUpper_offchain', # محاسبه شده آفچین
            'currentTickLower', 'currentTickUpper', # وضعیت قبل از فراخوانی
            'finalTickLower', 'finalTickUpper',     # وضعیت بعد از فراخوانی (اگر تغییر کرد)
            'liquidity', 'gas_used', 'gas_cost_eth', 'error_message'
        ]

        try:
            # اطمینان از اینکه همه کلیدهای ستون‌ها در متریک وجود دارند (با مقدار پیش‌فرض None)
            for col in columns:
                 self.metrics.setdefault(col, None)

            with open(filepath, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
                if not file_exists:
                    writer.writeheader()
                # تهیه داده ردیف، جایگزینی None با رشته خالی برای CSV
                row_data = {k: "" if self.metrics.get(k) is None else self.metrics.get(k) for k in columns}
                writer.writerow(row_data)
            logger.info(f"Metrics saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")

    # def get_position_info(self): # Use the one from base class or implement as needed
    #     # ... (Implementation to read contract state vars)

    def execute_test_steps(self) -> bool:
        """Runs the test steps."""
        logger.info(f"--- Starting Test Cycle for {self.contract_address} ---")
        if not self.setup():
             logger.error("Setup failed. Aborting test.")
             return False # Setup failure already saved metrics

        success = self.adjust_position() # adjust_position handles metric saving

        logger.info(f"--- Test Cycle Ended. Result: {'Success' if success else 'Failure'} ---")
        return success


# --- Main Function ---
def main():
    """Main test execution function."""
    try:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("baseline_test.log"), # لاگ در فایل
                logging.StreamHandler() # لاگ در کنسول
            ]
        )
        baseline_address = os.getenv('BASELINE_MINIMAL_ADDRESS')
        if not baseline_address:
            raise ValueError("BASELINE_MINIMAL_ADDRESS not found in environment")

        test = BaselineTest(baseline_address)
        # فقط یک بار اجرا می‌کنیم
        test.execute_test_steps()

    except Exception as e:
        logger.exception("Main execution failed:")

if __name__ == "__main__":
    main()