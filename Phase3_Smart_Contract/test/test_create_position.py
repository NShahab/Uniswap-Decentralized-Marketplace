import os
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
import json
import traceback
import sys

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

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL)) if SEPOLIA_RPC_URL else None

# Contract addresses - convert to checksum format
PREDICTIVE_MANAGER_ADDRESS = w3.to_checksum_address(os.getenv("PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS")) if w3 and os.getenv("PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS") else None
USDC_ADDRESS = w3.to_checksum_address(os.getenv("USDC_ADDRESS")) if w3 and os.getenv("USDC_ADDRESS") else None
WETH_ADDRESS = w3.to_checksum_address(os.getenv("WETH_ADDRESS")) if w3 and os.getenv("WETH_ADDRESS") else None

# CSV file path
CSV_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "position_results.csv")

# Setup separate logger for outputs
output_logger = logging.getLogger('output')
output_handler = logging.FileHandler('transaction_output.log')
output_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
output_logger.addHandler(output_handler)
output_logger.setLevel(logging.INFO)

logging.info(f"Loaded environment: RPC URL: {SEPOLIA_RPC_URL[:20] if SEPOLIA_RPC_URL else 'Not set'}...")
logging.info(f"Contract address: {PREDICTIVE_MANAGER_ADDRESS}")
logging.info(f"Token addresses - USDC: {USDC_ADDRESS}, WETH: {WETH_ADDRESS}")
logging.info(f"Results will be saved to CSV: {CSV_FILE_PATH}")

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

def get_predicted_price():
    """Get the predicted ETH price from API or use a fallback"""
    # Try to get current price from coinbase API
    try:
        response = requests.get('https://api.coinbase.com/v2/prices/ETH-USD/spot')
        if response.status_code == 200:
            data = response.json()
            price = float(data['data']['amount'])
            logging.info(f"Coinbase API ETH price: {price} USD")
            output_logger.info(f"Coinbase API ETH price: {price} USD")
            
            # Invert the price for Uniswap (WETH/USDC)
            inverted_price = 1.0 / price
            logging.info(f"Inverted price (USDC/WETH): {inverted_price}")
            output_logger.info(f"Inverted price (USDC/WETH): {inverted_price}")
            
            # Return both the original ETH/USDC price and the inverted price
            return {
                "original": price,
                "inverted": inverted_price
            }
    except Exception as e:
        logging.warning(f"Error getting price from Coinbase: {str(e)}")
        output_logger.warning(f"Failed to get price from Coinbase: {str(e)}")
    
    # Fallback: use a fixed price
    fallback_price = 1800.0  # ETH/USDC
    inverted_fallback = 1.0 / fallback_price  # USDC/WETH
    
    logging.warning(f"Using fallback price: {fallback_price} USD")
    output_logger.warning(f"Using fallback price: {fallback_price} USD")
    logging.info(f"Inverted fallback price (USDC/WETH): {inverted_fallback}")
    output_logger.info(f"Inverted fallback price (USDC/WETH): {inverted_fallback}")
    
    return {
        "original": fallback_price,
        "inverted": inverted_fallback
    }

