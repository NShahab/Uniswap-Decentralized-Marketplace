import os
import json
import time
import logging
import requests
import argparse
import traceback
import csv
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
from datetime import datetime
import schedule

# Load environment variables
load_dotenv()

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('position_creation.log'),
        logging.StreamHandler()
    ]
)

# Create a separate logger for transaction outputs
output_logger = logging.getLogger('transaction_output')
output_logger.setLevel(logging.INFO)
output_handler = logging.FileHandler('transaction_output.log')
output_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
output_logger.addHandler(output_handler)
output_logger.propagate = False

# Load environment variables
PREDICTIVE_MANAGER_ADDRESS = os.getenv('PREDICTIVE_MANAGER_ADDRESS')
BASELINE_MANAGER_ADDRESS = os.getenv('BASELINE_MINIMAL_ADDRESS')  # آدرس قرارداد بیس‌لاین
USDC_ADDRESS = os.getenv('USDC_ADDRESS')
WETH_ADDRESS = os.getenv('WETH_ADDRESS')
PRIVATE_KEY = os.getenv('PRIVATE_KEY')
RPC_URL = os.getenv('RPC_URL')

# Initialize Web3
w3 = None
try:
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    w3.eth.account.enable_unaudited_hdwallet_features()
    
    # Convert addresses to checksum format
    if PREDICTIVE_MANAGER_ADDRESS:
        PREDICTIVE_MANAGER_ADDRESS = w3.to_checksum_address(PREDICTIVE_MANAGER_ADDRESS)
    if BASELINE_MANAGER_ADDRESS:
        BASELINE_MANAGER_ADDRESS = w3.to_checksum_address(BASELINE_MANAGER_ADDRESS)
    if USDC_ADDRESS:
        USDC_ADDRESS = w3.to_checksum_address(USDC_ADDRESS)
    if WETH_ADDRESS:
        WETH_ADDRESS = w3.to_checksum_address(WETH_ADDRESS)
    
    logging.info(f"Connected to network: {w3.net.version}")
    logging.info(f"Using predictive contract: {PREDICTIVE_MANAGER_ADDRESS}")
    logging.info(f"Using baseline contract: {BASELINE_MANAGER_ADDRESS}")
    logging.info(f"USDC: {USDC_ADDRESS}")
    logging.info(f"WETH: {WETH_ADDRESS}")
except Exception as e:
    logging.error(f"Error initializing Web3: {str(e)}")

def load_contract_abi(contract_name):
    """Load ABI from artifacts"""
    try:
        artifact_path = f'artifacts/contracts/{contract_name}.sol/{contract_name}.json'
        with open(artifact_path, 'r') as f:
        contract_json = json.load(f)
            return contract_json['abi']
    except Exception as e:
        logging.error(f"Error loading ABI: {str(e)}")
        raise

