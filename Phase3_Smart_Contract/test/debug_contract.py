"""
Debug script for investigating PredictiveLiquidityManager contract issues
"""
import os
import json
import logging
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('contract_debug.log'),
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()

# Network settings
SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
PREDICTIVE_MANAGER_ADDRESS = os.getenv("PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS")
USDC_ADDRESS = os.getenv("USDC_ADDRESS")
WETH_ADDRESS = os.getenv("WETH_ADDRESS")

# Constants for testing
TEST_PRICE = 1538.4797  # Test with the price that failed

def load_contract_abi(contract_name):
    """Load contract ABI from artifacts"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    artifacts_path = os.path.join(current_dir, "..", "artifacts", "contracts", 
                                 f"{contract_name}.sol", f"{contract_name}.json")
    
    logging.info(f"Loading ABI from: {artifacts_path}")
    try:
        with open(artifacts_path) as f:
            contract_json = json.load(f)
            return contract_json["abi"]
    except Exception as e:
        logging.error(f"Error loading ABI: {str(e)}")
        raise

def debug_position_creation():
    """Debug position creation issues"""
    w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
    account = Account.from_key(PRIVATE_KEY)
    
    logging.info(f"Connected to network: {w3.is_connected()}")
    logging.info(f"Using account: {account.address}")
    
    # Load contract
    predictive_abi = load_contract_abi("PredictiveLiquidityManager")
    predictive = w3.eth.contract(
        address=PREDICTIVE_MANAGER_ADDRESS,
        abi=predictive_abi
    )
    
    try:
        # Get token details
        token0 = predictive.functions.token0().call()
        token1 = predictive.functions.token1().call()
        token0_decimals = predictive.functions.token0Decimals().call()
        token1_decimals = predictive.functions.token1Decimals().call()
        fee = predictive.functions.fee().call()
        tick_spacing = predictive.functions.tickSpacing().call()
        weth9 = predictive.functions.WETH9().call()
        
        logging.info("Contract configuration:")
        logging.info(f"- Token0: {token0} (Decimals: {token0_decimals})")
        logging.info(f"- Token1: {token1} (Decimals: {token1_decimals})")
        logging.info(f"- Fee: {fee}")
        logging.info(f"- Tick Spacing: {tick_spacing}")
        logging.info(f"- WETH9 Address: {weth9}")
        
        # Verify our token addresses match
        if token0.lower() != USDC_ADDRESS.lower():
            logging.warning(f"USDC_ADDRESS {USDC_ADDRESS} doesn't match token0 {token0}")
        if token1.lower() != WETH_ADDRESS.lower():
            logging.warning(f"WETH_ADDRESS {WETH_ADDRESS} doesn't match token1 {token1}")
            
        # Check contract balances
        balances = predictive.functions.getContractBalances().call()
        logging.info(f"Contract balances:")
        logging.info(f"- Token0: {balances[0]}")
        logging.info(f"- Token1: {balances[1]}")
        logging.info(f"- WETH: {balances[2]}")
        
        # Check if there's an existing position
        position = predictive.functions.getActivePositionDetails().call()
        if position[4]:  # if position is active
            logging.info("Active position exists:")
            logging.info(f"- Token ID: {position[0]}")
            logging.info(f"- Liquidity: {position[1]}")
            logging.info(f"- Lower Tick: {position[2]}")
            logging.info(f"- Upper Tick: {position[3]}")
        else:
            logging.info("No active position exists")
        
        # Get current price info
        try:
            sqrt_price_x96, current_tick = predictive.functions._getCurrentSqrtPriceAndTick().call()
            logging.info(f"Current price info:")
            logging.info(f"- SqrtPriceX96: {sqrt_price_x96}")
            logging.info(f"- Current Tick: {current_tick}")
            
            # Try to get the actual price
            try:
                actual_price = predictive.functions._sqrtPriceX96ToPrice(sqrt_price_x96).call()
                logging.info(f"- Actual Price: {actual_price}")
            except Exception as e:
                logging.error(f"Error getting actual price: {str(e)}")
        except Exception as e:
            logging.error(f"Error getting current price info: {str(e)}")
        
        # Try to debug with the test price
        try:
            # Test with different simple price values
            for test_price in [1, 10, 100, 1000, 1500, 1538, 2000]:
                logging.info(f"Testing with simple price value: {test_price}")
                
                try:
                    logging.info(f"Simulating updatePredictionAndAdjust with price {test_price}...")
                    result = predictive.functions.updatePredictionAndAdjust(
                        test_price
                    ).call({
                        'from': account.address,
                        'gas': 5000000
                    })
                    logging.info(f"Simulation with price {test_price} SUCCESSFUL!")
                    logging.info(f"Found working price: {test_price}")
                    break  # Found a working price
                except Exception as e:
                    logging.error(f"Simulation with price {test_price} failed: {str(e)}")
            
        except Exception as e:
            logging.error(f"Error in price testing: {str(e)}")
        
        # Check pool address
        try:
            pool_address = predictive.functions.getPoolAddress().call()
            logging.info(f"Pool address: {pool_address}")
        except Exception as e:
            logging.error(f"Error getting pool address: {str(e)}")
            
    except Exception as e:
        logging.error(f"General error: {str(e)}")

if __name__ == "__main__":
    logging.info(f"Starting debug at {datetime.now()}")
    debug_position_creation()
    logging.info(f"Debug completed at {datetime.now()}") 