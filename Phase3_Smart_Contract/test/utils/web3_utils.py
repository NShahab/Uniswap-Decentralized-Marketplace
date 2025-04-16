"""Shared Web3 utilities for interacting with contracts."""

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
RPC_URL = os.getenv('SEPOLIA_RPC_URL')

# --- Web3 Initialization ---
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# --- Standard IERC20 ABI ---
# Updated IERC20_ABI in web3_utils.py
IERC20_ABI = [
    # Balance check
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    # Approve
    {
        "constant": False,
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # Transfer
    {
        "constant": False,
        "inputs": [
            {"name": "recipient", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # Decimals
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    }
]

# --- WETH ABI for deposit ---
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

WETH_ADDRESS = "0x7b79995e5f793A07Bc00c21412e50Ecae098E7f9"  # Sepolia WETH

def init_web3():
    """Initialize Web3 connection and validate environment."""
    if not w3.is_connected():
        logger.error(f"Failed to connect to RPC URL: {RPC_URL}")
        return False
        
    if not PRIVATE_KEY:
        logger.error("PRIVATE_KEY not found in environment variables")
        return False
        
    logger.info(f"Connected to network ID: {w3.net.version}")
    return True

def load_contract_abi(contract_name):
    """Load a contract ABI from artifacts directory."""
    # Special case for IERC20 - use our standard ABI
    if contract_name == "IERC20":
        return IERC20_ABI
        
    # Path to the Phase3_Smart_Contract directory
    base_path = Path(__file__).parent.parent.parent
    
    # Common paths where ABIs might be found
    possible_paths = [
        base_path / 'artifacts/contracts/interfaces' / f'{contract_name}.sol' / f'{contract_name}.json',
        base_path / 'artifacts/contracts' / f'{contract_name}.sol' / f'{contract_name}.json',
        base_path / 'artifacts/@openzeppelin/contracts/token/ERC20' / f'{contract_name}.sol' / f'{contract_name}.json',
        base_path / 'artifacts/@uniswap/v3-core/contracts/interfaces' / f'{contract_name}.sol' / f'{contract_name}.json',
        base_path / 'artifacts/@uniswap/v3-periphery/contracts/interfaces' / f'{contract_name}.sol' / f'{contract_name}.json'
    ]
    
    for path in possible_paths:
        if path.exists():
            with open(path) as f:
                contract_json = json.load(f)
                return contract_json['abi']
                
    raise FileNotFoundError(f"ABI not found for {contract_name} in any expected path")

def get_contract(address, contract_name):
    """Get contract instance with loaded ABI."""
    if not w3.is_connected():
        raise ConnectionError("Web3 not initialized")
    
    if not address:
        raise ValueError(f"Address for {contract_name} not provided")
        
    abi = load_contract_abi(contract_name)
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)

def send_transaction(tx_params):
    """Send a transaction and wait for receipt."""
    try:
        signed_tx = w3.eth.account.sign_transaction(tx_params, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        return receipt
    except Exception as e:
        logger.error(f"Transaction failed: {str(e)}")
        return None

def wrap_eth_to_weth(amount_wei):
    """Wrap ETH to WETH by calling deposit on WETH contract."""
    try:
        account = Account.from_key(PRIVATE_KEY)
        weth = w3.eth.contract(address=WETH_ADDRESS, abi=WETH_ABI)
        tx = weth.functions.deposit().build_transaction({
            'from': account.address,
            'value': int(amount_wei),
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 100000,
            'gasPrice': w3.eth.gas_price,
            'chainId': int(w3.net.version)
        })
        signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        logger.info(f"Wrapping ETH to WETH, tx hash: {tx_hash.hex()}")
        w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        logger.info("ETH successfully wrapped to WETH.")
        return True
    except Exception as e:
        logger.error(f"Failed to wrap ETH to WETH: {e}")
        return False