def get_predicted_price():
    """Get the predicted ETH price from API or use a fallback"""
    # Try to get predicted price from our custom API
    api_url = os.getenv('PREDICTION_API_URL')
    
    if api_url:
        try:
            logging.info(f"Getting predicted price from custom API: {api_url}")
            response = requests.get(api_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # اینجا ساختار API شما باید اعمال شود
                # مثال: price = data['result']['predicted_price']
                price = data.get('predicted_price', None)
                
                if price is not None and isinstance(price, (int, float)):
                    logging.info(f"Custom API predicted ETH price: {price} USD")
                    
                    # Invert the price for Uniswap (USDC/WETH)
                    inverted_price = 1.0 / price
                    logging.info(f"Inverted price (USDC/WETH): {inverted_price}")
                    
                    return {
                        "original": price,
                        "inverted": inverted_price
                    }
                else:
                    logging.warning(f"Invalid price format from API: {data}")
        except Exception as e:
            logging.warning(f"Error getting price from custom API: {str(e)}")
    else:
        logging.warning("PREDICTION_API_URL not set in .env file")
    
    # Fallback: try Coinbase API
    try:
        logging.info("Falling back to Coinbase API")
        response = requests.get('https://api.coinbase.com/v2/prices/ETH-USD/spot')
        if response.status_code == 200:
        data = response.json()
            price = float(data['data']['amount'])
            logging.info(f"Coinbase API ETH price: {price} USD")
            
            # Invert the price for Uniswap (USDC/WETH)
            inverted_price = 1.0 / price
            logging.info(f"Inverted price (USDC/WETH): {inverted_price}")
            
            return {
                "original": price,
                "inverted": inverted_price
            }
    except Exception as e:
        logging.warning(f"Error getting price from Coinbase: {str(e)}")
    
    # Final fallback: use a fixed price
    fallback_price = 1800.0  # ETH/USDC
    inverted_fallback = 1.0 / fallback_price  # USDC/WETH
    
    logging.warning(f"Using fallback price: {fallback_price} USD")
    
    return {
        "original": fallback_price,
        "inverted": inverted_fallback
    }

def send_tokens_to_contract(send_usdc=True, is_baseline=False):
    """Send USDC and WETH to the contract"""
    if not w3:
        logging.error("Web3 not initialized. Check your RPC URL.")
        return None
    
    account = Account.from_key(PRIVATE_KEY)
    
    # Determine which contract address to use
    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_type = "Baseline" if is_baseline else "Predictive"
    
    # Ensure required addresses are set
    if not all([USDC_ADDRESS, WETH_ADDRESS, contract_address]):
        logging.error("Required addresses are not set in .env file")
        raise ValueError("All addresses are required")
    
    logging.info(f"Preparing to send tokens to {contract_type} contract ({contract_address})...")
    
    # Load contract ABIs
    weth_abi = [
        {"constant": False, "inputs": [], "name": "deposit", "outputs": [], 
         "payable": True, "stateMutability": "payable", "type": "function"},
        {"constant": True, "inputs": [{"name": "owner", "type": "address"}], 
         "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], 
         "payable": False, "stateMutability": "view", "type": "function"},
        {"constant": False, "inputs": [{"name": "dst", "type": "address"}, 
                                     {"name": "wad", "type": "uint256"}], 
         "name": "transfer", "outputs": [{"name": "", "type": "bool"}], 
         "payable": False, "stateMutability": "nonpayable", "type": "function"}
    ]
    
    # ERC20 ABI for USDC (simplified)
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
    
    # Check current contract balances
    contract_weth_balance = weth_contract.functions.balanceOf(contract_address).call()
    contract_usdc_balance = usdc_contract.functions.balanceOf(contract_address).call()
    logging.info(f"Current {contract_type} contract balances - WETH: {w3.from_wei(contract_weth_balance, 'ether')}, "
                 f"USDC: {contract_usdc_balance / 1e6}")
    
    try:
        # Get current gas price and increase it by 50%
        current_gas_price = w3.eth.gas_price
        gas_price = int(current_gas_price * 1.5)  # 50% higher gas price
        
        # 1. Convert ETH to WETH
        eth_amount = w3.to_wei(0.05, 'ether')  # 0.05 ETH
        
        logging.info(f"Converting {w3.from_wei(eth_amount, 'ether')} ETH to WETH...")
        tx_hash = weth_contract.functions.deposit().build_transaction({
            'from': account.address,
            'value': eth_amount,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 100000,
            'gasPrice': gas_price
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
        raw_tx_data = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
        
        deposit_tx_hash = w3.eth.send_raw_transaction(raw_tx_data)
        logging.info(f"WETH deposit transaction sent: {deposit_tx_hash.hex()}")
        
        try:
            deposit_receipt = w3.eth.wait_for_transaction_receipt(deposit_tx_hash, timeout=300)
            logging.info(f"ETH to WETH conversion confirmed.")
        except Exception as e:
            logging.error(f"Timed out waiting for WETH deposit confirmation: {str(e)}")
        
        time.sleep(5)
        
        # 2. Send WETH to contract
        weth_balance = weth_contract.functions.balanceOf(account.address).call()
        
        if weth_balance > 0:
            logging.info(f"Sending {w3.from_wei(weth_balance, 'ether')} WETH to {contract_type} contract...")
            tx_hash = weth_contract.functions.transfer(contract_address, weth_balance).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 100000,
                'gasPrice': gas_price
            })
            
            signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
            raw_tx_data = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
            
            weth_tx_hash = w3.eth.send_raw_transaction(raw_tx_data)
            logging.info(f"WETH transfer transaction sent: {weth_tx_hash.hex()}")
            
            try:
                w3.eth.wait_for_transaction_receipt(weth_tx_hash, timeout=300)
                logging.info(f"WETH transfer confirmed.")
            except Exception as e:
                logging.error(f"Timed out waiting for WETH transfer confirmation: {str(e)}")
            
            time.sleep(5)
        
        # 3. Send USDC to contract only if requested and contract doesn't have enough
        usdc_tx_hash = None
        if send_usdc and contract_usdc_balance < 10_000_000:  # Less than 10 USDC
            usdc_amount = 50_000_000  # 50 USDC with 6 decimals
            
            logging.info(f"Sending {usdc_amount / 1e6} USDC to {contract_type} contract...")
            tx_hash = usdc_contract.functions.transfer(contract_address, usdc_amount).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 100000,
                'gasPrice': gas_price
            })
            
            signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
            raw_tx_data = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
            
            usdc_tx_hash = w3.eth.send_raw_transaction(raw_tx_data)
            logging.info(f"USDC transfer transaction sent: {usdc_tx_hash.hex()}")
            
            try:
                w3.eth.wait_for_transaction_receipt(usdc_tx_hash, timeout=300)
                logging.info(f"USDC transfer confirmed.")
            except Exception as e:
                logging.error(f"Timed out waiting for USDC transfer confirmation: {str(e)}")
        else:
            if contract_usdc_balance >= 10_000_000:
                logging.info(f"{contract_type} contract already has enough USDC: {contract_usdc_balance / 1e6} USDC. Skipping USDC transfer.")
            elif not send_usdc:
                logging.info("USDC transfer skipped as requested.")
        
        # Check contract balances after transfer
        contract_weth_balance = weth_contract.functions.balanceOf(contract_address).call()
        contract_usdc_balance = usdc_contract.functions.balanceOf(contract_address).call()
        logging.info(f"{contract_type} contract balances after transfer - WETH: {w3.from_wei(contract_weth_balance, 'ether')}, "
                  f"USDC: {contract_usdc_balance / 1e6}")
        
        return {
            "weth_tx": deposit_tx_hash.hex(),
            "usdc_tx": usdc_tx_hash.hex() if usdc_tx_hash else "Not sent",
            "weth_amount": weth_balance,
            "usdc_sent": send_usdc and contract_usdc_balance < 10_000_000
        }
    except Exception as e:
        logging.error(f"Error sending tokens to {contract_type} contract: {str(e)}")
        traceback.print_exc()
        return None

