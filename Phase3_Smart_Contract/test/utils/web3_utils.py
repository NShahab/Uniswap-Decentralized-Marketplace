# test/utils/web3_utils.py
import os
import json
import logging
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
from pathlib import Path
import time # Import time for potential delays

# --- Logging Setup ---
logger = logging.getLogger('web3_utils')
# Basic logging configuration if not configured elsewhere
if not logger.hasHandlers():
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


# --- Load Environment Variables ---
# Ensure .env is loaded relative to the project root if this script is called directly
# Adjust path finding if needed. Assume .env is in PROJECT_ROOT.
utils_dir = Path(__file__).resolve().parent
PROJECT_ROOT = utils_dir.parent.parent # Adjust if 'utils' is not inside 'test' or 'test' not inside root
env_path = PROJECT_ROOT / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    # logger.debug(f"Loaded .env file from: {env_path}")
else:
    logger.warning(f".env file not found at expected location: {env_path}")

PRIVATE_KEY = os.getenv('PRIVATE_KEY')
# Use a specific ENV VAR for the local fork RPC
RPC_URL = os.getenv('MAINNET_FORK_RPC_URL', 'http://127.0.0.1:8545') # Default to localhost

# --- Web3 Initialization ---
w3 = None

def init_web3(retries=3, delay=2):
    """Initialize Web3 connection and validate environment."""
    global w3
    if w3 and w3.is_connected():
        # logger.debug("Web3 already initialized and connected.")
        return True

    if not RPC_URL:
        logger.error("RPC_URL (for fork) not found or set.")
        return False
    if not PRIVATE_KEY:
        logger.error("PRIVATE_KEY not found in environment variables.")
        return False

    for attempt in range(retries):
        try:
            logger.info(f"Attempting to connect to Web3 provider at {RPC_URL} (Attempt {attempt + 1}/{retries})...")
            w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={'timeout': 60})) # Increased timeout
            if w3.is_connected():
                chain_id = w3.net.version
                logger.info(f"Successfully connected to network via {RPC_URL} - Chain ID: {chain_id}")
                return True
            else:
                 logger.warning(f"Connection attempt {attempt + 1} failed (is_connected() is false).")
        except Exception as e:
            logger.error(f"Error connecting to Web3 provider on attempt {attempt + 1}: {e}")

        if attempt < retries - 1:
             logger.info(f"Retrying connection after {delay} seconds...")
             time.sleep(delay)

    logger.critical("Failed to connect to Web3 provider after multiple retries.")
    w3 = None
    return False


# --- Standard IERC20 ABI ---
IERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function", "stateMutability": "view"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function", "stateMutability": "view"},
    {"constant": False, "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function", "stateMutability": "nonpayable"},
    {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function", "stateMutability": "nonpayable"},
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
]

# --- WETH ABI (Minimal, just for type hinting, deposit happens via sending ETH) ---
WETH_ABI = IERC20_ABI # WETH implements ERC20. Deposit is via fallback/receive.

# --- Mainnet WETH Address ---
WETH_ADDRESS = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

def load_contract_abi(contract_name):
    """Load a contract ABI from artifacts directory."""
    if contract_name == "IERC20": return IERC20_ABI
    if contract_name == "WETH": return WETH_ABI # Added for clarity

    # Adjusted path finding relative to this utils script
    # Project Root -> test -> utils -> web3_utils.py
    # Artifacts should be at Project Root / artifacts
    base_path = Path(__file__).resolve().parent.parent.parent # Assumes utils is in test, test is in root

    possible_paths = [
        base_path / f'artifacts/contracts/{contract_name}.sol/{contract_name}.json',
        base_path / f'artifacts/contracts/interfaces/{contract_name}.sol/{contract_name}.json',
        base_path / f'artifacts/@uniswap/v3-core/contracts/interfaces/{contract_name}.sol/{contract_name}.json',
        base_path / f'artifacts/@uniswap/v3-periphery/contracts/interfaces/{contract_name}.sol/{contract_name}.json',
    ]

    for path in possible_paths:
        if path.exists():
            # logger.debug(f"Loading ABI for {contract_name} from: {path}")
            with open(path) as f:
                try:
                    contract_json = json.load(f)
                    if 'abi' not in contract_json:
                        logger.error(f"ABI key not found in {path}")
                        continue
                    return contract_json['abi']
                except json.JSONDecodeError:
                    logger.error(f"Error decoding JSON from {path}")
                    continue
    raise FileNotFoundError(f"ABI not found for {contract_name} in any expected path relative to {base_path}")

def get_contract(address, contract_name):
    """Get contract instance with loaded ABI."""
    global w3
    if not w3 or not w3.is_connected():
        if not init_web3(): raise ConnectionError("Web3 connection failed")

    if not address: raise ValueError(f"Address for {contract_name} not provided")

    try:
        checksum_address = Web3.to_checksum_address(address)
        abi = load_contract_abi(contract_name)
        return w3.eth.contract(address=checksum_address, abi=abi)
    except Exception as e:
        logger.exception(f"Error getting contract {contract_name} at {address}: {e}")
        raise

