"""Test implementation for PredictiveLiquidityManager contract with complete functionality."""

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
from decimal import Decimal, ROUND_DOWN

sys.path.append(str(Path(__file__).parent.parent))
from utils.test_base import LiquidityTestBase
from utils.web3_utils import send_transaction, init_web3, get_contract, wrap_eth_to_weth

# Constants
MIN_WETH_BALANCE = Web3.to_wei(0.01, 'ether')
MIN_USDC_BALANCE = 10 * (10**6)  # 10 USDC
TWO_POW_96 = 2**96

logger = logging.getLogger('predictive_test')

class PredictiveTest(LiquidityTestBase):
    """Enhanced test implementation for PredictiveLiquidityManager contract."""
    
    def __init__(self, contract_address: str):
        super().__init__(contract_address, "PredictiveLiquidityManager")
        self.metrics = {
            'timestamp': None,
            'contract_type': 'Predictive',
            'action_taken': False,
            'tx_hash': None,
            'input_price': 0,
            'predictedPrice': None,
            'predictedTick': None,
            'actualPrice': None,
            'sqrtPriceX96': 0,
            'currentTick': 0,
            'finalTickLower': 0,
            'finalTickUpper': 0,
            'liquidity': 0,
            'gas_used': 0,
            'gas_cost_eth': 0.0,
            'error_message': ""
        }
        self.predicted_price = None
        
    def get_predicted_price(self) -> float:
        """Get predicted ETH price from API or fallback."""
        try:
            # Try Coinbase API first
            response = requests.get('https://api.coinbase.com/v2/prices/ETH-USD/spot', timeout=10)
            response.raise_for_status()
            price = float(response.json()['data']['amount'])
            logger.info(f"Fetched ETH price: {price} USD")
            return price
            
        except Exception as e:
            logger.warning(f"Error getting price from Coinbase: {e}")
            fallback_price = 3000.0
            logger.warning(f"Using fallback price: {fallback_price} USD")
            return fallback_price
            
    def calculate_predicted_tick(self, price: float) -> int:
        """Convert predicted price to Uniswap v3 tick (off-chain, overflow-safe)."""
        try:
            token0_decimals = self.contract.functions.token0Decimals().call()
            token1_decimals = self.contract.functions.token1Decimals().call()
            price_decimal = Decimal(str(price)).quantize(Decimal('1.000000000000000000'))
            inverse_price = Decimal(1) / price_decimal
            # Adjust for decimals difference
            if token1_decimals > token0_decimals:
                ratio = inverse_price * Decimal(10 ** (token1_decimals - token0_decimals))
            else:
                ratio = inverse_price / Decimal(10 ** (token0_decimals - token1_decimals))
            sqrt_ratio = ratio.sqrt()
            sqrt_price_x96 = float(sqrt_ratio) * (2 ** 96)
            tick = int(math.log(sqrt_price_x96 / (2 ** 96)) / math.log(1.0001))
            return tick
        except Exception as e:
            logger.error(f"Failed to calculate predicted tick: {e}")
            return 0

    def check_token_balances(self) -> tuple:
        """Check if contract has sufficient token balances."""
        try:
            # تبدیل آدرس‌ها به checksum
            token0 = Web3.to_checksum_address(self.token0)
            token1 = Web3.to_checksum_address(self.token1)
            contract_address = Web3.to_checksum_address(self.contract_address)

            token0_contract = get_contract(token0, "IERC20")
            token1_contract = get_contract(token1, "IERC20")
            
            weth_balance = token1_contract.functions.balanceOf(contract_address).call()
            usdc_balance = token0_contract.functions.balanceOf(contract_address).call()
            
            has_enough_weth = weth_balance >= MIN_WETH_BALANCE
            has_enough_usdc = usdc_balance >= MIN_USDC_BALANCE
            
            return has_enough_weth, has_enough_usdc, weth_balance, usdc_balance
            
        except Exception as e:
            logger.error(f"Error checking token balances: {e}")
            return False, False, 0, 0
            
    def fund_contract(self) -> bool:
        """Fund the contract with WETH و USDC only if needed."""
        try:
            # تبدیل آدرس‌ها به checksum
            token0 = Web3.to_checksum_address(self.token0)
            token1 = Web3.to_checksum_address(self.token1)
            contract_address = Web3.to_checksum_address(self.contract_address)

            account = Account.from_key(os.getenv('PRIVATE_KEY'))
            w3 = self.contract.w3
            nonce = w3.eth.get_transaction_count(account.address)
            gas_price = w3.eth.gas_price
            funded = False

            # --- WETH ---
            token1_contract = get_contract(token1, "IERC20")
            contract_weth_balance = token1_contract.functions.balanceOf(contract_address).call()
            if contract_weth_balance < MIN_WETH_BALANCE:
                user_weth_balance = token1_contract.functions.balanceOf(account.address).call()
                required_weth = MIN_WETH_BALANCE - contract_weth_balance
                if user_weth_balance < required_weth:
                    # Try to wrap ETH to WETH automatically
                    eth_balance = w3.eth.get_balance(account.address)
                    if eth_balance > required_weth:
                        logger.info(f"Wrapping {Web3.from_wei(required_weth, 'ether')} ETH to WETH...")
                        wrap_success = wrap_eth_to_weth(required_weth)
                        if wrap_success:
                            # Update user_weth_balance after wrapping
                            user_weth_balance = token1_contract.functions.balanceOf(account.address).call()
                        else:
                            logger.error("Failed to wrap ETH to WETH automatically.")
                            return False
                    else:
                        logger.error("Not enough WETH or ETH in your wallet to wrap.")
                        return False
                tx1 = token1_contract.functions.transfer(contract_address, required_weth).build_transaction({
                    'from': account.address,
                    'nonce': nonce,
                    'gas': 100000,
                    'gasPrice': int(gas_price * 1.1),
                    'chainId': int(w3.net.version)
                })
                signed_tx1 = w3.eth.account.sign_transaction(tx1, os.getenv('PRIVATE_KEY'))
                tx_hash1 = w3.eth.send_raw_transaction(signed_tx1.raw_transaction)
                w3.eth.wait_for_transaction_receipt(tx_hash1, timeout=180)
                logger.info(f"Funded contract with WETH: {required_weth}")
                nonce += 1
                funded = True
            else:
                logger.info("Contract already has enough WETH.")

            # --- USDC ---
            token0_contract = get_contract(token0, "IERC20")
            contract_usdc_balance = token0_contract.functions.balanceOf(contract_address).call()
            if contract_usdc_balance < MIN_USDC_BALANCE:
                user_usdc_balance = token0_contract.functions.balanceOf(account.address).call()
                required_usdc = MIN_USDC_BALANCE - contract_usdc_balance
                if user_usdc_balance < required_usdc:
                    logger.error("Not enough USDC in your wallet.")
                    return False
                # --- APPROVE USDC ---
                approve_tx = token0_contract.functions.approve(contract_address, required_usdc).build_transaction({
                    'from': account.address,
                    'nonce': nonce,
                    'gas': 60000,
                    'gasPrice': int(gas_price * 1.1),
                    'chainId': int(w3.net.version)
                })
                signed_approve = w3.eth.account.sign_transaction(approve_tx, os.getenv('PRIVATE_KEY'))
                approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
                w3.eth.wait_for_transaction_receipt(approve_hash, timeout=180)
                nonce += 1
                # --- TRANSFER USDC ---
                tx2 = token0_contract.functions.transfer(contract_address, required_usdc).build_transaction({
                    'from': account.address,
                    'nonce': nonce,
                    'gas': 100000,
                    'gasPrice': int(gas_price * 1.1),
                    'chainId': int(w3.net.version)
                })
                signed_tx2 = w3.eth.account.sign_transaction(tx2, os.getenv('PRIVATE_KEY'))
                tx_hash2 = w3.eth.send_raw_transaction(signed_tx2.raw_transaction)
                w3.eth.wait_for_transaction_receipt(tx_hash2, timeout=180)
                logger.info(f"Funded contract with USDC: {required_usdc}")
                funded = True
            else:
                logger.info("Contract already has enough USDC.")

            if funded:
                time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"Error funding contract with tokens: {e}")
            return False
            
    def adjust_position(self) -> bool:
        try:
            # --- دریافت قیمت پیش‌بینی‌شده ---
            self.predicted_price = self.get_predicted_price()
            predicted_tick = self.calculate_predicted_tick(self.predicted_price)
            self.metrics['predictedPrice'] = float(self.predicted_price)
            self.metrics['predictedTick'] = predicted_tick

            # محاسبه بازه تیک جدید
            tick_spacing = self.contract.functions.tickSpacing().call()
            range_multiplier = self.contract.functions.rangeWidthMultiplier().call()
            half_width = (tick_spacing * range_multiplier) // 2
            lower_tick = ((predicted_tick - half_width) // tick_spacing) * tick_spacing
            upper_tick = ((predicted_tick + half_width) // tick_spacing) * tick_spacing
            lower_tick = max(lower_tick, -887272)
            upper_tick = min(upper_tick, 887272)
            if lower_tick >= upper_tick:
                upper_tick = lower_tick + tick_spacing
            self.metrics['finalTickLower'] = lower_tick
            self.metrics['finalTickUpper'] = upper_tick

            # بررسی موقعیت فعلی
            position_info = self.get_position_info()
            if position_info and position_info.get('hasPosition'):
                if position_info.get('lowerTick') == lower_tick and position_info.get('upperTick') == upper_tick:
                    logger.info("Ticks unchanged, skipping adjustment.")
                    self.save_metrics(receipt=None, success=False)
                    return True
            if not self.fund_contract():
                self.save_metrics(receipt=None, success=False, error_message="funding_failed")
                return False
            # --- ارسال predictedTick به قرارداد ---
            account = Account.from_key(os.getenv('PRIVATE_KEY'))
            w3 = self.contract.w3
            gas_price = w3.eth.gas_price
            nonce = w3.eth.get_transaction_count(account.address)
            tx = self.contract.functions.updatePredictionAndAdjust(predicted_tick).build_transaction({
                'from': account.address,
                'nonce': nonce,
                'gas': 1500000,
                'gasPrice': int(gas_price * 1.1),
                'chainId': int(w3.net.version)
            })
            signed = w3.eth.account.sign_transaction(tx, os.getenv('PRIVATE_KEY'))
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            except Exception as e:
                logger.error("Position adjustment failed")
                self.save_metrics(receipt=None, success=False, error_message=str(e))
                return False
            # مقداردهی sqrtPriceX96 از استخر یونی‌سواپ
            try:
                pool_address = self.contract.functions.pool().call()
                pool_contract = get_contract(pool_address, "IUniswapV3Pool")
                slot0 = pool_contract.functions.slot0().call()
                sqrt_price_x96 = slot0[0]
                self.metrics['sqrtPriceX96'] = sqrt_price_x96
                self.metrics['currentTick'] = slot0[1]
            except Exception as e:
                logger.warning(f"Could not fetch sqrtPriceX96 from pool: {e}")
            # مقداردهی دقیق فیلدهای liquidity و actualPrice و input_price
            position_info = self.get_position_info()
            if position_info:
                self.metrics['liquidity'] = position_info.get('liquidity', 0)
            sqrt_price_x96 = self.metrics.get('sqrtPriceX96')
            if sqrt_price_x96:
                token0_decimals = self.contract.functions.token0Decimals().call()
                token1_decimals = self.contract.functions.token1Decimals().call()
                price_ratio = (sqrt_price_x96 / TWO_POW_96) ** 2
                price_t1_t0_adj = price_ratio / (10**(token1_decimals - token0_decimals))
                actual_price = 1.0 / price_t1_t0_adj if price_t1_t0_adj else 0
                self.metrics['actualPrice'] = actual_price
                self.metrics['input_price'] = actual_price
            if receipt.status != 1:
                error_message = "onchain_failed"
                try:
                    call_tx = dict(tx)
                    call_tx.pop('gas', None)
                    call_tx.pop('gasPrice', None)
                    call_tx.pop('nonce', None)
                    call_tx['to'] = self.contract_address
                    call_tx['from'] = account.address
                    try:
                        w3.eth.call(call_tx, block_identifier=receipt.blockNumber)
                    except Exception as call_exc:
                        if hasattr(call_exc, 'args') and len(call_exc.args) > 0:
                            msg = str(call_exc.args[0])
                            if 'revert' in msg:
                                error_message = msg[msg.find('revert')+7:].strip()
                            else:
                                error_message = msg
                        else:
                            error_message = str(call_exc)
                except Exception as e:
                    error_message = f"onchain_failed: {str(e)}"
                logger.error(f"Position adjustment failed: {error_message}")
                self.save_metrics(receipt=receipt, success=False, error_message=error_message)
                return False
            logger.info("Position adjusted successfully")
            self.save_metrics(receipt=receipt, success=True)
            return True
        except Exception as e:
            logger.error(f"Failed to adjust position: {e}")
            self.save_metrics(receipt=None, success=False, error_message=str(e))
            return False
            
    def save_metrics(self, receipt: dict = None, success: bool = False, error_message: str = None):
        """Save position metrics to CSV with clear action_taken and error_message."""
        try:
            if error_message == "funding_failed":
                action_taken = "funding_failed"
            elif receipt is None:
                action_taken = "offchain_skipped"
            elif receipt and receipt.get('status', 0) == 1:
                action_taken = "onchain_success"
            else:
                action_taken = "onchain_failed"
            self.metrics['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.metrics['action_taken'] = action_taken
            self.metrics['error_message'] = error_message or ""
            if receipt:
                self.metrics['tx_hash'] = receipt.get('transactionHash', '').hex()
                self.metrics['gas_used'] = receipt.get('gasUsed', 0)
                if receipt.get('effectiveGasPrice'):
                    self.metrics['gas_cost_eth'] = float(
                        Web3.from_wei(
                            receipt.get('gasUsed', 0) * receipt.get('effectiveGasPrice'),
                            'ether'
                        )
                    )
            position_info = self.get_position_info()
            if position_info:
                self.metrics['liquidity'] = position_info.get('liquidity', 0)
            filepath = Path(__file__).parent.parent.parent / 'position_results.csv'
            file_exists = filepath.exists()
            columns = [
                'timestamp','contract_type','action_taken','tx_hash','input_price','predictedPrice','predictedTick','actualPrice',
                'sqrtPriceX96','currentTick','finalTickLower','finalTickUpper','liquidity','gas_used','gas_cost_eth','error_message'
            ]
            with open(filepath, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({col: self.metrics.get(col, "") for col in columns})
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")

def main():
    """Main test execution function."""
    try:
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Get contract address
        predictive_address = os.getenv('PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS')
        if not predictive_address:
            raise ValueError("PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS not found in environment")
            
        # Run test
        test = PredictiveTest(predictive_address)
        success = test.execute_test_steps()
        
        if success:
            logger.info("Predictive test completed successfully")
        else:
            logger.error("Predictive test failed")
            
    except Exception as e:
        logger.error(f"Test execution failed: {e}")

if __name__ == "__main__":
    main()