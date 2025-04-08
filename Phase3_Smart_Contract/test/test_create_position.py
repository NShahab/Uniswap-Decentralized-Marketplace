import os
import json
import requests
import time
import argparse
import csv
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
import logging
from datetime import datetime
from web3.exceptions import TimeExhausted, ContractLogicError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('position_creation.log'),
        logging.FileHandler('transaction_output.log'),  # Additional log file for outputs
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()

# Network settings
SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
PREDICTION_API_URL = os.getenv("PREDICTION_API_URL")

# Contract addresses
PREDICTIVE_MANAGER_ADDRESS = os.getenv("PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS")
USDC_ADDRESS = os.getenv("USDC_ADDRESS")
WETH_ADDRESS = os.getenv("WETH_ADDRESS")

# Setup separate logger for outputs
output_logger = logging.getLogger('output')
output_handler = logging.FileHandler('transaction_output.log')
output_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
output_logger.addHandler(output_handler)
output_logger.setLevel(logging.INFO)

logging.info(f"Loaded environment: RPC URL: {SEPOLIA_RPC_URL[:20]}..., API URL: {PREDICTION_API_URL}")
logging.info(f"Contract address: {PREDICTIVE_MANAGER_ADDRESS}")
logging.info(f"Token addresses - USDC: {USDC_ADDRESS}, WETH: {WETH_ADDRESS}")

def load_contract_abi(contract_name):
    """Load contract ABI from artifacts"""
    # Get the directory of the current script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Navigate to the artifacts directory from the current script location
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

def get_predicted_price():
    """Get predicted price from API"""
    try:
        logging.info(f"Fetching price prediction from API: {PREDICTION_API_URL}")
        output_logger.info(f"Fetching price prediction from API: {PREDICTION_API_URL}")
        
        response = requests.get(PREDICTION_API_URL)
        response.raise_for_status()
        data = response.json()
        predicted_price = data.get('predicted_price')
        if predicted_price is None:
            raise ValueError("No predicted price in API response")
        
        logging.info(f"Received predicted price from API: {predicted_price}")
        output_logger.info(f"Received predicted price from API: {predicted_price}")
        return predicted_price
    except Exception as e:
        logging.error(f"Error fetching prediction: {str(e)}")
        output_logger.error(f"Error fetching prediction: {str(e)}")
        # Return a fallback value
        fallback_price = 1538.0
        logging.warning(f"Using fallback price: {fallback_price}")
        output_logger.warning(f"Using fallback price: {fallback_price}")
        return fallback_price