def send_transaction(tx_params):
    """Builds necessary fields, signs, sends a transaction and waits for receipt."""
    global w3
    if not w3 or not w3.is_connected(): raise ConnectionError("Web3 connection failed")
    if 'from' not in tx_params: raise ValueError("Transaction 'from' address missing")

    try:
        # Ensure Chain ID
        if 'chainId' not in tx_params: tx_params['chainId'] = int(w3.net.version)

        # Ensure Nonce
        if 'nonce' not in tx_params: tx_params['nonce'] = w3.eth.get_transaction_count(tx_params['from'])

        # Gas Estimation (if not provided)
        if 'gas' not in tx_params:
            try:
                tx_params['gas'] = int(w3.eth.estimate_gas(tx_params) * 1.25) # Add 25% buffer
                logger.debug(f"Estimated gas: {tx_params['gas']}")
            except Exception as gas_err:
                logger.error(f"Gas estimation failed: {gas_err}. Using default 1,000,000.")
                tx_params['gas'] = 1000000

        # Gas Price Strategy (Handle EIP-1559 vs Legacy)
        if 'gasPrice' not in tx_params and 'maxFeePerGas' not in tx_params:
             try:
                  # Prefer EIP-1559 fields if supported by node
                  fee_history = w3.eth.fee_history(1, 'latest', [10]) # Get base fee and 10th percentile priority fee
                  base_fee = fee_history['baseFeePerGas'][-1]
                  tip = fee_history['reward'][-1][0]
                  tx_params['maxPriorityFeePerGas'] = tip
                  tx_params['maxFeePerGas'] = base_fee * 2 + tip # Example: 2x base + tip
                  logger.debug(f"Using EIP-1559 gas: maxFeePerGas={tx_params['maxFeePerGas']}, maxPriorityFeePerGas={tx_params['maxPriorityFeePerGas']}")
             except: # Fallback to legacy gasPrice if fee_history fails
                  tx_params['gasPrice'] = int(w3.eth.gas_price * 1.1) # 10% buffer
                  logger.debug(f"Using legacy gasPrice: {tx_params['gasPrice']}")
        elif 'gasPrice' in tx_params:
             logger.debug(f"Using provided legacy gasPrice: {tx_params['gasPrice']}")
        elif 'maxFeePerGas' in tx_params:
             logger.debug(f"Using provided EIP-1559 gas: maxFeePerGas={tx_params['maxFeePerGas']}, maxPriorityFeePerGas={tx_params.get('maxPriorityFeePerGas')}")


        logger.debug(f"Final TX params before signing: {tx_params}")
        signed_tx = w3.eth.account.sign_transaction(tx_params, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        logger.info(f"Transaction sent: {tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180) # 3 min timeout
        logger.info(f"Transaction confirmed in block: {receipt.blockNumber}, Status: {receipt.status}")
        return receipt
    except Exception as e:
        logger.exception(f"Transaction processing failed: {e}")
        # Consider adding revert reason fetching here if needed
        return None

def wrap_eth_to_weth(amount_wei) -> bool:
    """
    Wrap ETH to WETH by sending ETH to the WETH contract address.
    Relies on the WETH contract's receive() or fallback() function.
    """
    global w3
    if not w3 or not w3.is_connected(): raise ConnectionError("Web3 connection failed")

    try:
        account = Account.from_key(PRIVATE_KEY)
        checksum_weth_address = Web3.to_checksum_address(WETH_ADDRESS)

        logger.info(f"Attempting to wrap {Web3.from_wei(amount_wei, 'ether')} ETH for {account.address} by sending to {checksum_weth_address}")
        current_eth_balance = w3.eth.get_balance(account.address)

        # Estimate gas for a simple transfer
        gas_estimate = w3.eth.estimate_gas({'to': checksum_weth_address, 'value': amount_wei, 'from': account.address})
        # Estimate gas price (using helper logic within send_transaction now)

        # Check balance against value + estimated gas cost (rough check)
        # Note: send_transaction will handle more precise gas pricing
        gas_price_estimate = w3.eth.gas_price # Get current gas price for estimation
        estimated_cost = amount_wei + (gas_estimate * gas_price_estimate * 2) # Rough cost with buffer

        if current_eth_balance < estimated_cost:
            logger.error(f"Insufficient ETH balance ({Web3.from_wei(current_eth_balance, 'ether')}) for wrapping + gas.")
            return False

        # Prepare transaction: simple ETH transfer to WETH contract
        tx_params = {
            'from': account.address,
            'to': checksum_weth_address,
            'value': int(amount_wei),
             # nonce, chainId, gas, gasPrice/maxFee will be added by send_transaction
        }

        # Send transaction using the helper
        receipt = send_transaction(tx_params)

        if receipt and receipt.status == 1:
            logger.info(f"ETH wrapping transaction successful (tx: {receipt.transactionHash.hex()}).")
            # Optional: Wait a bit for potential state changes or events
            time.sleep(2)
            return True
        else:
            tx_hash_str = receipt.transactionHash.hex() if receipt else "N/A"
            logger.error(f"ETH wrapping transaction failed or reverted. Status: {receipt.status if receipt else 'Unknown'}. Tx: {tx_hash_str}")
            return False
    except Exception as e:
        logger.exception(f"Failed to wrap ETH to WETH: {e}")
        return False