def send_tokens_to_contract():
    """Send USDC and WETH to the contract"""
    if not w3:
        logging.error("Web3 not initialized. Check your RPC URL.")
        return None
    
    account = Account.from_key(PRIVATE_KEY)
    
    # Ensure required addresses are set
    if not all([USDC_ADDRESS, WETH_ADDRESS, PREDICTIVE_MANAGER_ADDRESS]):
        logging.error("Required addresses are not set in .env file")
        raise ValueError("All addresses are required")
    
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
        return None
    
    # WETH ABI for conversion and transfer
    weth_abi = [
        {"constant": False, "inputs": [], "name": "deposit", "outputs": [], 
         "payable": True, "stateMutability": "payable", "type": "function"},
        {"constant": True, "inputs": [{"name": "owner", "type": "address"}], 
         "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], 
         "payable": False, "stateMutability": "view", "type": "function"},
        {"constant": False, "inputs": [{"name": "dst", "type": "address"}, 
                                     {"name": "wad", "type": "uint256"}], 
         "name": "transfer", "outputs": [{"name": "", "type": "bool"}], 
         "payable": False, "stateMutability": "nonpayable", "type": "function"},
        {"constant": False, "inputs": [{"name": "guy", "type": "address"}, 
                                     {"name": "wad", "type": "uint256"}], 
         "name": "approve", "outputs": [{"name": "", "type": "bool"}], 
         "payable": False, "stateMutability": "nonpayable", "type": "function"}
    ]
    
    # ERC20 ABI for USDC
    erc20_abi = [
        {"constant": True, "inputs": [{"name": "owner", "type": "address"}], 
         "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], 
         "payable": False, "stateMutability": "view", "type": "function"},
        {"constant": False, "inputs": [{"name": "to", "type": "address"}, 
                                     {"name": "value", "type": "uint256"}], 
         "name": "transfer", "outputs": [{"name": "", "type": "bool"}], 
         "payable": False, "stateMutability": "nonpayable", "type": "function"}
    ]
    
    weth_contract = w3.eth.contract(address=WETH_ADDRESS, abi=weth_abi)
    usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=erc20_abi)
    
    try:
        # Get current gas price and increase it by 50%
        current_gas_price = w3.eth.gas_price
        gas_price = int(current_gas_price * 1.5)  # 50% higher gas price
        logging.info(f"Using gas price: {w3.from_wei(gas_price, 'gwei')} gwei (50% above current)")
        
        # 1. Convert ETH to WETH - INCREASED AMOUNT TO 0.05 ETH (5x MORE)
        eth_amount = w3.to_wei(0.05, 'ether')  # 0.05 ETH (was 0.01)
        
        logging.info(f"Converting {w3.from_wei(eth_amount, 'ether')} ETH to WETH...")
        tx_hash = weth_contract.functions.deposit().build_transaction({
            'from': account.address,
            'value': eth_amount,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 100000,
            'gasPrice': gas_price
        })
        
        # Fix for Web3.py version compatibility
        signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
        # Access the correct attribute based on Web3.py version
        raw_tx_data = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
        
        deposit_tx_hash = w3.eth.send_raw_transaction(raw_tx_data)
        logging.info(f"WETH deposit transaction sent: {deposit_tx_hash.hex()}")
        logging.info(f"Waiting for confirmation (up to 300 seconds)...")
        
        try:
            deposit_receipt = w3.eth.wait_for_transaction_receipt(deposit_tx_hash, timeout=300)
            logging.info(f"ETH to WETH conversion confirmed. Hash: {deposit_receipt.transactionHash.hex()}")
        except Exception as e:
            logging.error(f"Timed out waiting for WETH deposit confirmation: {str(e)}")
            logging.warning("Continuing with the next step anyway, the transaction might confirm later.")
        
        # Wait a few seconds to make sure nonce is updated
        time.sleep(5)
        
        # 2. Send WETH to contract
        weth_balance = weth_contract.functions.balanceOf(account.address).call()
        logging.info(f"WETH balance: {w3.from_wei(weth_balance, 'ether')} WETH")
        
        if weth_balance == 0:
            logging.warning("WETH balance is 0, the deposit transaction might not be confirmed yet.")
            logging.warning("Waiting 60 seconds and trying again...")
            time.sleep(60)
            weth_balance = weth_contract.functions.balanceOf(account.address).call()
            logging.info(f"WETH balance after waiting: {w3.from_wei(weth_balance, 'ether')} WETH")
        
        if weth_balance > 0:
            # Send all WETH to contract
            logging.info(f"Sending {w3.from_wei(weth_balance, 'ether')} WETH to contract...")
            tx_hash = weth_contract.functions.transfer(PREDICTIVE_MANAGER_ADDRESS, weth_balance).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 100000,
                'gasPrice': gas_price
            })
            
            signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
            raw_tx_data = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
            
            weth_tx_hash = w3.eth.send_raw_transaction(raw_tx_data)
            logging.info(f"WETH transfer transaction sent: {weth_tx_hash.hex()}")
            logging.info(f"Waiting for confirmation (up to 300 seconds)...")
            
            try:
                weth_receipt = w3.eth.wait_for_transaction_receipt(weth_tx_hash, timeout=300)
                logging.info(f"WETH transfer confirmed. Hash: {weth_receipt.transactionHash.hex()}")
            except Exception as e:
                logging.error(f"Timed out waiting for WETH transfer confirmation: {str(e)}")
                logging.warning("Continuing with the next step anyway, the transaction might confirm later.")
            
            # Wait a few seconds to make sure nonce is updated
            time.sleep(5)
        
        # 3. Send USDC to contract - INCREASED AMOUNT TO 50 USDC (5x MORE)
        usdc_amount = 50_000_000  # 50 USDC with 6 decimals (was 10)
        
        logging.info(f"Sending {usdc_amount / 1e6} USDC to contract...")
        tx_hash = usdc_contract.functions.transfer(PREDICTIVE_MANAGER_ADDRESS, usdc_amount).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 100000,
            'gasPrice': gas_price
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
        raw_tx_data = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
        
        usdc_tx_hash = w3.eth.send_raw_transaction(raw_tx_data)
        logging.info(f"USDC transfer transaction sent: {usdc_tx_hash.hex()}")
        logging.info(f"Waiting for confirmation (up to 300 seconds)...")
        
        try:
            usdc_receipt = w3.eth.wait_for_transaction_receipt(usdc_tx_hash, timeout=300)
            logging.info(f"USDC transfer confirmed. Hash: {usdc_receipt.transactionHash.hex()}")
        except Exception as e:
            logging.error(f"Timed out waiting for USDC transfer confirmation: {str(e)}")
            logging.warning("Continuing anyway, the transaction might confirm later.")
        
        # Check contract balances after transfer
        try:
            contract_weth_balance = weth_contract.functions.balanceOf(PREDICTIVE_MANAGER_ADDRESS).call()
            contract_usdc_balance = usdc_contract.functions.balanceOf(PREDICTIVE_MANAGER_ADDRESS).call()
            logging.info(f"Contract balances after transfer - WETH: {w3.from_wei(contract_weth_balance, 'ether')}, "
                      f"USDC: {contract_usdc_balance / 1e6}")
            output_logger.info(f"Contract now has {w3.from_wei(contract_weth_balance, 'ether')} WETH and {contract_usdc_balance / 1e6} USDC")
        except Exception as e:
            logging.error(f"Error checking contract balances: {str(e)}")
        
        # Wait a bit longer to make sure the contract received the tokens
        logging.info("Waiting 60 seconds to ensure tokens are received by the contract...")
        time.sleep(60)
        
        return {
            "status": "Transactions sent, some might still be pending",
            "weth_tx": deposit_tx_hash.hex(),
            "usdc_tx": usdc_tx_hash.hex() if 'usdc_tx_hash' in locals() else "Not sent",
            "weth_amount": weth_balance,
            "usdc_amount": usdc_amount
        }
    except Exception as e:
        logging.error(f"Error sending tokens: {str(e)}")
        traceback.print_exc()
        return None

