# test/utils/fund_my_wallet.py
from web3 import Web3
import json
import requests
import os
import sys
import logging # Add logging
from pathlib import Path


# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('fund_my_wallet')

# Ensure utils can be imported (adjust path if needed)
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent # Assumes utils is in test, test is in root
sys.path.insert(0, str(project_root))
# Load web3_utils to get w3 instance initialized with correct RPC
try:
    from test.utils.web3_utils import w3, init_web3, get_contract, send_transaction
except ImportError:
     logger.critical("Could not import web3_utils. Ensure it's in the python path and correct folder structure.")
     sys.exit(1)

# Ensure Web3 is connected
if not init_web3():
    logger.critical("Web3 failed to initialize in fund_my_wallet. Exiting.")
    sys.exit(1)

RPC_URL = os.getenv('MAINNET_FORK_RPC_URL', 'http://127.0.0.1:8545')

# Destination address (Your deployer address from .env)
MY_ADDRESS = os.getenv('DEPLOYER_ADDRESS')
if not MY_ADDRESS:
     logger.critical("DEPLOYER_ADDRESS not found in environment variables (.env).")
     sys.exit(1)

# --- Whales and Tokens ---
# !!! VERIFY THESE WHALE ADDRESSES HAVE SUFFICIENT FUNDS ON ETHERSCAN MAINNET !!!
# Using different examples known to often hold funds - ALWAYS DOUBLE CHECK
WETH_WHALE = "0x2fEb1512183545f48f620C1ec108a43eB094De7a" # Example WETH whale
USDC_WHALE = "0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503" # Example USDC whale

WETH_ADDRESS = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
USDC_ADDRESS = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48" # 6 decimals

# Amounts to transfer
WETH_AMOUNT = 20  # e.g., 20 WETH
USDC_AMOUNT = 50000 # e.g., 50,000 USDC

# Convert addresses to checksum format
try:
    MY_ADDRESS = Web3.to_checksum_address(MY_ADDRESS)
    WETH_WHALE = Web3.to_checksum_address(WETH_WHALE)
    USDC_WHALE = Web3.to_checksum_address(USDC_WHALE)
    WETH_ADDRESS = Web3.to_checksum_address(WETH_ADDRESS)
    USDC_ADDRESS = Web3.to_checksum_address(USDC_ADDRESS)
except ValueError as e:
    logger.critical(f"Invalid address format found: {e}")
    sys.exit(1)