def create_position(predicted_price, send_usdc=True, is_baseline=False):
    """Create position using predicted price"""
    if not w3:
        logging.error("Web3 not initialized. Check your RPC URL.")
        return None
        
    account = Account.from_key(PRIVATE_KEY)
    
    # Determine which contract address to use
    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_type = "Baseline" if is_baseline else "Predictive"
    contract_name = "BaselineMinimalManager" if is_baseline else "PredictiveLiquidityManager"
    
    # Load contract ABIs
    try:
        contract_abi = load_contract_abi(contract_name)
        contract = w3.eth.contract(address=contract_address, abi=contract_abi)
    except Exception as e:
        logging.error(f"Error loading {contract_type} contract ABI: {str(e)}")
        return None
    
    # Get contract token balances
    erc20_abi = [{"constant": True, "inputs": [{"name": "owner", "type": "address"}], 
                 "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], 
                 "payable": False, "stateMutability": "view", "type": "function"}]
    
    weth_contract = w3.eth.contract(address=WETH_ADDRESS, abi=erc20_abi)
    usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=erc20_abi)
    
    # Check balances before proceeding
    contract_weth_balance = weth_contract.functions.balanceOf(contract_address).call()
    contract_usdc_balance = usdc_contract.functions.balanceOf(contract_address).call()
    
    logging.info(f"{contract_type} contract balances - WETH: {w3.from_wei(contract_weth_balance, 'ether')}, "
                 f"USDC: {contract_usdc_balance / 1e6}")
    
    # Check if contract has enough tokens
    has_enough_weth = contract_weth_balance > 0
    has_enough_usdc = contract_usdc_balance >= 10_000_000  # At least 10 USDC
    
    if not has_enough_weth or not has_enough_usdc:
        logging.warning(f"{contract_type} contract doesn't have enough tokens.")
        
        if not has_enough_weth:
            logging.warning(f"{contract_type} contract needs WETH.")
        
        if not has_enough_usdc:
            logging.warning(f"{contract_type} contract needs USDC.")
            
        logging.info(f"Sending tokens to {contract_type} contract...")
        tokens_result = send_tokens_to_contract(send_usdc=send_usdc, is_baseline=is_baseline)
        if not tokens_result:
            logging.error(f"Failed to send tokens to {contract_type} contract. Cannot create position.")
            return None
    
    # Prepare optimized price variations for sending to contract
    # Using the 6-decimal rounded inverted price that works best
    inverted_price_rounded = round(predicted_price["inverted"], 6)
    price_to_send = int(inverted_price_rounded * 1e6)
    price_scale = 1e6
    
    logging.info(f"Creating position with {contract_type} contract - Predicted price: {predicted_price['original']} ETH/USDC")
    logging.info(f"Sending price to {contract_type} contract: {price_to_send}/{price_scale} = {price_to_send/price_scale} USDC/WETH")
    
    try:
        # Get current active position info before transaction
        try:
            current_position = contract.functions.currentPosition().call()
            position_active = current_position[4]  # active flag
            position_id = current_position[0] if position_active else 0
            logging.info(f"{contract_type} current position - Active: {position_active}, Token ID: {position_id}")
        except Exception as e:
            logging.warning(f"Error getting {contract_type} current position: {str(e)}")
            position_active = False
            position_id = 0
            
        # Get current gas price and increase it by 50%
        current_gas_price = w3.eth.gas_price
        gas_price = int(current_gas_price * 1.5)  # 50% higher gas price
        logging.info(f"Using gas price: {w3.from_wei(gas_price, 'gwei')} gwei (50% above current)")
        
        # Create transaction to update position with optimized price
        tx_hash = contract.functions.updatePredictionAndAdjust(price_to_send).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 2000000,  # Higher gas limit for complex operation
            'gasPrice': gas_price
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
        raw_tx_data = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
        
        transaction_hash = w3.eth.send_raw_transaction(raw_tx_data)
        
        logging.info(f"{contract_type} transaction sent: {transaction_hash.hex()}")
        logging.info(f"Waiting for confirmation (up to 360 seconds)...")
        
        # Wait for transaction with extended timeout
        transaction_receipt = w3.eth.wait_for_transaction_receipt(transaction_hash, timeout=360)
        
        # Get gas used and total cost
        gas_used = transaction_receipt.gasUsed
        gas_price = w3.eth.get_transaction(transaction_hash).gasPrice
        gas_cost_eth = w3.from_wei(gas_used * gas_price, 'ether')
        
        logging.info(f"{contract_type} transaction confirmed: {transaction_receipt.transactionHash.hex()}")
        logging.info(f"Gas used: {gas_used}, Gas cost: {gas_cost_eth} ETH")
        
        # Check transaction status
        if transaction_receipt.status == 0:
            logging.error(f"{contract_type} transaction failed on-chain.")
            return None
        
        # Get new position info
        try:
            new_position = contract.functions.currentPosition().call()
            token_id = new_position[0]
            liquidity = new_position[1]
            tick_lower = new_position[2]
            tick_upper = new_position[3]
            is_active = new_position[4]
            
            logging.info(f"{contract_type} new position - Token ID: {token_id}, Liquidity: {liquidity}, Lower Tick: {tick_lower}, Upper Tick: {tick_upper}, Active: {is_active}")
            
            # Prepare result for CSV
            result = {
                "timestamp": datetime.now().isoformat(),
                "transaction_hash": transaction_receipt.transactionHash.hex(),
                "contract_type": contract_type,
                "original_predicted_price": predicted_price["original"],
                "sent_price": price_to_send/price_scale,
                "price_format": "6-decimal rounded inverted",
                "price_int": price_to_send,
                "gas_used": gas_used,
                "gas_price": gas_price,
                "gas_cost_eth": gas_cost_eth,
                "token_id": token_id,
                "liquidity": liquidity,
                "tick_lower": tick_lower,
                "tick_upper": tick_upper,
                "is_active": is_active
            }
            
            # Save result to CSV
            save_result_to_csv(result)
            
            return result
            
        except Exception as e:
            logging.error(f"Error getting {contract_type} position info after transaction: {str(e)}")
            return None
            
    except Exception as e:
        logging.error(f"Error creating {contract_type} position: {str(e)}")
        traceback.print_exc()
        return None