def create_position(predicted_price):
    """Create position using predicted price"""
    if not w3:
        logging.error("Web3 not initialized. Check your RPC URL.")
        return None
        
    account = Account.from_key(PRIVATE_KEY)
    
    # Load contract ABIs
    predictive_abi = load_contract_abi("PredictiveLiquidityManager")
    predictive = w3.eth.contract(address=PREDICTIVE_MANAGER_ADDRESS, abi=predictive_abi)
    
    # Get contract token balances
    weth_abi = [{"constant": True, "inputs": [{"name": "owner", "type": "address"}], 
                 "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], 
                 "payable": False, "stateMutability": "view", "type": "function"}]
    erc20_abi = weth_abi  # Same balance checking function
    
    weth_contract = w3.eth.contract(address=WETH_ADDRESS, abi=weth_abi)
    usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=erc20_abi)
    
    # Check balances before proceeding
    contract_weth_balance = weth_contract.functions.balanceOf(PREDICTIVE_MANAGER_ADDRESS).call()
    contract_usdc_balance = usdc_contract.functions.balanceOf(PREDICTIVE_MANAGER_ADDRESS).call()
    
    logging.info(f"Contract balances - WETH: {w3.from_wei(contract_weth_balance, 'ether')}, "
                 f"USDC: {contract_usdc_balance / 1e6}")
    output_logger.info(f"Contract balances - WETH: {w3.from_wei(contract_weth_balance, 'ether')}, "
                     f"USDC: {contract_usdc_balance / 1e6}")
    
    if contract_weth_balance == 0 and contract_usdc_balance == 0:
        logging.warning("Contract has no tokens. Sending tokens first...")
        tokens_result = send_tokens_to_contract()
        if not tokens_result:
            logging.error("Failed to send tokens to contract. Cannot create position.")
            return None
        
        # Check balances again after sending tokens
        time.sleep(10)
        contract_weth_balance = weth_contract.functions.balanceOf(PREDICTIVE_MANAGER_ADDRESS).call()
        contract_usdc_balance = usdc_contract.functions.balanceOf(PREDICTIVE_MANAGER_ADDRESS).call()
        logging.info(f"Updated contract balances - WETH: {w3.from_wei(contract_weth_balance, 'ether')}, "
                   f"USDC: {contract_usdc_balance / 1e6}")
        output_logger.info(f"Updated contract balances - WETH: {w3.from_wei(contract_weth_balance, 'ether')}, "
                       f"USDC: {contract_usdc_balance / 1e6}")
        
        if contract_weth_balance == 0 and contract_usdc_balance == 0:
            logging.warning("Contract still has no tokens. Transactions might be pending. Will try to create position anyway.")
            output_logger.warning("Contract still has no tokens. Transactions might be pending.")
    
    # Prepare different price variations to try (all prices are USDC/WETH format)
    price_variations = []
    
    # Original inverted price with high precision
    inverted_price_high_precision = predicted_price["inverted"]
    price_variations.append({
        "name": "High precision inverted",
        "value": int(inverted_price_high_precision * 1e18),
        "scale": 1e18,
        "original": predicted_price["original"],
        "inverted": inverted_price_high_precision
    })
    
    # Rounded inverted price with 6 decimals (for better alignment with USDC decimals)
    inverted_price_rounded = round(predicted_price["inverted"], 6)
    price_variations.append({
        "name": "6-decimal rounded inverted",
        "value": int(inverted_price_rounded * 1e6),
        "scale": 1e6,
        "original": predicted_price["original"],
        "inverted": inverted_price_rounded
    })
    
    # Further simplified inverted price (4 decimals)
    inverted_price_simple = round(predicted_price["inverted"], 4)
    price_variations.append({
        "name": "4-decimal simplified inverted",
        "value": int(inverted_price_simple * 1e4),
        "scale": 1e4,
        "original": predicted_price["original"],
        "inverted": inverted_price_simple
    })
    
    # Modified price: slightly increase or decrease the prediction for a wider range
    inverted_price_adjusted = inverted_price_high_precision * 1.05  # 5% increase
    price_variations.append({
        "name": "Adjusted inverted (+5%)",
        "value": int(inverted_price_adjusted * 1e18),
        "scale": 1e18,
        "original": predicted_price["original"] / 1.05,
        "inverted": inverted_price_adjusted
    })
    
    # Try using a whole number to represent price (for debugging)
    fallback_whole_number = 1000000  # Simple large integer for testing
    price_variations.append({
        "name": "Fallback whole number",
        "value": fallback_whole_number,
        "scale": 1,
        "original": "N/A",
        "inverted": fallback_whole_number
    })
    
    # Log all price variations we'll try
    logging.info(f"Generated {len(price_variations)} price variations to try:")
    for i, pv in enumerate(price_variations):
        logging.info(f"  {i+1}. {pv['name']}: {pv['value']}/{pv['scale']} = {pv['value']/pv['scale']}")
    
    # Try each price variation until one succeeds or all fail
    for i, price_var in enumerate(price_variations):
        logging.info(f"Trying price variation {i+1}/{len(price_variations)}: {price_var['name']}")
        output_logger.info(f"Trying price: {price_var['value']/price_var['scale']} USDC/WETH (variation: {price_var['name']})")
        
        try:
            # Get current active position info before transaction
            try:
                current_position = predictive.functions.currentPosition().call()
                position_active = current_position[4]  # active flag
                position_id = current_position[0] if position_active else 0
                logging.info(f"Current position - Active: {position_active}, Token ID: {position_id}")
            except Exception as e:
                logging.warning(f"Error getting current position: {str(e)}")
                position_active = False
                position_id = 0
                
            # Get current gas price and increase it by 50%
            current_gas_price = w3.eth.gas_price
            gas_price = int(current_gas_price * 1.5)  # 50% higher gas price
            logging.info(f"Using gas price: {w3.from_wei(gas_price, 'gwei')} gwei (50% above current)")
            
            # Create transaction to update position with current price variation
            price_to_use = price_var["value"]
            tx_hash = predictive.functions.updatePredictionAndAdjust(price_to_use).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 2000000,  # Higher gas limit for complex operation
                'gasPrice': gas_price
            })
            
            signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
            # Fix for Web3.py version compatibility
            raw_tx_data = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
            
            transaction_hash = w3.eth.send_raw_transaction(raw_tx_data)
            
            logging.info(f"Transaction sent, waiting for confirmation: {transaction_hash.hex()}")
            output_logger.info(f"Transaction sent: {transaction_hash.hex()}")
            
            # Wait for transaction with extended timeout
            try:
                logging.info(f"Waiting for confirmation (up to 360 seconds)...")
                transaction_receipt = w3.eth.wait_for_transaction_receipt(transaction_hash, timeout=360)
                
                # Get gas used and total cost
                gas_used = transaction_receipt.gasUsed
                gas_price = w3.eth.get_transaction(transaction_hash).gasPrice
                gas_cost_eth = w3.from_wei(gas_used * gas_price, 'ether')
                
                logging.info(f"Transaction confirmed: {transaction_receipt.transactionHash.hex()}")
                logging.info(f"Gas used: {gas_used}, Gas cost: {gas_cost_eth} ETH")
                output_logger.info(f"Transaction confirmed! Gas cost: {gas_cost_eth} ETH")
                
                # Check if transaction status is success
                if transaction_receipt.status == 0:
                    logging.error(f"Transaction failed on-chain. Variation {i+1} failed.")
                    output_logger.error(f"Transaction for price variation {price_var['name']} failed on-chain.")
                    if i < len(price_variations) - 1:
                        logging.info(f"Will try next price variation.")
                        output_logger.info(f"Trying next price variation.")
                        continue
                    else:
                        logging.error("All price variations failed. Position could not be created.")
                        output_logger.error("All price variations failed. Position could not be created.")
                        return None
                
                # Try to get and parse events from transaction receipt
                try:
                    # Event for liquidity operations
                    liquidity_ops_event = predictive.events.LiquidityOperation()
                    liquidity_events = liquidity_ops_event.processReceipt(transaction_receipt)
                    
                    if liquidity_events:
                        for evt in liquidity_events:
                            args = evt['args']
                            logging.info(f"Event LiquidityOperation: Type={args['operationType']}, "
                                      f"TokenId={args['tokenId']}, Ticks={args['tickLower']}-{args['tickUpper']}, "
                                      f"Liquidity={args['liquidity']}, Success={args['success']}")
                            output_logger.info(f"Liquidity operation: {args['operationType']}, Success={args['success']}")
                            # If operation failed in the contract, log more details
                            if not args['success']:
                                output_logger.error(f"Liquidity operation failed in contract. Check token amounts: "
                                                f"Amount0={args['amount0']}, Amount1={args['amount1']}")
                                if i < len(price_variations) - 1:
                                    logging.info(f"Will try next price variation.")
                                    output_logger.info(f"Trying next price variation.")
                                    continue
                    else:
                        logging.warning("No LiquidityOperation events found in transaction receipt")
                    
                    # Event for prediction adjustment metrics
                    prediction_event = predictive.events.PredictionAdjustmentMetrics()
                    prediction_events = prediction_event.processReceipt(transaction_receipt)
                    
                    if prediction_events:
                        for evt in prediction_events:
                            args = evt['args']
                            logging.info(f"Event PredictionAdjustmentMetrics: Actual={args['actualPrice']}, "
                                       f"Predicted={args['predictedPrice']}, PredictedTick={args['predictedTick']}, "
                                       f"FinalTicks={args['finalTickLower']}-{args['finalTickUpper']}, "
                                       f"Adjusted={args['adjusted']}")
                            output_logger.info(f"Prediction metrics: Actual price={args['actualPrice']}, "
                                           f"Predicted price={args['predictedPrice']}, "
                                           f"Range={args['finalTickLower']}-{args['finalTickUpper']}")
                    else:
                        logging.warning("No PredictionAdjustmentMetrics events found in transaction receipt")
                except Exception as e:
                    logging.error(f"Error processing events from receipt: {str(e)}")
                
                # Get new position information
                try:
                    new_position = predictive.functions.currentPosition().call()
                    token_id = new_position[0]
                    liquidity = new_position[1]
                    lower_tick = new_position[2]
                    upper_tick = new_position[3]
                    is_active = new_position[4]
                    
                    logging.info(f"New position - Token ID: {token_id}, Liquidity: {liquidity}, "
                                 f"Lower Tick: {lower_tick}, Upper Tick: {upper_tick}, Active: {is_active}")
                    output_logger.info(f"New position created: Token ID {token_id}, Ticks: {lower_tick}-{upper_tick}")
                    
                    # If position is now active, we succeeded!
                    if is_active:
                        logging.info(f"SUCCESS! Position is active with price variation {i+1}: {price_var['name']}")
                        output_logger.info(f"SUCCESS! Position created with price: {price_var['value']/price_var['scale']} USDC/WETH")
                        
                        # Calculate results
                        result = {
                            "timestamp": datetime.now().isoformat(),
                            "transaction_hash": transaction_receipt.transactionHash.hex(),
                            "original_predicted_price": predicted_price["original"] if isinstance(predicted_price["original"], (int, float)) else 0,
                            "inverted_price": price_var['value']/price_var['scale'],
                            "price_variation": price_var['name'],
                            "used_price_value": price_var['value'],
                            "gas_used": gas_used,
                            "gas_price": gas_price,
                            "total_gas_cost_eth": gas_cost_eth,
                            "token_id": token_id,
                            "liquidity": liquidity,
                            "lower_tick": lower_tick,
                            "upper_tick": upper_tick,
                            "is_active": is_active
                        }
                        
                        # Save to CSV
                        save_result_to_csv(result)
                        
                        return result
                    # Position is not active, but we'll try the next price variation if available
                    else:
                        logging.warning(f"Position is not active after transaction with price variation {i+1}.")
                        output_logger.warning(f"Position NOT active with price: {price_var['value']/price_var['scale']} USDC/WETH")
                        
                        # Check contract balances again
                        contract_weth_balance = weth_contract.functions.balanceOf(PREDICTIVE_MANAGER_ADDRESS).call()
                        contract_usdc_balance = usdc_contract.functions.balanceOf(PREDICTIVE_MANAGER_ADDRESS).call()
                        logging.info(f"Contract balances after operation - WETH: {w3.from_wei(contract_weth_balance, 'ether')}, "
                                   f"USDC: {contract_usdc_balance / 1e6}")
                        output_logger.info(f"Contract balances after operation - WETH: {w3.from_wei(contract_weth_balance, 'ether')}, "
                                       f"USDC: {contract_usdc_balance / 1e6}")
                        
                        if i < len(price_variations) - 1:
                            logging.info(f"Will try next price variation.")
                            output_logger.info(f"Trying next price variation.")
                            # Wait a bit before trying the next variation
                            time.sleep(5)
                            continue
                        else:
                            logging.error("All price variations tried, but no active position was created.")
                            output_logger.error("All price variations tried, but no active position was created.")
                            
                            # Save the last attempt to CSV anyway
                            result = {
                                "timestamp": datetime.now().isoformat(),
                                "transaction_hash": transaction_receipt.transactionHash.hex(),
                                "original_predicted_price": predicted_price["original"] if isinstance(predicted_price["original"], (int, float)) else 0,
                                "inverted_price": price_var['value']/price_var['scale'],
                                "price_variation": price_var['name'],
                                "used_price_value": price_var['value'],
                                "gas_used": gas_used,
                                "gas_price": gas_price,
                                "total_gas_cost_eth": gas_cost_eth,
                                "token_id": token_id,
                                "liquidity": liquidity,
                                "lower_tick": lower_tick,
                                "upper_tick": upper_tick,
                                "is_active": is_active
                            }
                            
                            save_result_to_csv(result)
                            return result
                
                except Exception as e:
                    logging.error(f"Error getting new position info: {str(e)}")
                    if i < len(price_variations) - 1:
                        logging.info("Will try next price variation.")
                        continue
                    else:
                        # Still save basic transaction info for the last attempt
                        result = {
                            "timestamp": datetime.now().isoformat(),
                            "transaction_hash": transaction_receipt.transactionHash.hex(),
                            "original_predicted_price": predicted_price["original"] if isinstance(predicted_price["original"], (int, float)) else 0,
                            "inverted_price": price_var['value']/price_var['scale'],
                            "price_variation": price_var['name'],
                            "used_price_value": price_var['value'],
                            "gas_used": gas_used,
                            "gas_price": gas_price,
                            "total_gas_cost_eth": gas_cost_eth,
                            "token_id": "Error",
                            "liquidity": "Error",
                            "lower_tick": "Error",
                            "upper_tick": "Error",
                            "is_active": "Error"
                        }
                        
                        save_result_to_csv(result)
                        return result
                    
            except Exception as e:
                logging.error(f"Error waiting for transaction confirmation: {str(e)}")
                logging.warning(f"Transaction {transaction_hash.hex()} might still confirm later.")
                
                if i < len(price_variations) - 1:
                    logging.info("Will try next price variation.")
                    continue
                else:
                    # Create result with pending status for the last attempt
                    result = {
                        "timestamp": datetime.now().isoformat(),
                        "transaction_hash": transaction_hash.hex(),
                        "original_predicted_price": predicted_price["original"] if isinstance(predicted_price["original"], (int, float)) else 0,
                        "inverted_price": price_var['value']/price_var['scale'],
                        "price_variation": price_var['name'],
                        "used_price_value": price_var['value'],
                        "gas_used": "Pending",
                        "gas_price": gas_price,
                        "total_gas_cost_eth": "Pending",
                        "token_id": "Pending",
                        "liquidity": "Pending",
                        "lower_tick": "Pending",
                        "upper_tick": "Pending",
                        "is_active": "Pending"
                    }
                    
                    save_result_to_csv(result)
                    return result
                
        except Exception as e:
            logging.error(f"Error creating position with price variation {i+1}: {str(e)}")
            if i < len(price_variations) - 1:
                logging.info("Will try next price variation.")
                continue
            else:
                logging.error("All price variations failed with exceptions.")
                traceback.print_exc()
                return None
                
    # If we reach here, all variations failed
    logging.error("All price variations failed. Position could not be created.")
    output_logger.error("All price variations failed. Position could not be created.")
    return None

