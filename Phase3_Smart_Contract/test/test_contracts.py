import os
import json
from datetime import datetime
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('contract_tests.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()

# Sepolia network settings
SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

# Contract addresses
BASELINE_MINIMAL_ADDRESS = "0x1Ef926AA3Cb366FFcb925a98b24488cE6Ad6043C"
PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS = "0xe4CbeF27cebD83f1D6646BC73e22f06239451f0f"
TOKEN_MANAGER_OPTIMIZED_ADDRESS = "0x62C599020C08BD030e18653BA85B1D72dE9401Af"

# Web3 setup
w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
account = Account.from_key(PRIVATE_KEY)

def load_contract_abi(contract_name):
    """Load contract ABI from artifacts"""
    artifacts_path = f"artifacts/contracts/{contract_name}.sol/{contract_name}.json"
    with open(artifacts_path) as f:
        contract_json = json.load(f)
        return contract_json["abi"]

def test_baseline_minimal():
    """Test BaselineMinimal contract"""
    try:
        logging.info("=== Testing BaselineMinimal ===")
        
        # Load contract
        baseline_abi = load_contract_abi("BaselineMinimal")
        baseline = w3.eth.contract(address=BASELINE_MINIMAL_ADDRESS, abi=baseline_abi)
        
        # Test view functions
        owner = baseline.functions.owner().call()
        has_position = baseline.functions.hasPosition().call()
        current_token_id = baseline.functions.currentTokenId().call()
        
        logging.info(f"Contract owner: {owner}")
        logging.info(f"Has position: {has_position}")
        logging.info(f"Current token ID: {current_token_id}")
        
        if has_position:
            position = baseline.functions.getActivePositionDetails().call()
            logging.info(f"Active position details:")
            logging.info(f"- Token ID: {position[0]}")
            logging.info(f"- Liquidity: {position[1]}")
            logging.info(f"- Lower Tick: {position[2]}")
            logging.info(f"- Upper Tick: {position[3]}")
            logging.info(f"- Active: {position[4]}")
        
        return True
    except Exception as e:
        logging.error(f"Error in BaselineMinimal test: {str(e)}")
        return False

def test_predictive_manager():
    """Test PredictiveLiquidityManager contract"""
    try:
        logging.info("\n=== Testing PredictiveLiquidityManager ===")
        
        # Load contract
        predictive_abi = load_contract_abi("PredictiveLiquidityManager")
        predictive = w3.eth.contract(address=PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS, abi=predictive_abi)
        
        # Test view functions
        owner = predictive.functions.owner().call()
        logging.info(f"Contract owner: {owner}")
        
        # Get pool address
        pool_address = predictive.functions.getPoolAddress().call()
        logging.info(f"Pool address: {pool_address}")
        
        # Get contract balances
        balances = predictive.functions.getContractBalances().call()
        logging.info(f"Token0 balance: {balances[0]}")
        logging.info(f"Token1 balance: {balances[1]}")
        logging.info(f"WETH balance: {balances[2]}")
        
        # Get position details
        position = predictive.functions.getActivePositionDetails().call()
        logging.info(f"Position details:")
        logging.info(f"- Token ID: {position[0]}")
        logging.info(f"- Liquidity: {position[1]}")
        logging.info(f"- Lower Tick: {position[2]}")
        logging.info(f"- Upper Tick: {position[3]}")
        logging.info(f"- Active: {position[4]}")
        
        return True
    except Exception as e:
        logging.error(f"Error in PredictiveLiquidityManager test: {str(e)}")
        return False

def test_token_operations():
    """Test TokenOperationsManager contract"""
    try:
        logging.info("\n=== Testing TokenOperationsManager ===")
        
        # Load contract
        token_ops_abi = load_contract_abi("TokenOperationsManagerOptimized")
        token_ops = w3.eth.contract(address=TOKEN_MANAGER_OPTIMIZED_ADDRESS, abi=token_ops_abi)
        
        # Test view functions
        owner = token_ops.functions.owner().call()
        logging.info(f"Contract owner: {owner}")
        
        # Check contract ETH balance
        balance = w3.eth.get_balance(TOKEN_MANAGER_OPTIMIZED_ADDRESS)
        logging.info(f"Contract ETH balance: {w3.from_wei(balance, 'ether')} ETH")
        
        return True
    except Exception as e:
        logging.error(f"Error in TokenOperationsManager test: {str(e)}")
        return False

def main():
    """Main function"""
    logging.info(f"Starting contract tests at {datetime.now()}")
    logging.info(f"Test account address: {account.address}")
    
    # Test all contracts
    baseline_success = test_baseline_minimal()
    predictive_success = test_predictive_manager()
    token_ops_success = test_token_operations()
    
    # Show final results
    logging.info("\n=== Final Results ===")
    logging.info(f"BaselineMinimal: {'SUCCESS' if baseline_success else 'FAILED'}")
    logging.info(f"PredictiveLiquidityManager: {'SUCCESS' if predictive_success else 'FAILED'}")
    logging.info(f"TokenOperationsManager: {'SUCCESS' if token_ops_success else 'FAILED'}")

if __name__ == "__main__":
    main() 