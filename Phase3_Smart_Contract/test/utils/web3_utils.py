# web3_utils.py

import os
import json
import logging
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
from pathlib import Path

# --- Logging Setup ---
logger = logging.getLogger('web3_utils')

# --- Load Environment Variables ---
load_dotenv()
PRIVATE_KEY = os.getenv('PRIVATE_KEY')
# --- Use a specific ENV VAR for the local fork RPC ---
# Set MAINNET_FORK_RPC_URL=http://127.0.0.1:8545 in your .env or environment
RPC_URL = os.getenv('MAINNET_FORK_RPC_URL', 'http://127.0.0.1:8545') # Default to localhost

# --- Web3 Initialization ---
w3 = None
def init_web3():
    """Initialize Web3 connection and validate environment."""
    global w3
    if w3 and w3.is_connected():
        return True

    if not RPC_URL:
        logger.error("RPC_URL (for fork) not found or set.")
        return False

    w3 = Web3(Web3.HTTPProvider(RPC_URL))

    if not w3.is_connected():
        logger.error(f"Failed to connect to RPC URL: {RPC_URL}")
        w3 = None
        return False

    if not PRIVATE_KEY:
        logger.error("PRIVATE_KEY not found in environment variables")
        w3 = None
        return False

    try:
        chain_id = w3.net.version
        logger.info(f"Connected to network via {RPC_URL} - Chain ID: {chain_id}")
    except Exception as e:
        logger.error(f"Error getting chain ID from {RPC_URL}: {e}")
        w3 = None
        return False
    return True

# --- Standard IERC20 ABI (Minimal, covers balanceOf, decimals, transfer, etc.) ---
IERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
        "stateMutability": "view"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
        "stateMutability": "view"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
        "stateMutability": "nonpayable"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
        "stateMutability": "view"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
        "stateMutability": "view"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
        "stateMutability": "view"
    }
]

# --- WETH ABI (Minimal, only deposit function) ---
WETH_ABI = [
    {
        "constant": False,
        "inputs": [],
        "name": "deposit",
        "outputs": [],
        "payable": True,
        "stateMutability": "payable",
        "type": "function"
    }
]

# --- Mainnet WETH Address ---
WETH_ADDRESS = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2" # Mainnet WETH

def load_contract_abi(contract_name):
    """Load a contract ABI from artifacts directory."""
    if contract_name == "IERC20":
        return IERC20_ABI

    # Adjusted path finding relative to this file's location
    # Assumes web3_utils.py is inside a 'utils' folder, which is inside the 'tests' folder
    # Project Root -> tests -> utils -> web3_utils.py
    # We need to go up three levels to reach the project root where 'artifacts' should be.
    base_path = Path(__file__).resolve().parent.parent.parent # Goes up to project root

    # Define possible locations relative to the project root
    possible_paths = [
        base_path / f'artifacts/contracts/{contract_name}.sol/{contract_name}.json',
        base_path / f'artifacts/contracts/interfaces/{contract_name}.sol/{contract_name}.json',
        # Add other potential paths based on your project structure if needed
        base_path / f'artifacts/@uniswap/v3-core/contracts/interfaces/{contract_name}.sol/{contract_name}.json',
        base_path / f'artifacts/@uniswap/v3-periphery/contracts/interfaces/{contract_name}.sol/{contract_name}.json',
    ]

    for path in possible_paths:
        if path.exists():
            logger.debug(f"Loading ABI for {contract_name} from: {path}")
            with open(path) as f:
                try:
                    contract_json = json.load(f)
                    if 'abi' not in contract_json:
                        logger.error(f"ABI key not found in {path}")
                        continue # Try next path
                    return contract_json['abi']
                except json.JSONDecodeError:
                    logger.error(f"Error decoding JSON from {path}")
                    continue # Try next path
                
    raise FileNotFoundError(f"ABI not found for {contract_name} in any expected path relative to {base_path}")