def send_tokens_to_contract():
    """Send USDC and ETH to the contract"""
    w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
    account = Account.from_key(PRIVATE_KEY)
    
    # Ensure required addresses are set
    if not USDC_ADDRESS:
        logging.error("USDC_ADDRESS is not set in .env file")
        raise ValueError("USDC_ADDRESS is required")
    
    if not WETH_ADDRESS:
        logging.error("WETH_ADDRESS is not set in .env file")
        raise ValueError("WETH_ADDRESS is required")
    
    logging.info("Preparing to send tokens to contract...")
    output_logger.info("=== Starting token transfer to contract ===")
    
    # Load contract ABI to check token0 and token1 addresses
    try:
        predictive_abi = load_contract_abi("PredictiveLiquidityManager")
        predictive = w3.eth.contract(
            address=PREDICTIVE_MANAGER_ADDRESS,
            abi=predictive_abi
        )
        
        # Get token0 and token1 from contract
        token0_address = predictive.functions.token0().call()
        token1_address = predictive.functions.token1().call()
        logging.info(f"Contract token addresses - Token0: {token0_address}, Token1: {token1_address}")
        output_logger.info(f"Contract token addresses - Token0: {token0_address}, Token1: {token1_address}")
        
        # Check if our addresses match what's in the contract
        if token0_address.lower() != USDC_ADDRESS.lower() and token1_address.lower() != USDC_ADDRESS.lower():
            logging.warning(f"USDC_ADDRESS {USDC_ADDRESS} does not match either token0 or token1 in the contract")
            output_logger.warning(f"USDC_ADDRESS {USDC_ADDRESS} does not match either token0 or token1 in the contract")
        
        if token0_address.lower() != WETH_ADDRESS.lower() and token1_address.lower() != WETH_ADDRESS.lower():
            logging.warning(f"WETH_ADDRESS {WETH_ADDRESS} does not match either token0 or token1 in the contract")
            output_logger.warning(f"WETH_ADDRESS {WETH_ADDRESS} does not match either token0 or token1 in the contract")
    except Exception as e:
        logging.error(f"Error checking token addresses: {str(e)}")
        output_logger.error(f"Error checking token addresses: {str(e)}")
    
    # 1. Convert ETH to WETH first
    eth_amount = w3.to_wei(0.01, 'ether')  # 0.01 ETH as an example
    
    # WETH ABI for deposit function
    weth_abi = [
        {
            "constant": False,
            "inputs": [],
            "name": "deposit",
            "outputs": [],
            "payable": True,
            "stateMutability": "payable",
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [{"name": "owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function"
        },
        {
            "constant": False,
            "inputs": [
                {"name": "dst", "type": "address"},
                {"name": "wad", "type": "uint256"}
            ],
            "name": "transfer",
            "outputs": [{"name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function"
        },
        {
            "constant": False,
            "inputs": [
                {"name": "guy", "type": "address"},
                {"name": "wad", "type": "uint256"}
            ],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function"
        }
    ]
    
    weth_contract = w3.eth.contract(address=WETH_ADDRESS, abi=weth_abi)
    
    # Check initial WETH balance
    initial_weth = weth_contract.functions.balanceOf(account.address).call()
    logging.info(f"Initial WETH balance: {w3.from_wei(initial_weth, 'ether')} WETH")
    output_logger.info(f"Initial WETH balance: {w3.from_wei(initial_weth, 'ether')} WETH")

    # Convert ETH to WETH by calling deposit
    logging.info(f"Converting {w3.from_wei(eth_amount, 'ether')} ETH to WETH...")
    output_logger.info(f"Converting {w3.from_wei(eth_amount, 'ether')} ETH to WETH...")
    
    weth_tx = weth_contract.functions.deposit().build_transaction({
        'from': account.address,
        'value': eth_amount,
        'gas': 100000,
        'gasPrice': w3.to_wei(20, 'gwei'),
        'nonce': w3.eth.get_transaction_count(account.address),
    })
    
    # Sign and send WETH deposit transaction
    signed_weth_tx = w3.eth.account.sign_transaction(weth_tx, PRIVATE_KEY)
    weth_tx_hash = w3.eth.send_raw_transaction(signed_weth_tx.raw_transaction)
    logging.info(f"WETH deposit transaction sent. Hash: {weth_tx_hash.hex()}")
    output_logger.info(f"WETH deposit transaction sent. Hash: {weth_tx_hash.hex()}")
    
    # Wait for WETH deposit to be confirmed
    try:
        logging.info("Waiting for WETH deposit confirmation...")
        w3.eth.wait_for_transaction_receipt(weth_tx_hash, timeout=120)
        
        # Check new WETH balance
        new_weth = weth_contract.functions.balanceOf(account.address).call()
        logging.info(f"New WETH balance: {w3.from_wei(new_weth, 'ether')} WETH")
        output_logger.info(f"New WETH balance: {w3.from_wei(new_weth, 'ether')} WETH")
        
        # Approve WETH spending by the contract before sending
        logging.info(f"Approving contract to spend {w3.from_wei(eth_amount, 'ether')} WETH...")
        output_logger.info(f"Approving contract to spend {w3.from_wei(eth_amount, 'ether')} WETH...")
        
        weth_approve_tx = weth_contract.functions.approve(
            PREDICTIVE_MANAGER_ADDRESS,
            eth_amount
        ).build_transaction({
            'from': account.address,
            'gas': 100000,
            'gasPrice': w3.to_wei(20, 'gwei'),
            'nonce': w3.eth.get_transaction_count(account.address),
        })
        
        # Sign and send WETH approve transaction
        signed_weth_approve_tx = w3.eth.account.sign_transaction(weth_approve_tx, PRIVATE_KEY)
        weth_approve_hash = w3.eth.send_raw_transaction(signed_weth_approve_tx.raw_transaction)
        logging.info(f"WETH approval transaction sent. Hash: {weth_approve_hash.hex()}")
        output_logger.info(f"WETH approval transaction sent. Hash: {weth_approve_hash.hex()}")
        
        # Wait for approval to be confirmed
        logging.info("Waiting for WETH approval confirmation...")
        w3.eth.wait_for_transaction_receipt(weth_approve_hash, timeout=120)
        
        # Send WETH to contract
        logging.info(f"Sending {w3.from_wei(eth_amount, 'ether')} WETH to contract...")
        output_logger.info(f"Sending {w3.from_wei(eth_amount, 'ether')} WETH to contract...")
        
        weth_transfer_tx = weth_contract.functions.transfer(
            PREDICTIVE_MANAGER_ADDRESS,
            eth_amount
        ).build_transaction({
            'from': account.address,
            'gas': 100000,
            'gasPrice': w3.to_wei(20, 'gwei'),
            'nonce': w3.eth.get_transaction_count(account.address),
        })
        
        # Sign and send WETH transfer transaction
        signed_weth_transfer_tx = w3.eth.account.sign_transaction(weth_transfer_tx, PRIVATE_KEY)
        weth_transfer_hash = w3.eth.send_raw_transaction(signed_weth_transfer_tx.raw_transaction)
        logging.info(f"WETH transfer transaction sent. Hash: {weth_transfer_hash.hex()}")
        output_logger.info(f"WETH transfer transaction sent. Hash: {weth_transfer_hash.hex()}")
        
        # Wait for WETH transfer to be confirmed
        logging.info("Waiting for WETH transfer confirmation...")
        w3.eth.wait_for_transaction_receipt(weth_transfer_hash, timeout=120)
        
    except Exception as e:
        logging.error(f"Error with WETH deposit or transfer: {str(e)}")
        output_logger.error(f"Error with WETH deposit or transfer: {str(e)}")
        return False
    
    # 2. Send USDC to contract
    # Load USDC contract
    erc20_abi = [
        {
            "constant": False,
            "inputs": [
                {"name": "_to", "type": "address"},
                {"name": "_value", "type": "uint256"}
            ],
            "name": "transfer",
            "outputs": [{"name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function"
        },
        {
            "constant": False,
            "inputs": [
                {"name": "_spender", "type": "address"},
                {"name": "_value", "type": "uint256"}
            ],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function"
        }
    ]
    
    usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=erc20_abi)
    
    # Check USDC balance
    usdc_balance = usdc_contract.functions.balanceOf(account.address).call()
    usdc_amount = 10 * (10 ** 6)  # 10 USDC (assuming USDC has 6 decimals)
    
    logging.info(f"USDC balance: {usdc_balance / (10 ** 6)} USDC")
    output_logger.info(f"USDC balance: {usdc_balance / (10 ** 6)} USDC")
    
    if usdc_balance < usdc_amount:
        logging.error(f"Insufficient USDC balance. Need {usdc_amount / (10 ** 6)} USDC.")
        output_logger.error(f"Insufficient USDC balance. Need {usdc_amount / (10 ** 6)} USDC.")
        return False
    
    # Approve USDC spending by the contract before sending
    logging.info(f"Approving contract to spend {usdc_amount / (10 ** 6)} USDC...")
    output_logger.info(f"Approving contract to spend {usdc_amount / (10 ** 6)} USDC...")
    
    usdc_approve_tx = usdc_contract.functions.approve(
        PREDICTIVE_MANAGER_ADDRESS,
        usdc_amount
    ).build_transaction({
        'from': account.address,
        'gas': 100000,
        'gasPrice': w3.to_wei(20, 'gwei'),
        'nonce': w3.eth.get_transaction_count(account.address),
    })
    
    # Sign and send USDC approve transaction
    signed_usdc_approve_tx = w3.eth.account.sign_transaction(usdc_approve_tx, PRIVATE_KEY)
    usdc_approve_hash = w3.eth.send_raw_transaction(signed_usdc_approve_tx.raw_transaction)
    logging.info(f"USDC approval transaction sent. Hash: {usdc_approve_hash.hex()}")
    output_logger.info(f"USDC approval transaction sent. Hash: {usdc_approve_hash.hex()}")
    
    # Wait for approval to be confirmed
    logging.info("Waiting for USDC approval confirmation...")
    w3.eth.wait_for_transaction_receipt(usdc_approve_hash, timeout=120)
    
    # Send USDC
    logging.info(f"Sending {usdc_amount / (10 ** 6)} USDC to contract...")
    output_logger.info(f"Sending {usdc_amount / (10 ** 6)} USDC to contract")
    
    usdc_tx = usdc_contract.functions.transfer(
        PREDICTIVE_MANAGER_ADDRESS, 
        usdc_amount
    ).build_transaction({
        'from': account.address,
        'gas': 100000,
        'gasPrice': w3.to_wei(20, 'gwei'),
        'nonce': w3.eth.get_transaction_count(account.address),
    })
    
    # Sign and send USDC transaction
    signed_usdc_tx = w3.eth.account.sign_transaction(usdc_tx, PRIVATE_KEY)
    usdc_tx_hash = w3.eth.send_raw_transaction(signed_usdc_tx.raw_transaction)
    logging.info(f"USDC transaction sent. Hash: {usdc_tx_hash.hex()}")
    output_logger.info(f"USDC transaction sent. Hash: {usdc_tx_hash.hex()}")
    
    # Wait for USDC transfer to be confirmed
    logging.info("Waiting for USDC transfer confirmation...")
    w3.eth.wait_for_transaction_receipt(usdc_tx_hash, timeout=120)
    
    output_logger.info("=== Token transfer to contract completed successfully ===")
    return True

def debug_transaction(w3, contract, account_address, price_in_wei):
    """Simulate the transaction to identify potential errors before sending it"""
    logging.info("Simulating transaction before sending...")
    output_logger.info("Simulating transaction before sending...")
    
    try:
        # Try calling the function locally first to check for errors
        contract.functions.updatePredictionAndAdjust(
            price_in_wei
        ).call({
            'from': account_address,
            'gas': 5000000
        })
        logging.info("Simulation successful! Transaction should work.")
        output_logger.info("Simulation successful! Transaction should work.")
        return True
    except ContractLogicError as e:
        error_msg = str(e)
        logging.error(f"Simulation failed with error: {error_msg}")
        output_logger.error(f"Simulation failed with error: {error_msg}")
        
        # Try to extract revert reason from the error message
        if "revert" in error_msg.lower():
            # Common error patterns
            if "insufficient liquidity" in error_msg.lower():
                suggestion = "The pool might not have enough liquidity. Try with a smaller amount or a different price range."
            elif "price out of range" in error_msg.lower() or "tick" in error_msg.lower():
                suggestion = "The predicted price might be outside the acceptable range for the pool."
            elif "slippage" in error_msg.lower():
                suggestion = "Increase slippage tolerance or try a smaller amount."
            elif "balance" in error_msg.lower() or "allowance" in error_msg.lower():
                suggestion = "Check token balances and allowances. Make sure the contract has enough tokens."
            else:
                suggestion = "Check contract parameters and try again with different values."
                
            logging.error(f"Suggestion: {suggestion}")
            output_logger.error(f"Suggestion: {suggestion}")
        return False
    except Exception as e:
        logging.error(f"Simulation failed with unknown error: {str(e)}")
        output_logger.error(f"Simulation failed with unknown error: {str(e)}")
        return False

def check_pool_and_debug(w3, predictive, predicted_price):
    """Check pool settings and debug possible transaction failure reasons"""
    logging.info("Checking pool settings and debugging...")
    output_logger.info("Checking pool settings and debugging...")
    
    try:
        # Get contract token decimals
        try:
            token0_address = predictive.functions.token0().call()
            token1_address = predictive.functions.token1().call()
            token0_decimals = predictive.functions.token0Decimals().call()
            token1_decimals = predictive.functions.token1Decimals().call()
            logging.info(f"Token decimals - Token0: {token0_decimals}, Token1: {token1_decimals}")
            output_logger.info(f"Token decimals - Token0: {token0_decimals}, Token1: {token1_decimals}")
        except Exception as e:
            logging.error(f"Error getting token decimals: {str(e)}")
            token0_decimals = 6  # Default USDC
            token1_decimals = 18  # Default WETH
            logging.info(f"Using default decimals - Token0: {token0_decimals}, Token1: {token1_decimals}")
        
        # Convert predicted price to contract format (similar to _priceToTick in contract)
        # In contract: uint256 ratioX192 = numerator.mul(1 << 192).div(denominator);
        # Here we need to properly scale the price based on token decimals
        
        # Convert predicted price to the expected format
        # According to the contract, the price should be expressed as:
        # price = (token1/token0) * 10^(token0_decimals - token1_decimals) * 1e18
        
        # Start with a simple scaling
        contract_price = int(predicted_price * (10 ** 18))
        
        # Try to get pool address
        pool_address = predictive.functions.getPoolAddress().call()
        logging.info(f"Pool address: {pool_address}")
        output_logger.info(f"Pool address: {pool_address}")
        
        # Try to get fee
        fee = predictive.functions.fee().call()
        logging.info(f"Pool fee: {fee}")
        output_logger.info(f"Pool fee: {fee}")
        
        # Try to get tick spacing
        tick_spacing = predictive.functions.tickSpacing().call()
        logging.info(f"Tick spacing: {tick_spacing}")
        output_logger.info(f"Tick spacing: {tick_spacing}")
        
        # Try to get current active position to understand the tick range
        try:
            position = predictive.functions.getActivePositionDetails().call()
            if position[4]:  # If position is active
                lower_tick = position[2]
                upper_tick = position[3]
                logging.info(f"Active position ticks: [{lower_tick}, {upper_tick}]")
                output_logger.info(f"Active position ticks: [{lower_tick}, {upper_tick}]")
                
                # Based on the logs, we see when price_in_wei=1, we get ticks around -138000
                # Since this works, we'll use this value
                final_price = 1  # This seems to work reliably with the contract
                
                logging.info(f"Using price value 1 which is known to work with the contract")
                output_logger.info(f"Using price value 1 which is known to work with the contract")
                return True, final_price, contract_price
        except Exception as e:
            logging.error(f"Error checking active position: {str(e)}")
            output_logger.error(f"Error checking active position: {str(e)}")
        
        # If all else fails, use 1 which works based on logs
        logging.info("Using price value 1 which is known to work with contract")
        output_logger.info("Using price value 1 which is known to work with contract")
        return True, 1, contract_price
    except Exception as e:
        logging.error(f"Error checking pool: {str(e)}")
        output_logger.error(f"Error checking pool: {str(e)}")
        return False, 1, int(predicted_price * (10 ** 18))

def create_position():
    """Create a new position using predicted price"""
    try:
        # Setup web3
        w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
        account = Account.from_key(PRIVATE_KEY)
        
        # Load contract
        predictive_abi = load_contract_abi("PredictiveLiquidityManager")
        predictive = w3.eth.contract(
            address=PREDICTIVE_MANAGER_ADDRESS,
            abi=predictive_abi
        )
        
        output_logger.info("=== Starting new position creation ===")
        
        # Check contract balances first
        balances = predictive.functions.getContractBalances().call()
        logging.info(f"Contract balances before creating position:")
        logging.info(f"- Token0: {balances[0]}")
        logging.info(f"- Token1: {balances[1]}")
        logging.info(f"- WETH: {balances[2]}")
        
        output_logger.info(f"Contract balances before creating position:")
        output_logger.info(f"- Token0: {balances[0]}")
        output_logger.info(f"- Token1: {balances[1]}")
        output_logger.info(f"- WETH: {balances[2]}")
        
        # Send tokens to contract if needed
        if balances[0] == 0 or balances[1] == 0:
            logging.info("Contract needs tokens. Sending USDC and ETH...")
            output_logger.info("Contract needs tokens. Sending USDC and ETH...")
            
            if not send_tokens_to_contract():
                logging.error("Failed to send tokens to contract.")
                output_logger.error("Failed to send tokens to contract.")
                return
            
            # Wait for token transfer transactions to be confirmed
            logging.info("Waiting for token transfers to be confirmed...")
            output_logger.info("Waiting for token transfers to be confirmed...")
            time.sleep(30)  # Wait 30 seconds for transactions to be confirmed
            
            # Verify balances after sending tokens
            balances = predictive.functions.getContractBalances().call()
            logging.info(f"Contract balances after sending tokens:")
            logging.info(f"- Token0: {balances[0]}")
            logging.info(f"- Token1: {balances[1]}")
            logging.info(f"- WETH: {balances[2]}")
            
            output_logger.info(f"Contract balances after sending tokens:")
            output_logger.info(f"- Token0: {balances[0]}")
            output_logger.info(f"- Token1: {balances[1]}")
            output_logger.info(f"- WETH: {balances[2]}")
        
        # Get predicted price from API
        predicted_price = get_predicted_price()
        logging.info(f"Received predicted price: {predicted_price}")
        output_logger.info(f"Received predicted price: {predicted_price}")
        
        # Check if there's an existing position
        position = predictive.functions.getActivePositionDetails().call()
        if position[4]:  # if position is active
            logging.info("Active position exists:")
            logging.info(f"- Token ID: {position[0]}")
            logging.info(f"- Liquidity: {position[1]}")
            logging.info(f"- Lower Tick: {position[2]}")
            logging.info(f"- Upper Tick: {position[3]}")
            
            output_logger.info("Active position exists:")
            output_logger.info(f"- Token ID: {position[0]}")
            output_logger.info(f"- Liquidity: {position[1]}")
            output_logger.info(f"- Lower Tick: {position[2]}")
            output_logger.info(f"- Upper Tick: {position[3]}")
            
            # Here we will try to update the position with a new price
            logging.info("Attempting to update existing position with new predicted price...")
            output_logger.info("Attempting to update existing position with new predicted price...")
        
        # Prepare transaction
        if not position[4]:
            logging.info("No active position found. Creating new position...")
            output_logger.info("No active position found. Creating new position...")
        
        # استفاده از قیمت معکوس برای قرارداد
        # در Uniswap، قیمت به صورت نسبت token1/token0 نمایش داده می‌شود
        # اگر قیمت پیش‌بینی ما ETH/USDC است (مثلاً 1537 USDC برای هر ETH)،
        # باید معکوس آن را به قرارداد بدهیم (USDC/ETH یا 1/1537 = 0.00065)
        
        # محاسبه معکوس قیمت
        inverse_price = 1.0 / float(predicted_price)
        
        # برای اطمینان از دقت، مقدار را در 10^18 ضرب می‌کنیم (برای تبدیل به Wei)
        price_in_wei = int(inverse_price * (10 ** 18))
        
        logging.info(f"Original predicted price: {predicted_price} (ETH/USDC)")
        logging.info(f"Inverse price: {inverse_price} (USDC/ETH)")
        logging.info(f"Price in Wei format: {price_in_wei}")
        
        output_logger.info(f"Original predicted price: {predicted_price} (ETH/USDC)")
        output_logger.info(f"Inverse price: {inverse_price} (USDC/ETH)")
        output_logger.info(f"Price in Wei format: {price_in_wei}")
        
        # اطمینان از اینکه قیمت از صفر بزرگتر است
        if price_in_wei <= 0:
            price_in_wei = 1
            logging.warning(f"Invalid price calculation! Using default value: {price_in_wei}")
            output_logger.warning(f"Invalid price calculation! Using default value: {price_in_wei}")
        
        original_predicted_price = predicted_price  # Save for logging
        
        # Build and send transaction
        try:
            transaction = predictive.functions.updatePredictionAndAdjust(
                price_in_wei
            ).build_transaction({
                'from': account.address,
                'gas': 5000000,  # Increased gas limit to 5 million
                'gasPrice': w3.to_wei(20, 'gwei'),  # Increased gas price to 20 Gwei
                'nonce': w3.eth.get_transaction_count(account.address),
            })
            
            # Sign and send transaction
            signed_txn = w3.eth.account.sign_transaction(transaction, PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            
            logging.info(f"Transaction sent. Hash: {tx_hash.hex()}")
            output_logger.info(f"Transaction sent. Hash: {tx_hash.hex()}")
        except Exception as tx_error:
            logging.error(f"Error sending transaction: {str(tx_error)}")
            output_logger.error(f"Error sending transaction: {str(tx_error)}")
            return False
        
        # Wait for receipt
        try:
            logging.info("Waiting for transaction confirmation...")
            output_logger.info("Waiting for transaction confirmation...")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)  # Increased timeout to 5 minutes
            if receipt['status'] == 1:
                logging.info("Position created successfully!")
                output_logger.info("Position created successfully!")
                
                new_position = predictive.functions.getActivePositionDetails().call()
                logging.info("New position details:")
                logging.info(f"- Token ID: {new_position[0]}")
                logging.info(f"- Liquidity: {new_position[1]}")
                logging.info(f"- Lower Tick: {new_position[2]}")
                logging.info(f"- Upper Tick: {new_position[3]}")
                
                output_logger.info("New position details:")
                output_logger.info(f"- Token ID: {new_position[0]}")
                output_logger.info(f"- Liquidity: {new_position[1]}")
                output_logger.info(f"- Lower Tick: {new_position[2]}")
                output_logger.info(f"- Upper Tick: {new_position[3]}")

                # Get more details from transaction receipt and logs
                gas_used = receipt['gasUsed']
                gas_price = w3.eth.get_transaction(tx_hash)['gasPrice']
                total_gas_cost = gas_used * gas_price
                total_eth_cost = float(w3.from_wei(total_gas_cost, 'ether'))
                
                # Get current price from pool
                try:
                    # First try with _getCurrentSqrtPriceAndTick
                    try:
                        current_price = predictive.functions._getCurrentSqrtPriceAndTick().call()[0]
                        logging.info(f"Current pool price: {current_price}")
                        output_logger.info(f"Current pool price: {current_price}")
                    except Exception as e1:
                        # If that fails, try alternative methods
                        logging.warning(f"Could not get price with _getCurrentSqrtPriceAndTick: {str(e1)}")
                        try:
                            # Try to get pool address
                            pool_address = predictive.functions.getPoolAddress().call()
                            logging.info(f"Pool address for price check: {pool_address}")
                            
                            # Use direct observation from contract instead
                            current_position = predictive.functions.getActivePositionDetails().call()
                            logging.info(f"Successfully created position with ID: {current_position[0]}")
                            output_logger.info(f"Successfully created position with ID: {current_position[0]}")
                        except Exception as e2:
                            logging.warning(f"Could not get alternative price info: {str(e2)}")
                except Exception as e:
                    logging.warning(f"Could not get price information: {str(e)}")
                    output_logger.warning(f"Could not get price information: {str(e)}")
                
                # Save final transaction result with all details
                final_result = {
                    "timestamp": datetime.now().isoformat(),
                    "transaction_hash": tx_hash.hex(),
                    "predicted_price": {
                        "original": float(original_predicted_price),
                        "used_value": price_in_wei
                    },
                    "inverse_price": float(inverse_price) if 'inverse_price' in locals() else None,
                    "gas_used": gas_used,
                    "gas_price": gas_price,
                    "total_gas_cost_eth": total_eth_cost,
                    "position": {
                        "token_id": int(new_position[0]),
                        "liquidity": int(new_position[1]),
                        "lower_tick": int(new_position[2]),
                        "upper_tick": int(new_position[3]),
                        "is_active": bool(new_position[4])
                    }
                }
                
                # Log the final result in both loggers
                logging.info(f"FINAL RESULT: {json.dumps(final_result, indent=2)}")
                output_logger.info(f"FINAL RESULT: {json.dumps(final_result, indent=2)}")
                
                # Save the result to a separate JSON file that can be easily read by other scripts
                result_dir = os.path.dirname(os.path.abspath(__file__))
                parent_dir = os.path.abspath(os.path.join(result_dir, ".."))
                result_file = os.path.join(parent_dir, "position_results.json")
                csv_file = os.path.join(parent_dir, "position_results.csv")
                
                # Also save a copy in the current working directory
                current_dir = os.getcwd()
                current_csv_file = os.path.join(current_dir, "position_results.csv")
                
                logging.info(f"Current working directory: {current_dir}")
                logging.info(f"Result directory: {result_dir}")
                logging.info(f"Parent directory: {parent_dir}")
                logging.info(f"Full JSON path: {os.path.abspath(result_file)}")
                logging.info(f"Full CSV path: {os.path.abspath(csv_file)}")
                logging.info(f"Current dir CSV path: {os.path.abspath(current_csv_file)}")
                
                try:
                    # Read existing results if file exists
                    if os.path.exists(result_file):
                        with open(result_file, 'r') as f:
                            results = json.load(f)
                    else:
                        results = []
                    
                    # Add new result
                    results.append(final_result)
                    
                    # Write back to JSON file
                    with open(result_file, 'w') as f:
                        json.dump(results, f, indent=2)
                        
                    logging.info(f"Result saved to {result_file}")
                    output_logger.info(f"Result saved to {result_file}")
                    
                    # Also save to CSV file
                    # Define CSV columns
                    csv_columns = [
                        'timestamp', 
                        'transaction_hash', 
                        'original_predicted_price', 
                        'used_price_value',
                        'inverse_price', 
                        'gas_used', 
                        'gas_price', 
                        'total_gas_cost_eth',
                        'token_id',
                        'liquidity',
                        'lower_tick',
                        'upper_tick',
                        'is_active'
                    ]
                    
                    # Check if CSV exists
                    csv_exists = os.path.exists(csv_file)
                    logging.info(f"CSV file exists: {csv_exists}")
                    
                    try:
                        # First make sure the directory exists
                        os.makedirs(os.path.dirname(os.path.abspath(csv_file)), exist_ok=True)
                        
                        # Open CSV in append mode
                        with open(csv_file, 'a', newline='') as csvfile:
                            writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
                            
                            # Write header only if file is new
                            if not csv_exists:
                                writer.writeheader()
                                logging.info("Wrote CSV header")
                            
                            # Flatten the data for CSV format
                            csv_data = {
                                'timestamp': final_result['timestamp'],
                                'transaction_hash': final_result['transaction_hash'],
                                'original_predicted_price': final_result['predicted_price']['original'],
                                'used_price_value': final_result['predicted_price']['used_value'],
                                'inverse_price': final_result['inverse_price'],
                                'gas_used': final_result['gas_used'],
                                'gas_price': final_result['gas_price'],
                                'total_gas_cost_eth': final_result['total_gas_cost_eth'],
                                'token_id': final_result['position']['token_id'],
                                'liquidity': final_result['position']['liquidity'],
                                'lower_tick': final_result['position']['lower_tick'],
                                'upper_tick': final_result['position']['upper_tick'],
                                'is_active': final_result['position']['is_active']
                            }
                            
                            # Write to CSV
                            writer.writerow(csv_data)
                            logging.info("Wrote CSV row data")
                        
                        logging.info(f"Result also saved to CSV file: {csv_file}")
                        output_logger.info(f"Result also saved to CSV file: {csv_file}")
                        
                        # Also save a copy in the current working directory
                        try:
                            with open(current_csv_file, 'a', newline='') as current_csvfile:
                                current_writer = csv.DictWriter(current_csvfile, fieldnames=csv_columns)
                                
                                # Write header only if file is new
                                if not os.path.exists(current_csv_file) or os.path.getsize(current_csv_file) == 0:
                                    current_writer.writeheader()
                                
                                # Write data
                                current_writer.writerow(csv_data)
                            
                            logging.info(f"Also saved a copy to current directory: {current_csv_file}")
                            output_logger.info(f"Also saved a copy to current directory: {current_csv_file}")
                            
                            # Try to determine if file is actually on disk and readable
                            if os.path.exists(current_csv_file):
                                file_size = os.path.getsize(current_csv_file)
                                logging.info(f"Current dir CSV file exists, size: {file_size} bytes")
                                
                                # Try to read back a few lines to verify
                                with open(current_csv_file, 'r') as f:
                                    lines = f.readlines()[:5]  # Read up to 5 lines
                                    logging.info(f"CSV file contains {len(lines)} lines (showing up to 5)")
                                    for line in lines:
                                        logging.info(f"CSV line: {line.strip()}")
                            else:
                                logging.error(f"Current dir CSV file still doesn't exist after writing!")
                        except Exception as current_csv_error:
                            logging.error(f"Error saving to current directory CSV: {str(current_csv_error)}")
                    except Exception as csv_error:
                        logging.error(f"Error saving to CSV: {str(csv_error)}")
                        import traceback
                        logging.error(traceback.format_exc())
                except Exception as e:
                    logging.error(f"Error saving result to file: {str(e)}")
                    output_logger.error(f"Error saving result to file: {str(e)}")
            else:
                logging.error("Transaction failed!")
                output_logger.error("Transaction failed!")
                
                # Try to get detailed error information
                try:
                    tx = w3.eth.get_transaction(tx_hash)
                    tx_data = {
                        "hash": tx_hash.hex(),
                        "from": tx["from"],
                        "to": tx["to"],
                        "gas": tx["gas"],
                        "gasPrice": tx["gasPrice"],
                        "nonce": tx["nonce"],
                        "blockNumber": receipt["blockNumber"],
                        "blockHash": receipt["blockHash"],
                        "status": receipt["status"]
                    }
                    
                    logging.error(f"Transaction details: {json.dumps(tx_data, indent=2)}")
                    output_logger.error(f"Transaction details: {json.dumps(tx_data, indent=2)}")
                except Exception as debug_error:
                    logging.error(f"Error debugging transaction: {str(debug_error)}")
                    output_logger.error(f"Error debugging transaction: {str(debug_error)}")
        except TimeExhausted:
            logging.error("Transaction not confirmed within the expected time. Still pending...")
            output_logger.error("Transaction not confirmed within the expected time. Still pending...")
        
        output_logger.info("=== Position creation operation completed ===")
        return True
    except Exception as e:
        logging.error(f"Error creating position: {str(e)}")
        output_logger.error(f"Error creating position: {str(e)}")
        return False

def main():
    """Main function to execute the position creation process"""
    logging.info(f"Starting position creation process at {datetime.now()}")
    output_logger.info(f"=== Starting position creation process at {datetime.now()} ===")
    
    # Check if required environment variables are set
    if not SEPOLIA_RPC_URL:
        logging.error("SEPOLIA_RPC_URL is not set in .env file")
        output_logger.error("SEPOLIA_RPC_URL is not set in .env file")
        return
    if not PRIVATE_KEY:
        logging.error("PRIVATE_KEY is not set in .env file")
        output_logger.error("PRIVATE_KEY is not set in .env file")
        return
    if not PREDICTIVE_MANAGER_ADDRESS:
        logging.error("PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS is not set in .env file")
        output_logger.error("PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS is not set in .env file")
        return
    if not PREDICTION_API_URL:
        logging.error("PREDICTION_API_URL is not set in .env file")
        output_logger.error("PREDICTION_API_URL is not set in .env file")
        return
    if not USDC_ADDRESS:
        logging.error("USDC_ADDRESS is not set in .env file")
        output_logger.error("USDC_ADDRESS is not set in .env file")
        return
    if not WETH_ADDRESS:
        logging.error("WETH_ADDRESS is not set in .env file")
        output_logger.error("WETH_ADDRESS is not set in .env file")
        return
    
    try:
        create_position()
        logging.info("Position creation process completed successfully")
        output_logger.info("=== Position creation process completed successfully ===")
    except Exception as e:
        logging.error(f"Error in position creation process: {str(e)}")
        output_logger.error(f"Error in position creation process: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        output_logger.error(traceback.format_exc())

def run_scheduled(interval_hours=1):
    """Run the position creation process at regular intervals"""
    logging.info(f"Starting scheduled job to run every {interval_hours} hour(s)")
    output_logger.info(f"Starting scheduled job to run every {interval_hours} hour(s)")
    
    try:
        main()  # Run once immediately
        
        seconds_between_runs = interval_hours * 60 * 60
        next_run_time = time.time() + seconds_between_runs
        
        while True:
            current_time = time.time()
            wait_time = next_run_time - current_time
            
            if wait_time > 0:
                logging.info(f"Waiting {wait_time:.2f} seconds until next run...")
                output_logger.info(f"Waiting {wait_time:.2f} seconds until next run...")
                try:
                    time.sleep(wait_time)
                except KeyboardInterrupt:
                    logging.info("Process terminated by user")
                    output_logger.info("Process terminated by user")
                    break
            
            main()  # Run the process
            next_run_time = time.time() + seconds_between_runs
    except KeyboardInterrupt:
        logging.info("Process terminated by user")
        output_logger.info("Process terminated by user")
    except Exception as e:
        logging.error(f"Error in scheduled process: {str(e)}")
        output_logger.error(f"Error in scheduled process: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        output_logger.error(traceback.format_exc())

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Run position creation process')
    parser.add_argument('--schedule', action='store_true', help='Run the process at regular intervals')
    parser.add_argument('--interval', type=float, default=1.0, help='Interval between runs in hours (default: 1.0)')
    args = parser.parse_args()
    
    if args.schedule:
        run_scheduled(interval_hours=args.interval)
    else:
        main()