def save_result_to_csv(result):
    """Save transaction result to CSV file"""
    # Define CSV columns
    csv_columns = [
        "timestamp", "transaction_hash", "contract_type", "original_predicted_price", 
        "sent_price", "price_format", "price_int", "gas_used", 
        "gas_price", "gas_cost_eth", "token_id", "liquidity", 
        "tick_lower", "tick_upper", "is_active"
    ]
    
    # Get the path for the CSV file
    # First in project directory
    result_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    csv_file = os.path.join(result_dir, "position_results.csv")
    
    # Also save a copy in the current directory
    current_dir = os.getcwd()
    current_csv_file = os.path.join(current_dir, "position_results.csv")
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(csv_file), exist_ok=True)
    
    # Log paths
    logging.info(f"Result directory: {result_dir}")
    logging.info(f"Current directory: {current_dir}")
    logging.info(f"CSV file path: {csv_file}")
    logging.info(f"Current directory CSV path: {current_csv_file}")
    
    # Save to project directory CSV
    try:
        # Check if file exists to determine if we need to write headers
        file_exists = os.path.isfile(csv_file)
        
        with open(csv_file, mode='a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns)
            if not file_exists:
                writer.writeheader()
            writer.writerow(result)
        
        logging.info(f"Results saved to CSV: {csv_file}")
        
        # Check if file was created properly
        if os.path.exists(csv_file):
            file_size = os.path.getsize(csv_file)
            logging.info(f"CSV file exists. Size: {file_size} bytes")
            
            # Read back a few lines to verify content
            try:
                with open(csv_file, 'r') as f:
                    lines = f.readlines()[:5]  # First 5 lines only
                    logging.info(f"CSV file first few lines ({len(lines)} lines):")
                    for line in lines:
                        logging.info(line.strip())
            except Exception as e:
                logging.error(f"Error reading back CSV file: {str(e)}")
            else:
            logging.error(f"CSV file does not exist after writing: {csv_file}")

    except Exception as e:
        logging.error(f"Error saving to CSV file: {str(e)}")
    
    # Also save to current directory CSV
    try:
        file_exists = os.path.isfile(current_csv_file)
        
        with open(current_csv_file, mode='a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns)
            if not file_exists:
                writer.writeheader()
            writer.writerow(result)
        
        logging.info(f"Results also saved to CSV in current directory: {current_csv_file}")
    except Exception as e:
        logging.error(f"Error saving to current directory CSV: {str(e)}")

def main():
    """Main function to parse arguments and execute"""
    parser = argparse.ArgumentParser(description='Create Uniswap position based on price prediction')
    parser.add_argument('--schedule', action='store_true', help='Run on a schedule')
    parser.add_argument('--interval', type=int, default=1, help='Interval in hours (default: 1)')
    parser.add_argument('--send-tokens', action='store_true', help='Just send tokens to contract without creating position')
    parser.add_argument('--no-usdc', action='store_true', help='Skip sending USDC to contract')
    parser.add_argument('--baseline', action='store_true', help='Test baseline contract instead of predictive')
    parser.add_argument('--both', action='store_true', help='Test both predictive and baseline contracts')
    args = parser.parse_args()
    
    if args.send_tokens:
        if args.both:
            logging.info("Sending tokens to both contracts...")
            # First send to predictive
            result_pred = send_tokens_to_contract(send_usdc=not args.no_usdc, is_baseline=False)
            if result_pred:
                logging.info("Tokens sent successfully to predictive contract!")
            else:
                logging.error("Failed to send tokens to predictive contract")
            
            # Then send to baseline
            result_base = send_tokens_to_contract(send_usdc=not args.no_usdc, is_baseline=True)
            if result_base:
                logging.info("Tokens sent successfully to baseline contract!")
            else:
                logging.error("Failed to send tokens to baseline contract")
        else:
            is_baseline = args.baseline
            contract_type = "baseline" if is_baseline else "predictive"
            logging.info(f"Sending tokens to {contract_type} contract...")
            result = send_tokens_to_contract(send_usdc=not args.no_usdc, is_baseline=is_baseline)
            if result:
                logging.info(f"Tokens sent successfully to {contract_type} contract!")
            else:
                logging.error(f"Failed to send tokens to {contract_type} contract")
        return
    
    if args.schedule:
        send_usdc = not args.no_usdc
        is_baseline = args.baseline
        test_both = args.both
        contract_type = "baseline" if is_baseline and not test_both else "predictive"
        
        if test_both:
            logging.info(f"Scheduled execution for both contracts with USDC transfer {'disabled' if args.no_usdc else 'enabled'}")
        else:
            logging.info(f"Scheduled execution for {contract_type} contract with USDC transfer {'disabled' if args.no_usdc else 'enabled'}")
        
        def job():
            logging.info(f"=== Scheduled execution at {datetime.now().isoformat()} ===")
            price_data = get_predicted_price()
            
            if test_both:
                # First run predictive
                pred_result = create_position(price_data, send_usdc=send_usdc, is_baseline=False)
                if pred_result:
                    logging.info(f"Predictive position created successfully. Token ID: {pred_result['token_id']}")
                else:
                    logging.error("Failed to create predictive position")
                
                # Then run baseline
                base_result = create_position(price_data, send_usdc=send_usdc, is_baseline=True)
                if base_result:
                    logging.info(f"Baseline position created successfully. Token ID: {base_result['token_id']}")
                else:
                    logging.error("Failed to create baseline position")
            else:
                result = create_position(price_data, send_usdc=send_usdc, is_baseline=is_baseline)
                if result:
                    logging.info(f"Position created successfully. Token ID: {result['token_id']}")
                else:
                    logging.error("Failed to create position")
        
        # Run once immediately
        job()
        
        # Schedule future runs
        schedule.every(args.interval).hours.do(job)
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            logging.info("Scheduled execution stopped by user")
        except Exception as e:
            logging.error(f"Error in scheduled execution: {str(e)}")
    else:
        # Regular single execution
        price_data = get_predicted_price()
        
        if args.both:
            # First run predictive
            logging.info("=== Testing Predictive Contract ===")
            pred_result = create_position(price_data, send_usdc=not args.no_usdc, is_baseline=False)
            
            if pred_result:
                logging.info(f"Predictive position created successfully. Token ID: {pred_result['token_id']}")
                
                # Then run baseline
                logging.info("=== Testing Baseline Contract ===")
                base_result = create_position(price_data, send_usdc=not args.no_usdc, is_baseline=True)
                
                if base_result:
                    logging.info(f"Baseline position created successfully. Token ID: {base_result['token_id']}")
                else:
                    logging.error("Failed to create baseline position")
            else:
                logging.error("Failed to create predictive position. Baseline test skipped.")
        else:
            is_baseline = args.baseline
            contract_type = "Baseline" if is_baseline else "Predictive"
            logging.info(f"=== Testing {contract_type} Contract ===")
            result = create_position(price_data, send_usdc=not args.no_usdc, is_baseline=is_baseline)
            
            if result:
                logging.info(f"{contract_type} position created successfully. Token ID: {result['token_id']}")
            else:
                logging.error(f"Failed to create {contract_type.lower()} position")

if __name__ == "__main__":
    main()