def get_contract(address, contract_name):
    """Get contract instance with loaded ABI."""
    global w3
    if not w3 or not w3.is_connected():
        # Attempt to initialize if not already connected
        if not init_web3():
            raise ConnectionError("Web3 not initialized or connection failed")

    if not address:
        raise ValueError(f"Address for {contract_name} not provided")

    try:
        checksum_address = Web3.to_checksum_address(address)
        abi = load_contract_abi(contract_name)
        return w3.eth.contract(address=checksum_address, abi=abi)
    except ValueError as ve:
        logger.error(f"Invalid address format for {contract_name}: {address} - {ve}")
        raise
    except FileNotFoundError as fnf:
        logger.error(f"ABI file error for {contract_name}: {fnf}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error getting contract {contract_name} at {address}: {e}")
        raise

def send_transaction(tx_params):
    """Send a transaction and wait for receipt."""
    global w3
    if not w3 or not w3.is_connected():
        raise ConnectionError("Web3 not initialized or connection failed")
        
    try:
        # Ensure chainId is present, defaulting to the connected network's ID
        if 'chainId' not in tx_params:
            tx_params['chainId'] = int(w3.net.version)

        # Estimate gas if not provided
        if 'gas' not in tx_params:
            try:
                tx_params['gas'] = w3.eth.estimate_gas(tx_params)
                logger.debug(f"Estimated gas: {tx_params['gas']}")
            except Exception as gas_err:
                logger.error(f"Gas estimation failed: {gas_err}. Using default 1,000,000.")
                tx_params['gas'] = 1000000 # Fallback gas limit

        # حذف افزودن gasPrice برای سازگاری با web3.py v6+
        # if 'gasPrice' not in tx_params:
        #     tx_params['gasPrice'] = w3.eth.gas_price
        #     logger.debug(f"Using network gas price: {tx_params['gasPrice']}")

        logger.debug(f"Signing transaction: {tx_params}")
        signed_tx = w3.eth.account.sign_transaction(tx_params, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        logger.info(f"Transaction sent: {tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        logger.info(f"Transaction confirmed in block: {receipt.blockNumber}, Status: {receipt.status}")
        return receipt
    except Exception as e:
        logger.error(f"Transaction failed: {str(e)}")
        # Try to get more info if revert
        if 'revert' in str(e):
            try:
                # Remove gas/nonce for call
                call_tx = tx_params.copy()
                call_tx.pop('gas', None)
                call_tx.pop('gasPrice', None)
                call_tx.pop('nonce', None)
                revert_reason = w3.eth.call(call_tx, 'latest') # Check on latest block
                logger.error(f"Revert reason (from eth_call): {revert_reason.hex()}")
            except Exception as call_err:
                logger.error(f"Could not get revert reason via eth_call: {call_err}")
        return None

def wrap_eth_to_weth(amount_wei):
    """Wrap ETH to WETH by calling deposit on WETH contract."""
    global w3
    if not w3 or not w3.is_connected():
        raise ConnectionError("Web3 not initialized or connection failed")

    try:
        account = Account.from_key(PRIVATE_KEY)
        # Ensure WETH_ADDRESS is checksummed
        checksum_weth_address = Web3.to_checksum_address(WETH_ADDRESS)
        weth = w3.eth.contract(address=checksum_weth_address, abi=WETH_ABI + IERC20_ABI) # Add IERC20 for balance check etc.

        logger.info(f"Attempting to wrap {Web3.from_wei(amount_wei, 'ether')} ETH for account {account.address}")
        current_eth_balance = w3.eth.get_balance(account.address)
        if current_eth_balance < amount_wei:
            logger.error(f"Insufficient ETH balance ({Web3.from_wei(current_eth_balance, 'ether')}) to wrap {Web3.from_wei(amount_wei, 'ether')}")
            return False

        tx_params = {
            'from': account.address,
            'to': checksum_weth_address, # Use checksummed address
            'value': int(amount_wei),
            'nonce': w3.eth.get_transaction_count(account.address),
            # Gas/GasPrice will be handled by send_transaction
            'chainId': int(w3.net.version),
            'data': weth.encodeABI(fn_name='deposit') # Encode function call
        }

        receipt = send_transaction(tx_params)

        if receipt and receipt.status == 1:
            logger.info("ETH successfully wrapped to WETH.")
            return True
        else:
            logger.error("Failed to wrap ETH to WETH. Transaction reverted or failed.")
            return False
    except Exception as e:
        logger.error(f"Failed to wrap ETH to WETH: {e}")
        return False