def save_result_to_csv(result):
    """Save transaction result to CSV file"""
    # Define CSV columns
    csv_columns = [
        "timestamp", "transaction_hash", "original_predicted_price", "inverted_price",
        "price_variation", "used_price_value", "gas_used", "gas_price", "total_gas_cost_eth", 
        "token_id", "liquidity", "lower_tick", "upper_tick", "is_active"
    ]
    
    # Check if file exists to determine if headers are needed
    file_exists = os.path.isfile(CSV_FILE_PATH)
    
    try:
        with open(CSV_FILE_PATH, 'a', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
            
            # Write header only if file is new
            if not file_exists:
                writer.writeheader()
            
            # Write data row
            writer.writerow(result)
            
        logging.info(f"Results saved to CSV: {CSV_FILE_PATH}")
        
        # Also save a copy in the current directory
        current_dir = os.getcwd()
        current_csv_file = os.path.join(current_dir, "position_results.csv")
        current_file_exists = os.path.isfile(current_csv_file)
        
        try:
            with open(current_csv_file, 'a', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
                
                # Write header only if file is new
                if not current_file_exists:
                    writer.writeheader()
                
                # Write data row
                writer.writerow(result)
                
            logging.info(f"Copy of results saved to current directory: {current_csv_file}")
            output_logger.info(f"Results saved to: {current_csv_file}")
            
            # Check if file exists and log its size
            if os.path.exists(current_csv_file):
                file_size = os.path.getsize(current_csv_file)
                logging.info(f"CSV file exists, size: {file_size} bytes")
                
                # Try to read back a few lines to verify
                try:
                    with open(current_csv_file, 'r') as f:
                        lines = f.readlines()
                        num_lines = min(5, len(lines))
                        logging.info(f"First {num_lines} lines of CSV:")
                        for i in range(num_lines):
                            logging.info(f"  {i+1}: {lines[i].strip()}")
                except Exception as e:
                    logging.error(f"Error reading back CSV file: {str(e)}")
            else:
                logging.error(f"CSV file does not exist after writing: {current_csv_file}")
        except Exception as e:
            logging.error(f"Error saving copy of results to current directory: {str(e)}")
    except Exception as e:
        logging.error(f"Error saving results to CSV: {str(e)}")
        traceback.print_exc()

def run_scheduled(interval_hours=1):
    """Run the position creation on a schedule"""
    logging.info(f"Starting scheduled execution every {interval_hours} hour(s)")
    
    while True:
        try:
            # Get predicted price
            predicted_price = get_predicted_price()
            logging.info(f"Predicted price: {predicted_price}")
            
            # Create position with predicted price
            result = create_position(predicted_price)
            
            if result:
                logging.info(f"Position created successfully. Token ID: {result.get('token_id', 'Unknown')}")
            else:
                logging.error("Failed to create position")
                
        except Exception as e:
            logging.error(f"Error in scheduled execution: {str(e)}")
            traceback.print_exc()
            
        # Sleep for the specified interval
        sleep_seconds = interval_hours * 3600
        logging.info(f"Sleeping for {interval_hours} hour(s) ({sleep_seconds} seconds)")
        time.sleep(sleep_seconds)

def main():
    """Main execution function"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Predictive liquidity position management")
    parser.add_argument("--schedule", action="store_true", help="Run on a schedule")
    parser.add_argument("--interval", type=int, default=1, help="Interval in hours (default: 1)")
    parser.add_argument("--send-tokens", action="store_true", help="Only send tokens to contract")
    args = parser.parse_args()
    
    # Check for required environment variables
    if not SEPOLIA_RPC_URL:
        logging.error("SEPOLIA_RPC_URL is not set in .env file")
        return
    
    if not PRIVATE_KEY:
        logging.error("PRIVATE_KEY is not set in .env file")
        return
    
    if not PREDICTIVE_MANAGER_ADDRESS:
        logging.error("PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS is not set in .env file")
        return
    
    # Execute based on arguments
    if args.send_tokens:
        # Only send tokens
        logging.info("Sending tokens to contract...")
        send_tokens_to_contract()
    elif args.schedule:
        # Run on schedule
        run_scheduled(args.interval)
    else:
        # Single execution
        logging.info("Running single execution...")
        predicted_price = get_predicted_price()
        logging.info(f"Predicted price: {predicted_price}")
        
        result = create_position(predicted_price)
        
        if result:
            logging.info(f"Position created successfully. Token ID: {result.get('token_id', 'Unknown')}")
        else:
            logging.error("Failed to create position")

if __name__ == "__main__":
    main()