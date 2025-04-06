import os
import json
import requests
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
import logging
from datetime import datetime
from web3.exceptions import TimeExhausted

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('position_creation.log'),
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

def load_contract_abi(contract_name):
    """Load contract ABI from artifacts"""
    artifacts_path = f"artifacts/contracts/{contract_name}.sol/{contract_name}.json"
    with open(artifacts_path) as f:
        contract_json = json.load(f)
        return contract_json["abi"]

def get_predicted_price():
    """Get predicted price from API"""
    try:
        response = requests.get(PREDICTION_API_URL)
        response.raise_for_status()
        data = response.json()
        predicted_price = data.get('predicted_price')
        if predicted_price is None:
            raise ValueError("No predicted price in API response")
        return predicted_price
    except Exception as e:
        logging.error(f"Error fetching prediction: {str(e)}")
        raise

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
        
        # Get predicted price from API
        predicted_price = get_predicted_price()
        logging.info(f"Received predicted price: {predicted_price}")
        
        # Check if there's an existing position
        position = predictive.functions.getActivePositionDetails().call()
        if position[4]:  # if position is active
            logging.info("Active position exists:")
            logging.info(f"- Token ID: {position[0]}")
            logging.info(f"- Liquidity: {position[1]}")
            logging.info(f"- Lower Tick: {position[2]}")
            logging.info(f"- Upper Tick: {position[3]}")
            return
        
        # Prepare transaction
        logging.info("No active position found. Creating new position...")
        price_in_wei = w3.to_wei(predicted_price, 'ether')
        
        transaction = predictive.functions.updatePredictionAndAdjust(
            price_in_wei
        ).build_transaction({
            'from': account.address,
            'gas': 3000000,
            'gasPrice': w3.to_wei(10, 'gwei'),  # ✅ Increased gas price
            'nonce': w3.eth.get_transaction_count(account.address),
        })
        
        # Sign and send transaction
        signed_txn = w3.eth.account.sign_transaction(transaction, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)

        
        logging.info(f"Transaction sent. Hash: {tx_hash.hex()}")
        
        # Wait for receipt
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)  # ⏳ longer timeout
            if receipt['status'] == 1:
                logging.info("Position created successfully!")
                new_position = predictive.functions.getActivePositionDetails().call()
                logging.info("New position details:")
                logging.info(f"- Token ID: {new_position[0]}")
                logging.info(f"- Liquidity: {new_position[1]}")
                logging.info(f"- Lower Tick: {new_position[2]}")
                logging.info(f"- Upper Tick: {new_position[3]}")
            else:
                logging.error("Transaction failed!")
        except TimeExhausted:
            logging.error("⏳ Transaction not confirmed within the expected time. Still pending...")

    except Exception as e:
        logging.error(f"Error creating position: {str(e)}")
        raise

def main():
    logging.info(f"Starting position creation process at {datetime.now()}")
    create_position()

if __name__ == "__main__":
    main()