# Minimal ERC20 ABI for transfer and balanceOf
ERC20_ABI = [
    {"constant": False, "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}
]

def make_rpc_request(method, params):
    """Helper function to make JSON-RPC requests directly to Hardhat node."""
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    try:
        response = requests.post(RPC_URL, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        if 'error' in result:
            logger.error(f"RPC Error for {method}: {result['error']}")
            return None
        # logger.debug(f"RPC Response for {method}: {result.get('result')}")
        return result.get('result')
    except requests.exceptions.RequestException as e:
        logger.error(f"Error making RPC request {method}: {e}")
        return None

def impersonate_and_transfer(token_address, token_symbol, whale_address, recipient, amount_human, decimals):
    """Impersonates whale, checks balance, and transfers tokens."""
    logger.info(f"\nAttempting to transfer {amount_human} {token_symbol} from whale {whale_address[:6]}...")
    token_contract = None
    impersonation_active = False
    success = False
    try:
        token_contract = get_contract(token_address, "IERC20") # Use get_contract helper

        # 1. Impersonate account
        logger.info(f"Impersonating {token_symbol} whale {whale_address}...")
        if make_rpc_request("hardhat_impersonateAccount", [whale_address]) is None:
            logger.error(f"Failed to start impersonating whale {whale_address}.")
            return False
        impersonation_active = True

        # Give the whale some ETH for gas if needed
        whale_eth_balance = w3.eth.get_balance(whale_address)
        if whale_eth_balance < Web3.to_wei(0.1, 'ether'): # Ensure whale has at least 0.1 ETH
             logger.info(f"Setting 1 ETH balance for whale {whale_address[:6]} to cover gas...")
             set_eth_balance(whale_address, 1)

        # 2. Check Whale's Token Balance
        logger.info(f"Checking {token_symbol} balance of impersonated whale {whale_address}...")
        whale_balance_wei = token_contract.functions.balanceOf(whale_address).call()
        required_amount_wei = int(amount_human * (10 ** decimals))
        readable_balance = whale_balance_wei / (10**decimals)
        logger.info(f"Whale {token_symbol} balance: {readable_balance:.4f}, Required: {amount_human}")

        if whale_balance_wei < required_amount_wei:
            logger.error(f"Impersonated whale has insufficient {token_symbol} balance ({readable_balance:.4f})")
            return False # Failure due to balance

        # 3. Build and Send Transaction using send_transaction helper
        logger.info(f"Building & sending {token_symbol} transfer transaction...")
        transfer_func = token_contract.functions.transfer(recipient, required_amount_wei)
        tx_params = {'from': whale_address} # 'nonce', 'gas', etc., added by send_transaction

        receipt = send_transaction(transfer_func.build_transaction(tx_params))

        if receipt and receipt.status == 1:
            logger.info(f"✅ Transferred {amount_human} {token_symbol} from {whale_address[:6]}... to {recipient[:6]}... (tx: {receipt.transactionHash.hex()})")
            success = True
        else:
            logger.error(f"❌ {token_symbol} transfer transaction failed or reverted.")
            success = False

    except Exception as e:
        logger.exception(f"❌ ERROR during impersonate_and_transfer for {token_symbol}: {e}")
        success = False
    finally:
        # 4. Stop impersonating (always attempt this)
        if impersonation_active:
             logger.info(f"Stopping impersonation for {whale_address}...")
             make_rpc_request("hardhat_stopImpersonatingAccount", [whale_address])
    return success


def set_eth_balance(address, eth_amount):
    """Sets the ETH balance of an address using hardhat_setBalance."""
    logger.info(f"Setting ETH balance for {address[:6]}... to {eth_amount} ETH")
    try:
        checksum_address = Web3.to_checksum_address(address) # Ensure checksum
        hex_balance = hex(w3.to_wei(eth_amount, 'ether'))
        if make_rpc_request("hardhat_setBalance", [checksum_address, hex_balance]) is None:
            logger.error(f"❌ Failed request to set ETH balance for {checksum_address[:6]}...")
            return False
        logger.info(f"✅ ETH balance set request sent for {checksum_address[:6]}...")
        # Verify balance after setting (optional, adds slight delay)
        # time.sleep(1)
        # new_balance = w3.eth.get_balance(checksum_address)
        # logger.info(f"   New balance confirmed: {w3.from_wei(new_balance, 'ether')} ETH")
        return True
    except Exception as e:
        logger.exception(f"❌ ERROR setting ETH balance for {address[:6]}: {e}")
        return False

# --- Main Execution ---
logger.info("\n--- Funding Deployer Wallet ---")
overall_success = True

# 1. Set Deployer's ETH balance
if not set_eth_balance(MY_ADDRESS, 100): # Set 100 ETH for deployer
     overall_success = False
     logger.warning("Could not set deployer ETH balance, subsequent steps might fail.")

# 2. Transfer WETH from Whale to Deployer
weth_success = impersonate_and_transfer(WETH_ADDRESS, "WETH", WETH_WHALE, MY_ADDRESS, WETH_AMOUNT, 18)
if not weth_success:
     logger.error("!!!!!!!!!!!!!!!! WETH Funding Failed !!!!!!!!!!!!!!!!")
     overall_success = False

# 3. Transfer USDC from Whale to Deployer
usdc_success = impersonate_and_transfer(USDC_ADDRESS, "USDC", USDC_WHALE, MY_ADDRESS, USDC_AMOUNT, 6)
if not usdc_success:
     logger.error("!!!!!!!!!!!!!!!! USDC Funding Failed !!!!!!!!!!!!!!!!")
     overall_success = False


# --- Final Status ---
if overall_success:
    logger.info("\n--- Wallet Funding Script Finished Successfully ---")
    sys.exit(0) # Exit with success code
else:
    logger.error("\n--- Wallet Funding Script Finished with Errors ---")
    sys.exit(1) # Exit with error code