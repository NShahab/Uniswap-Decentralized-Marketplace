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

sys.path.append(str(Path(__file__).parent.parent))
from utils.test_base import LiquidityTestBase
from utils.web3_utils import send_transaction, init_web3, get_contract

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
            'actualPrice': None,
            'sqrtPriceX96': 0,
            'currentTick': 0,
            'finalTickLower': 0,
            'finalTickUpper': 0,
            'liquidity': 0,
            'gas_used': 0,
            'gas_cost_eth': 0.0
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
            
    def calculate_ticks(self) -> tuple:
        """Calculate ticks based on predicted price (off-chain logic)."""
        try:
            # تبدیل آدرس‌ها به checksum
            self.token0 = Web3.to_checksum_address(self.token0)
            self.token1 = Web3.to_checksum_address(self.token1)
            self.contract_address = Web3.to_checksum_address(self.contract_address)

            self.predicted_price = self.get_predicted_price()
            if not self.predicted_price:
                return None, None
            self.metrics['input_price'] = self.predicted_price
            self.metrics['predictedPrice'] = self.predicted_price
            token0_decimals = self.contract.functions.token0Decimals().call()
            token1_decimals = self.contract.functions.token1Decimals().call()
            # Off-chain tick calculation (replicate contract logic)
            price_ratio = 1.0 / self.predicted_price
            ratio = price_ratio * (10**(token1_decimals - token0_decimals))
            sqrt_price_x96 = int((ratio ** 0.5) * TWO_POW_96)
            predicted_tick = int((math.log(sqrt_price_x96 / TWO_POW_96) / (0.5 * math.log(1.0001))))
            tick_spacing = self.contract.functions.tickSpacing().call()
            range_multiplier = self.contract.functions.rangeWidthMultiplier().call()
            half_width = (tick_spacing * range_multiplier) // 2
            lower_tick = ((predicted_tick - half_width) // tick_spacing) * tick_spacing
            upper_tick = ((predicted_tick + half_width) // tick_spacing) * tick_spacing
            self.metrics['finalTickLower'] = lower_tick
            self.metrics['finalTickUpper'] = upper_tick
            # Get current pool price for actual price metric
            try:
                factory_addr = self.contract.functions.factory().call()
                factory_contract = get_contract(factory_addr, "IUniswapV3Factory")
                pool_address = factory_contract.functions.getPool(
                    self.token0,
                    self.token1,
                    self.contract.functions.fee().call()
                ).call()
                pool_contract = get_contract(pool_address, "IUniswapV3Pool")
                slot0 = pool_contract.functions.slot0().call()
                sqrt_price_x96_onchain, current_tick = slot0[0], slot0[1]
                self.metrics['sqrtPriceX96'] = sqrt_price_x96_onchain
                self.metrics['currentTick'] = current_tick
                price_ratio_onchain = (sqrt_price_x96_onchain / TWO_POW_96)**2
                price_t1_t0_adj = price_ratio_onchain / (10**(token1_decimals - token0_decimals))
                self.metrics['actualPrice'] = 1.0 / price_t1_t0_adj if price_t1_t0_adj else 0
            except Exception as e:
                logger.warning(f"Failed to get actual price: {e}")
            logger.info(f"Calculated ticks - Lower: {lower_tick}, Upper: {upper_tick}")
            return lower_tick, upper_tick
        except Exception as e:
            logger.error(f"Failed to calculate ticks: {e}")
            return None, None
            
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
                if user_weth_balance < (MIN_WETH_BALANCE - contract_weth_balance):
                    logger.error("Not enough WETH in your wallet. Please wrap ETH to WETH first.")
                    return False
                tx1 = token1_contract.functions.transfer(contract_address, MIN_WETH_BALANCE - contract_weth_balance).build_transaction({
                    'from': account.address,
                    'nonce': nonce,
                    'gas': 100000,
                    'gasPrice': int(gas_price * 1.1),
                    'chainId': int(w3.net.version)
                })
                signed_tx1 = w3.eth.account.sign_transaction(tx1, os.getenv('PRIVATE_KEY'))
                tx_hash1 = w3.eth.send_raw_transaction(signed_tx1.raw_transaction)
                w3.eth.wait_for_transaction_receipt(tx_hash1, timeout=180)
                logger.info(f"Funded contract with WETH: {MIN_WETH_BALANCE - contract_weth_balance}")
                nonce += 1
                funded = True
            else:
                logger.info("Contract already has enough WETH.")

            # --- USDC ---
            token0_contract = get_contract(token0, "IERC20")
            contract_usdc_balance = token0_contract.functions.balanceOf(contract_address).call()
            if contract_usdc_balance < MIN_USDC_BALANCE:
                user_usdc_balance = token0_contract.functions.balanceOf(account.address).call()
                if user_usdc_balance < (MIN_USDC_BALANCE - contract_usdc_balance):
                    logger.error("Not enough USDC in your wallet.")
                    return False
                tx2 = token0_contract.functions.transfer(contract_address, MIN_USDC_BALANCE - contract_usdc_balance).build_transaction({
                    'from': account.address,
                    'nonce': nonce,
                    'gas': 100000,
                    'gasPrice': int(gas_price * 1.1),
                    'chainId': int(w3.net.version)
                })
                signed_tx2 = w3.eth.account.sign_transaction(tx2, os.getenv('PRIVATE_KEY'))
                tx_hash2 = w3.eth.send_raw_transaction(signed_tx2.raw_transaction)
                w3.eth.wait_for_transaction_receipt(tx_hash2, timeout=180)
                logger.info(f"Funded contract with USDC: {MIN_USDC_BALANCE - contract_usdc_balance}")
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
            lower_tick, upper_tick = self.calculate_ticks()
            # Off-chain: check if position needs adjustment
            position_info = self.get_position_info()
            if position_info and position_info.get('hasPosition'):
                if position_info.get('lowerTick') == lower_tick and position_info.get('upperTick') == upper_tick:
                    logger.info("Ticks unchanged, skipping adjustment.")
                    self.save_metrics(receipt=None, success=False)
                    return True
            if not self.fund_contract():
                return False
            token0_decimals = self.contract.functions.token0Decimals().call()
            token1_decimals = self.contract.functions.token1Decimals().call()
            scaled_price = self.predicted_price / (10 ** token0_decimals)
            price_to_send = int(scaled_price * (10 ** token1_decimals))
            account = Account.from_key(os.getenv('PRIVATE_KEY'))
            w3 = self.contract.w3
            gas_price = w3.eth.gas_price
            nonce = w3.eth.get_transaction_count(account.address)
            tx = self.contract.functions.updatePredictionAndAdjust(price_to_send).build_transaction({
                'from': account.address,
                'nonce': nonce,
                'gas': 1500000,
                'gasPrice': int(gas_price * 1.1),
                'chainId': int(w3.net.version)
            })
            signed = w3.eth.account.sign_transaction(tx, os.getenv('PRIVATE_KEY'))
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            # --- مقداردهی دقیق فیلدهای liquidity و actualPrice و input_price ---
            position_info = self.get_position_info()
            if position_info:
                self.metrics['liquidity'] = position_info.get('liquidity', 0)
            sqrt_price_x96 = self.metrics.get('sqrtPriceX96')
            if sqrt_price_x96:
                price_ratio = (sqrt_price_x96 / TWO_POW_96) ** 2
                price_t1_t0_adj = price_ratio / (10**(token1_decimals - token0_decimals))
                actual_price = 1.0 / price_t1_t0_adj if price_t1_t0_adj else 0
                self.metrics['actualPrice'] = actual_price
                self.metrics['input_price'] = actual_price
            if receipt.status != 1:
                logger.error("Position adjustment failed")
                self.save_metrics(receipt, success=False)
                return False
            logger.info("Position adjusted successfully")
            self.save_metrics(receipt, success=True)
            return True
        except Exception as e:
            logger.error(f"Failed to adjust position: {e}")
            return False
            
    def save_metrics(self, receipt: dict = None, success: bool = False):
        """Save position metrics to CSV."""
        try:
            self.metrics['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.metrics['action_taken'] = success
            
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
                    
            # Get current position info for liquidity
            position_info = self.get_position_info()
            if position_info:
                self.metrics['liquidity'] = position_info.get('liquidity', 0)
                
            # Save to CSV
            filepath = Path(__file__).parent.parent.parent / 'position_results.csv'
            file_exists = filepath.exists()
            
            with open(filepath, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(self.metrics.keys()))
                if not file_exists:
                    writer.writeheader()
                writer.writerow(self.metrics)
                
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