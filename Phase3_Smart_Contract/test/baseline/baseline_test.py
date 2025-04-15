"""Test implementation for BaselineMinimal contract with complete functionality."""

import os
import sys
import json
import time
import logging
import csv
from datetime import datetime
from pathlib import Path
from web3 import Web3
from eth_account import Account

sys.path.append(str(Path(__file__).parent.parent))
from utils.test_base import LiquidityTestBase
from utils.web3_utils import send_transaction, init_web3, get_contract, load_contract_abi

# Constants
MIN_WETH_BALANCE = Web3.to_wei(0.02, 'ether')
MIN_USDC_BALANCE = 10 * (10**6)
TWO_POW_96 = 2**96

logger = logging.getLogger('baseline_test')

class BaselineTest(LiquidityTestBase):
    """Enhanced test implementation for BaselineMinimal contract."""
    
    def __init__(self, contract_address: str):
        super().__init__(contract_address, "BaselineMinimal")
        self.factory_contract = None
        self.metrics = {
            'timestamp': None,
            'contract_type': 'Baseline',
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

    def setup(self) -> bool:
        """Extended setup to include factory contract initialization."""
        if not super().setup():
            return False
            
        try:
            # Get factory address from contract
            factory_address = self.contract.functions.factory().call()
            self.factory_contract = get_contract(factory_address, "IUniswapV3Factory")
            logger.info(f"Factory contract initialized at {factory_address}")
            return True
            
        except Exception as e:
            logger.error(f"Factory setup failed: {e}")
            return False
            
    def check_token_balances(self) -> tuple:
        """Check if contract has sufficient token balances."""
        try:
            token0_contract = get_contract(self.token0, "IERC20")
            token1_contract = get_contract(self.token1, "IERC20")
            
            weth_balance = token1_contract.functions.balanceOf(self.contract_address).call()
            usdc_balance = token0_contract.functions.balanceOf(self.contract_address).call()
            
            has_enough_weth = weth_balance >= MIN_WETH_BALANCE
            has_enough_usdc = usdc_balance >= MIN_USDC_BALANCE
            
            logger.info(f"Token0 balance: {usdc_balance / (10**6)}")
            logger.info(f"Token1 balance: {Web3.from_wei(weth_balance, 'ether')}")
            
            return has_enough_weth, has_enough_usdc, weth_balance, usdc_balance
            
        except Exception as e:
            logger.error(f"Error checking token balances: {e}")
            return False, False, 0, 0
            
    def fund_contract(self) -> bool:
        """Fund contract with ETH only if needed (BaselineMinimal auto-wraps and swaps)."""
        try:
            weth_contract = get_contract(self.token1, "IERC20")
            usdc_contract = get_contract(self.token0, "IERC20")
            contract_weth_balance = weth_contract.functions.balanceOf(self.contract_address).call()
            contract_usdc_balance = usdc_contract.functions.balanceOf(self.contract_address).call()
            if contract_weth_balance >= MIN_WETH_BALANCE and contract_usdc_balance >= MIN_USDC_BALANCE:
                logger.info("Contract already has enough WETH and USDC.")
                return True
            account = Account.from_key(os.getenv('PRIVATE_KEY'))
            w3 = self.contract.w3
            nonce = w3.eth.get_transaction_count(account.address)
            gas_price = w3.eth.gas_price
            eth_to_send = Web3.to_wei(0.04, 'ether')  # مقدار ETH که می‌خواهی بفرستی
            tx = {
                'from': account.address,
                'to': self.contract_address,
                'value': eth_to_send,
                'nonce': nonce,
                'gas': 150000,
                'gasPrice': int(gas_price * 1.1),
                'chainId': int(w3.net.version)
            }
            signed = w3.eth.account.sign_transaction(tx, os.getenv('PRIVATE_KEY'))
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            logger.info(f"Sent {Web3.from_wei(eth_to_send, 'ether')} ETH to contract for auto-wrapping and swap.")
            time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"Error funding contract with ETH: {e}")
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
            account = Account.from_key(os.getenv('PRIVATE_KEY'))
            w3 = self.contract.w3
            gas_price = w3.eth.gas_price
            nonce = w3.eth.get_transaction_count(account.address)
            tx = self.contract.functions.adjustLiquidityWithCurrentPrice().build_transaction({
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
                price_t1_t0_adj = price_ratio / (10**(18 - 6))
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
            
    def calculate_ticks(self) -> tuple:
        """Calculate ticks based on current pool price (off-chain logic)."""
        try:
            if not self.factory_contract:
                raise ValueError("Factory contract not initialized")
            pool_address = self.factory_contract.functions.getPool(
                self.token0,
                self.token1,
                self.contract.functions.fee().call()
            ).call()
            if pool_address == '0x0000000000000000000000000000000000000000':
                raise ValueError("Pool not found")
            pool_contract = get_contract(pool_address, "IUniswapV3Pool")
            slot0 = pool_contract.functions.slot0().call()
            sqrt_price_x96, current_tick = slot0[0], slot0[1]
            self.metrics['sqrtPriceX96'] = sqrt_price_x96
            self.metrics['currentTick'] = current_tick
            try:
                price_ratio = (sqrt_price_x96 / TWO_POW_96)**2
                price_t1_t0_adj = price_ratio / (10**(18 - 6))  # WETH(18) - USDC(6)
                self.metrics['actualPrice'] = 1.0 / price_t1_t0_adj if price_t1_t0_adj else 0
                self.metrics['input_price'] = self.metrics['actualPrice']
            except Exception as e:
                logger.warning(f"Failed to calculate actual price: {e}")
            tick_spacing = self.contract.functions.tickSpacing().call()
            half_width = (tick_spacing * 4) // 2
            lower_tick = ((current_tick - half_width) // tick_spacing) * tick_spacing
            upper_tick = ((current_tick + half_width) // tick_spacing) * tick_spacing
            self.metrics['finalTickLower'] = lower_tick
            self.metrics['finalTickUpper'] = upper_tick
            logger.info(f"Calculated ticks - Lower: {lower_tick}, Upper: {upper_tick}")
            return lower_tick, upper_tick
        except Exception as e:
            logger.error(f"Failed to calculate ticks: {e}")
            return None, None
            
    def save_metrics(self, receipt: dict = None, success: bool = False):
        try:
            # مقداردهی دقیق هر ستون مطابق با فرمت position_results.csv
            metrics = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'contract_type': 'Baseline',
                'action_taken': success,
                'tx_hash': receipt.get('transactionHash', '').hex() if receipt else 'FUNDING_FAILED',
                'input_price': self.metrics.get('input_price', 0.0),
                'predictedPrice': getattr(self, 'predicted_price', 0.0),
                'actualPrice': self.metrics.get('actualPrice', 0.0),
                'sqrtPriceX96': self.metrics.get('sqrtPriceX96', 0),
                'currentTick': self.metrics.get('currentTick', 0),
                'finalTickLower': self.metrics.get('finalTickLower', 0),
                'finalTickUpper': self.metrics.get('finalTickUpper', 0),
                'liquidity': self.metrics.get('liquidity', 0),
                'gas_used': receipt.get('gasUsed', 0) if receipt else 0,
                'gas_cost_eth': float(Web3.from_wei(receipt.get('gasUsed', 0) * receipt.get('effectiveGasPrice', 0), 'ether')) if receipt else 0.0
            }
            # ترتیب دقیق ستون‌ها مطابق فایل CSV
            columns = [
                'timestamp','contract_type','action_taken','tx_hash','input_price','predictedPrice','actualPrice',
                'sqrtPriceX96','currentTick','finalTickLower','finalTickUpper','liquidity','gas_used','gas_cost_eth'
            ]
            filepath = Path(__file__).parent.parent.parent / 'position_results.csv'
            file_exists = filepath.exists()
            with open(filepath, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({col: metrics.get(col, 0) for col in columns})
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
        baseline_address = os.getenv('BASELINE_MINIMAL_ADDRESS')
        if not baseline_address:
            raise ValueError("BASELINE_MINIMAL_ADDRESS not found in environment")
            
        # Run test
        test = BaselineTest(baseline_address)
        success = test.execute_test_steps()
        
        if success:
            logger.info("Baseline test completed successfully")
        else:
            logger.error("Baseline test failed")
            
    except Exception as e:
        logger.error(f"Test execution failed: {e}")

if __name__ == "__main__":
    main()