import time
import requests
from web3 import Web3
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
INFURA_URL = os.getenv('INFURA_URL', 'https://sepolia.infura.io/v3/YOUR-PROJECT-ID')
PRIVATE_KEY = os.getenv('PRIVATE_KEY')
CONTRACT_ADDRESS = os.getenv('CONTRACT_ADDRESS')
PREDICTION_API_URL = 'http://95.216.156.73:5000/predict_price'

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Load contract ABI
with open('artifacts/contracts/UniswapLiquidityManager.sol/UniswapLiquidityManager.json', 'r') as f:
    contract_json = json.load(f)
    contract_abi = contract_json['abi']

# Initialize contract
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=contract_abi)

def get_predicted_price():
    """Get predicted price from API"""
    try:
        response = requests.get(f"{PREDICTION_API_URL}?symbol=ETHUSDT&interval=4h")
        if response.status_code == 200:
            data = response.json()
            return int(float(data['predicted_price']) * 1e18)  # Convert to wei
        else:
            print(f"Error getting prediction: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error in get_predicted_price: {e}")
        return None

def send_prediction_to_contract(predicted_price):
    """Send predicted price to smart contract"""
    try:
        # Get nonce
        nonce = w3.eth.get_transaction_count(w3.eth.account.from_key(PRIVATE_KEY).address)
        
        # Build transaction
        transaction = contract.functions.setPredictedPrice(predicted_price).build_transaction({
            'gas': 200000,
            'gasPrice': w3.eth.gas_price,
            'nonce': nonce,
        })
        
        # Sign transaction
        signed_txn = w3.eth.account.sign_transaction(transaction, PRIVATE_KEY)
        
        # Send transaction
        tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        
        # Wait for transaction receipt
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        print(f"Transaction successful! Hash: {receipt['transactionHash'].hex()}")
        return receipt
    except Exception as e:
        print(f"Error in send_prediction_to_contract: {e}")
        return None

def main():
    print("Starting price keeper...")
    
    while True:
        try:
            # Get predicted price
            predicted_price = get_predicted_price()
            
            if predicted_price is not None:
                # Send to contract
                receipt = send_prediction_to_contract(predicted_price)
                
                if receipt is not None:
                    print(f"Successfully updated price: {predicted_price / 1e18}")
            
            # Wait for next update
            time.sleep(3600)  # Update every hour
            
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(60)  # Wait a minute before retrying

if __name__ == "__main__":
    main() 