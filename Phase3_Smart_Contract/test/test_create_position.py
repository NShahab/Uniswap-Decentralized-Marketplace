# -*- coding: utf-8 -*-
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
import math

# --- Constants ---
USDC_DECIMALS = 6
WETH_DECIMALS = 18
TICK_ADJUSTMENT_THRESHOLD = 0 # Adjust only if ticks differ
UINT256_MAX = 2**256 - 1
MIN_TICK = -887272
MAX_TICK = 887272
# Constants for minimum token balances
MIN_WETH_BALANCE = Web3.to_wei(0.01, 'ether')  # 0.01 WETH minimum
MIN_USDC_BALANCE = 10 * (10**USDC_DECIMALS)    # 10 USDC minimum
# Constants for tick calculation (approximations)
LOG_1_0001 = math.log(1.0001)
TWO_POW_96 = 2**96
TWO_POW_192 = 2**192
ONE_E12 = 10**12
ONE_E18 = 10**18
ONE_E36 = 10**36


# --- Logging Setup ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# General logger
logger = logging.getLogger('main_logger')
logger.setLevel(logging.INFO)
# File handler
file_handler = logging.FileHandler('position_management.log')
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)
# Stream handler (console)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)
logger.addHandler(stream_handler)

# Separate logger for CSV saving issues if needed
csv_logger = logging.getLogger('csv_logger')
# ... (configure csv_logger if needed) ...

# File handler for error logs
error_file_handler = logging.FileHandler('error.log')
error_file_handler.setFormatter(log_formatter)
error_logger = logging.getLogger('error_logger')
error_logger.setLevel(logging.ERROR)
error_logger.addHandler(error_file_handler)

# --- Environment Variable Loading ---
load_dotenv()
PREDICTIVE_MANAGER_ADDRESS = os.getenv('PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS')
BASELINE_MANAGER_ADDRESS = os.getenv('BASELINE_MINIMAL_ADDRESS') # Ensure this matches .env after Baseline deploy
USDC_ADDRESS = os.getenv('USDC_ADDRESS')
WETH_ADDRESS = os.getenv('WETH_ADDRESS')
PRIVATE_KEY = os.getenv('PRIVATE_KEY')
RPC_URL = os.getenv('SEPOLIA_RPC_URL')
PREDICTION_API_URL = os.getenv('PREDICTION_API_URL')

# --- Web3 Initialization ---
w3 = None
try:
    w3 = Web3(Web3.HTTPProvider(RPC_URL))

    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect to RPC URL: {RPC_URL}")

    w3.eth.account.enable_unaudited_hdwallet_features()

    # Validate and checksum addresses
    if PREDICTIVE_MANAGER_ADDRESS:
        PREDICTIVE_MANAGER_ADDRESS = w3.to_checksum_address(PREDICTIVE_MANAGER_ADDRESS)
    else:
        logger.warning("PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS not found in .env")
    if BASELINE_MANAGER_ADDRESS:
        BASELINE_MANAGER_ADDRESS = w3.to_checksum_address(BASELINE_MANAGER_ADDRESS)
    else:
        logger.warning("BASELINE_MINIMAL_ADDRESS not found in .env")
    if USDC_ADDRESS:
        USDC_ADDRESS = w3.to_checksum_address(USDC_ADDRESS)
    else:
        logger.error("USDC_ADDRESS not found in .env")
    if WETH_ADDRESS:
        WETH_ADDRESS = w3.to_checksum_address(WETH_ADDRESS)
    else:
        logger.error("WETH_ADDRESS not found in .env")

    logger.info(f"Connected to network ID: {w3.net.version}")
    logger.info(f"Using Predictive contract: {PREDICTIVE_MANAGER_ADDRESS}")
    logger.info(f"Using Baseline contract: {BASELINE_MANAGER_ADDRESS}")
    logger.info(f"USDC: {USDC_ADDRESS} (Decimals: {USDC_DECIMALS})")
    logger.info(f"WETH: {WETH_ADDRESS} (Decimals: {WETH_DECIMALS})")

except Exception as e:
    logger.critical(f"Error initializing Web3: {str(e)}", exc_info=True)
    w3 = None

# --- Global Cache for ABIs and Contract Objects ---
# Avoid reloading ABI/creating objects repeatedly
abi_cache = {}
contract_cache = {}
contract_params_cache = {} # Cache for tickSpacing etc.

# --- Function to Load ABI (Improved Error Handling) ---
def load_contract_abi(contract_name):
    possible_paths = []  # Initialize possible_paths to avoid UnboundLocalError
    
    try:
        if contract_name == "IERC20":
            artifact_path = "artifacts/contracts/interfaces/IERC20.sol/IERC20.json"
        elif contract_name == "IUniswapV3Pool":
            artifact_path = "artifacts/@uniswap/v3-core/contracts/interfaces/IUniswapV3Pool.sol/IUniswapV3Pool.json"
        elif contract_name == "IUniswapV3Factory":
            artifact_path = "artifacts/@uniswap/v3-core/contracts/interfaces/IUniswapV3Factory.sol/IUniswapV3Factory.json"
        elif contract_name == "PredictiveLiquidityManager":
            artifact_path = "artifacts/contracts/PredictiveLiquidityManager.sol/PredictiveLiquidityManager.json"
        elif contract_name == "BaselineMinimal":
            artifact_path = "artifacts/contracts/BaselineMinimal.sol/BaselineMinimal.json"
        else:
            possible_paths = [
                f'artifacts/contracts/interfaces/{contract_name}.sol/{contract_name}.json',
                f'artifacts/contracts/{contract_name}.sol/{contract_name}.json',
                f'artifacts/{contract_name}.json',
                f'abis/{contract_name}.json'
            ]

        if 'artifact_path' in locals():
            logger.info(f"Loading ABI from: {artifact_path}")
            with open(artifact_path, 'r') as f:
                contract_json = json.load(f)
                if 'abi' not in contract_json:
                    raise ValueError(f"ABI key not found in {artifact_path}")
                abi = contract_json['abi']
                abi_cache[contract_name] = abi
                return abi
        else:
            # Try finding by directory if structure is different
            base_artifact_dir = 'artifacts/contracts'
            sol_file_name = f"{contract_name}.sol"
            possible_dir = os.path.join(base_artifact_dir, sol_file_name)
            if os.path.isdir(possible_dir):
                json_file = os.path.join(possible_dir, f"{contract_name}.json")
                possible_paths.insert(0, json_file)

            for path in possible_paths:
                if os.path.exists(path):
                    logger.info(f"Loading ABI from: {path}")
                    with open(path, 'r') as f:
                        contract_json = json.load(f)
                        if 'abi' not in contract_json:
                            continue
                        abi = contract_json['abi']
                        abi_cache[contract_name] = abi
                        return abi

        # If no ABI found
        error_logger.error(f"ABI file for '{contract_name}' not found in any expected paths: {possible_paths}")
        raise FileNotFoundError(f"ABI file for '{contract_name}' not found in any expected paths: {possible_paths}")

    except Exception as e:
        error_logger.error(f"Error loading ABI for {contract_name}: {str(e)}")
        raise

# --- Function to Get Contract Object (Caching) ---
def get_contract(contract_address, contract_name):
     """Gets a web3 contract object, using cache if possible."""
     if not w3: raise ConnectionError("Web3 not initialized")
     if not contract_address: raise ValueError(f"Address for {contract_name} not provided")

     cache_key = f"{contract_name}_{contract_address}"
     if cache_key in contract_cache:
          return contract_cache[cache_key]

     try:
          abi = load_contract_abi(contract_name)
          contract_obj = w3.eth.contract(address=contract_address, abi=abi)
          contract_cache[cache_key] = contract_obj
          return contract_obj
     except Exception as e:
          logger.error(f"Failed to create contract object for {contract_name} at {contract_address}: {e}")
          raise


# --- Function to Get Contract Parameters (Caching) ---
def get_contract_params(contract_address, contract_name, is_baseline):
    """Fetches and caches necessary parameters like tickSpacing."""
    cache_key = f"params_{contract_name}_{contract_address}"
    if cache_key in contract_params_cache:
        return contract_params_cache[cache_key]

    try:
        contract = get_contract(contract_address, contract_name)
        params = {}
        params['tickSpacing'] = contract.functions.tickSpacing().call()
        if not is_baseline:
            # Predictive specific params
            params['token0Decimals'] = contract.functions.token0Decimals().call()
            params['token1Decimals'] = contract.functions.token1Decimals().call()
            params['rangeWidthMultiplier'] = contract.functions.rangeWidthMultiplier().call()
        else:
             # Baseline uses global constants or could fetch if needed
             params['token0Decimals'] = USDC_DECIMALS
             params['token1Decimals'] = WETH_DECIMALS


        if params['tickSpacing'] <= 0:
            raise ValueError(f"Invalid tickSpacing ({params['tickSpacing']}) read from {contract_name}")

        contract_params_cache[cache_key] = params
        logger.info(f"Fetched params for {contract_name}: {params}")
        return params
    except Exception as e:
        logger.error(f"Failed to get parameters for {contract_name} at {contract_address}: {e}")
        raise # Re-raise


# --- Function to Get Predicted Price (Unchanged) ---
def get_predicted_price():
    """Get the predicted ETH price from API or use a fallback"""
    logger.info("Fetching predicted price...")
    # Try custom API
    if PREDICTION_API_URL:
        try:
            response = requests.get(PREDICTION_API_URL, timeout=10)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            data = response.json()
            price = data.get('predicted_price')
            if price is not None:
                price = float(price)
                logger.info(f"Custom API predicted ETH price: {price} USD")
                return {"original": price}
            else:
                logger.warning(f"Key 'predicted_price' not found or null in custom API response: {data}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error getting price from custom API ({PREDICTION_API_URL}): {e}")
        except Exception as e:
            logger.warning(f"Error processing custom API response: {e}")
    else:
        logger.warning("PREDICTION_API_URL not set in .env file")

    # Fallback: Coinbase API
    try:
        logger.info("Falling back to Coinbase API")
        response = requests.get('https://api.coinbase.com/v2/prices/ETH-USD/spot', timeout=10)
        response.raise_for_status()
        data = response.json()
        price = float(data['data']['amount'])
        logger.info(f"Coinbase API ETH price: {price} USD")
        return {"original": price}
    except requests.exceptions.RequestException as e:
        logger.warning(f"Error getting price from Coinbase: {e}")
    except Exception as e:
        logger.warning(f"Error processing Coinbase response: {e}")

    # Final fallback
    fallback_price = 3000.0 # Updated fallback ETH/USDC price example
    logger.warning(f"Using fallback price: {fallback_price} USD")
    return {"original": fallback_price}


# --- Functions for Balance Check & Sending Tokens (Unchanged) ---
def check_token_balances(is_baseline=False):
    """Check token balances in contract and return detailed status."""
    if not w3:
        return False, False, 0, 0

    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_type = "Baseline" if is_baseline else "Predictive"

    if not contract_address:
        return False, False, 0, 0

    try:
        erc20_abi = load_contract_abi("IERC20")  # Assume a generic IERC20 ABI file exists
        weth_contract = w3.eth.contract(address=WETH_ADDRESS, abi=erc20_abi)
        usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=erc20_abi)

        weth_balance = weth_contract.functions.balanceOf(contract_address).call()
        usdc_balance = usdc_contract.functions.balanceOf(contract_address).call()

        logger.info(f"{contract_type} contract balance: {w3.from_wei(weth_balance, 'ether')} WETH, {usdc_balance / (10**USDC_DECIMALS)} USDC")

        has_enough_weth = weth_balance >= MIN_WETH_BALANCE
        has_enough_usdc = usdc_balance >= MIN_USDC_BALANCE

        return has_enough_weth, has_enough_usdc, weth_balance, usdc_balance

    except Exception as e:
        logger.error(f"Error checking token balances for {contract_type}: {e}")
        return False, False, 0, 0

def send_tokens_to_contract(is_baseline=False):
    if not w3: logger.error("Web3 not initialized"); return False
    if not PRIVATE_KEY: logger.error("PRIVATE_KEY not set"); return False

    account = Account.from_key(PRIVATE_KEY)
    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_type = "Baseline" if is_baseline else "Predictive"
    chain_id = int(w3.net.version)
    
    if not contract_address: 
        logger.error(f"{contract_type} address not set"); 
        return False

    # Check account balance first
    account_balance = w3.eth.get_balance(account.address)
    if account_balance < Web3.to_wei(0.03, 'ether'):
        logger.error(f"Insufficient ETH balance in account: {w3.from_wei(account_balance, 'ether')} ETH")
        return False

    has_enough_weth, has_enough_usdc, _, _ = check_token_balances(is_baseline)

    if (is_baseline and has_enough_weth) or (not is_baseline and has_enough_weth and has_enough_usdc):
        logger.info(f"{contract_type} contract appears to have sufficient funds.")
        return True

    logger.info(f"Attempting to fund {contract_type} contract...")
    try:
        gas_price = w3.eth.gas_price
        nonce = w3.eth.get_transaction_count(account.address)

        if is_baseline:
            eth_to_send = Web3.to_wei(0.02, 'ether')
            logger.info(f"Sending {w3.from_wei(eth_to_send, 'ether')} ETH to Baseline contract...")
            
            tx = {
                'chainId': chain_id,
                'to': contract_address,
                'value': eth_to_send,
                'gas': 100000,
                'maxFeePerGas': int(gas_price * 2),  # Double the base fee
                'maxPriorityFeePerGas': int(gas_price * 0.5),  # 50% of base fee as priority fee
                'nonce': nonce,
                'from': account.address,
                'type': 2  # EIP-1559 transaction
            }
            
            try:
                estimated_gas = w3.eth.estimate_gas(tx)
                tx['gas'] = int(estimated_gas * 1.5)  # 50% buffer
                logger.info(f"Estimated gas for ETH transfer: {estimated_gas}")
            except Exception as e:
                logger.warning(f"Gas estimation failed: {e}. Using default gas limit.")
            
            signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            logger.info(f"ETH transfer tx sent: {tx_hash.hex()}")
            
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            if receipt.status != 1:
                logger.error(f"ETH transfer failed. Receipt: {receipt}")
                return False
            logger.info(f"ETH transfer successful. Gas used: {receipt.gasUsed}")
            time.sleep(2)  # Wait for state to update
            return True

        else:
            # ... existing WETH/USDC handling for Predictive ...
            pass

    except Exception as e:
        logger.error(f"Error in send_tokens_to_contract: {str(e)}", exc_info=True)
        return False

# --- Python Helper Functions for Tick Calculations (REFINED) ---

def isqrt(n: int) -> int:
    """Integer square root (returns floor(sqrt(n)))."""
    if n < 0: raise ValueError("isqrt() argument must be non-negative")
    if n == 0: return 0
    x = int(n**0.5)
    if (x + 1)**2 <= n:
        x += 1
    if x * x > n:
        x -= 1
    return x

def get_tick_at_sqrt_ratio_py(sqrt_ratio_x96: int) -> int:
    """Python equivalent of TickMath.getTickAtSqrtRatio."""
    if sqrt_ratio_x96 <= 0: return MIN_TICK # Handle edge case

    try:
        # Convert Q96 sqrt ratio to float sqrt ratio
        sqrt_ratio = sqrt_ratio_x96 / TWO_POW_96
        # tick = log_{sqrt(1.0001)}(sqrt_ratio) = ln(sqrt_ratio) / ln(sqrt(1.0001))
        tick = math.log(sqrt_ratio) / (0.5 * LOG_1_0001)
        tick_int = int(math.floor(tick))
        # Clamp to Solidity's MIN/MAX_TICK
        return max(MIN_TICK, min(MAX_TICK, tick_int))
    except (ValueError, OverflowError, ZeroDivisionError) as e:
        logger.error(f"Error in get_tick_at_sqrt_ratio_py for sqrt_ratio_x96={sqrt_ratio_x96}: {e}")
        # Return an boundary value on error
        return MIN_TICK if sqrt_ratio_x96 < TWO_POW_96 else MAX_TICK # Crude guess


def price_to_tick_predictive_py(price_token0_token1: float, token0_decimals: int, token1_decimals: int) -> int:
    """
    Python equivalent of PredictiveLiquidityManager._priceToTick.
    Takes price like ETH/USDC (token0/token1).
    Returns the calculated center tick.
    """
    if price_token0_token1 <= 0:
        logger.error("Input price must be positive")
        return MIN_TICK # Or raise error

    try:
        # Contract expects price scaled by 10**(dec1-dec0)
        # Let's calculate that scaled price first
        scale_factor = 1
        if token1_decimals >= token0_decimals:
             scale_factor = 10**(token1_decimals - token0_decimals)
        else:
             scale_factor = 1 / (10**(token0_decimals - token1_decimals)) # Should be int division? No, use float

        # This is the value the contract *receives*
        price_decimal_input = price_token0_token1 * scale_factor

        # Now, replicate the contract's internal logic with this input
        # It seems the contract's internal logic might be flawed or expect a different input format
        # based on the overflow analysis. Let's directly calculate sqrtPriceX96 from the desired price.

        # We want price of token1 in terms of token0 for Uniswap calculations
        # e.g., WETH/USDC
        price_t1_t0 = 1.0 / price_token0_token1

        # Account for decimals to get the raw ratio
        # ratio = price_t1_t0 * 10**(token1_decimals) / 10**(token0_decimals)
        ratio = price_t1_t0 * (10**(token1_decimals - token0_decimals))

        # Calculate sqrtPriceX96 = sqrt(ratio) * 2^96
        if ratio < 0: raise ValueError("Negative ratio calculated")
        sqrt_ratio_x96 = int(math.sqrt(ratio) * TWO_POW_96)

        # Check Uniswap bounds for sqrtPriceX96 (approximate)
        MIN_SQRT_RATIO = 4295128739
        MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342
        if not (MIN_SQRT_RATIO <= sqrt_ratio_x96 <= MAX_SQRT_RATIO):
            logger.warning(f"Calculated sqrtPriceX96 {sqrt_ratio_x96} outside Uniswap bounds")
            sqrt_ratio_x96 = max(MIN_SQRT_RATIO, min(MAX_SQRT_RATIO, sqrt_ratio_x96))


        # Convert sqrtPriceX96 to tick
        predicted_tick = get_tick_at_sqrt_ratio_py(sqrt_ratio_x96)
        logger.info(f"Calculated predicted_tick (Python): {predicted_tick} for price {price_token0_token1}")
        return predicted_tick

    except Exception as e:
        logger.error(f"Error in price_to_tick_predictive_py for price {price_token0_token1}: {e}")
        return -1 # Indicate error

def floor_to_tick_spacing_py(tick: int, tick_spacing: int) -> int:
    """Python equivalent of floorToTickSpacing."""
    if tick_spacing <= 0: return tick # Avoid division by zero
    compressed = tick // tick_spacing
    if tick < 0 and (tick % tick_spacing != 0):
        compressed -= 1
    return compressed * tick_spacing

def calculate_ticks_predictive_py(target_center_tick: int, tick_spacing: int, range_width_multiplier: int) -> tuple[int, int]:
    """Python equivalent of PredictiveLiquidityManager._calculateTicks."""
    if tick_spacing <= 0 or range_width_multiplier <= 0:
        logger.error("Invalid tick_spacing or range_width_multiplier")
        return -1, -1

    try:
        # Calculate half width (integer math)
        half_width = (tick_spacing * range_width_multiplier) // 2
        if half_width <= 0: half_width = tick_spacing

        # Ensure half width is multiple of tick spacing
        half_width = (half_width // tick_spacing) * tick_spacing
        if half_width == 0: half_width = tick_spacing # Should not happen if rangeWidthMultiplier > 0

        # Raw boundaries
        raw_tick_lower = target_center_tick - half_width
        raw_tick_upper = target_center_tick + half_width

        # Align with tick spacing
        tick_lower = floor_to_tick_spacing_py(raw_tick_lower, tick_spacing)
        tick_upper = floor_to_tick_spacing_py(raw_tick_upper, tick_spacing)

        # Adjust upper tick if not aligned properly by floor
        if (raw_tick_upper % tick_spacing) != 0 and tick_upper < MAX_TICK:
             if tick_upper <= MAX_TICK - tick_spacing:
                tick_upper += tick_spacing
             else:
                 tick_upper = floor_to_tick_spacing_py(MAX_TICK, tick_spacing)

        # Ensure upper > lower
        if tick_lower >= tick_upper:
            tick_upper = tick_lower + tick_spacing

        # Ensure ticks are within global range (and aligned)
        tick_lower = max(floor_to_tick_spacing_py(MIN_TICK, tick_spacing), tick_lower)
        tick_upper = min(floor_to_tick_spacing_py(MAX_TICK, tick_spacing), tick_upper)

        # If clamping caused lower >= upper, adjust
        if tick_lower >= tick_upper:
            tick_lower = tick_upper - tick_spacing
            tick_lower = max(floor_to_tick_spacing_py(MIN_TICK, tick_spacing), tick_lower)

        # Final safety check
        if tick_lower >= tick_upper:
             logger.error("Predictive Tick calculation failed (Python): lower >= upper after all adjustments")
             tick_lower = floor_to_tick_spacing_py(target_center_tick - tick_spacing, tick_spacing)
             tick_upper = floor_to_tick_spacing_py(target_center_tick + tick_spacing, tick_spacing)
             if tick_lower >= tick_upper: tick_upper = tick_lower + tick_spacing
             tick_lower = max(floor_to_tick_spacing_py(MIN_TICK, tick_spacing), tick_lower)
             tick_upper = min(floor_to_tick_spacing_py(MAX_TICK, tick_spacing), tick_upper)
             if tick_lower >= tick_upper: return -1, -1

        logger.info(f"Calculated Predictive Ticks (Python): Lower={tick_lower}, Upper={tick_upper}")
        return tick_lower, tick_upper

    except Exception as e:
        logger.error(f"Error calculating predictive tick range in Python: {e}", exc_info=True)
        return -1, -1

# Baseline calculation uses a simpler fixed width, already implemented in its own helper

# --- Function to Extract Event Data (Refined) ---
def get_contract_event_data(receipt, contract_address, contract_abi, is_baseline=False):
    """Extracts and consolidates event data from a transaction receipt."""
    processed_logs = []
    all_event_data = {'tx_hash': receipt.get('transactionHash', b'').hex()} # Start with tx hash

    try:
        event_abis = [abi for abi in contract_abi if abi['type'] == 'event']
        event_signatures = { w3.keccak(text=Web3.get_abi_event_signature(abi)).hex(): abi for abi in event_abis }

        for log in receipt.get('logs', []):
             # Check address and if topic0 matches a known event
             if log['address'] == contract_address and log['topics'] and log['topics'][0].hex() in event_signatures:
                event_abi = event_signatures[log['topics'][0].hex()]
                try:
                    event_data = w3.eth.codec.decode_log(event_abi, log['data'], log['topics'][1:])
                    event_name = event_abi['name']
                    processed_logs.append({'name': event_name, 'data': event_data})
                    # logger.info(f"Decoded event: {event_name} with data: {event_data}") # Verbose
                except Exception as e:
                    logger.warning(f"Could not decode log for event {event_abi.get('name', 'Unknown')}: {e}")

    except Exception as e:
        logger.error(f"Error processing logs in receipt: {e}", exc_info=True)
        return all_event_data # Return basic info

    # --- Consolidate Data ---
    final_data = all_event_data.copy()

    # 1. Adjustment Metrics (Baseline or Predictive)
    adj_metrics_event_name = 'BaselineAdjustmentMetrics' if is_baseline else 'PredictionAdjustmentMetrics'
    adj_metrics_event = next((log['data'] for log in processed_logs if log['name'] == adj_metrics_event_name), None)
    if adj_metrics_event:
        final_data.update(adj_metrics_event)
        # Standardize tick keys
        final_data['finalTickLower'] = adj_metrics_event.get('targetTickLower', adj_metrics_event.get('finalTickLower'))
        final_data['finalTickUpper'] = adj_metrics_event.get('targetTickUpper', adj_metrics_event.get('finalTickUpper'))
        # Remove potentially duplicate keys
        for k in ['targetTickLower', 'targetTickUpper']: final_data.pop(k, None)
        logger.info(f"Processed {adj_metrics_event_name}")

    # 2. Liquidity Info (Prioritize specific events)
    minted_event = next((log['data'] for log in processed_logs if log['name'] == 'PositionMinted'), None) # Baseline specific
    state_changed_event = next((log['data'] for log in processed_logs if log['name'] == 'PositionStateChanged'), None) # Baseline specific
    liq_op_event = next((log['data'] for log in processed_logs if log['name'] == 'LiquidityOperation'), None) # Predictive specific

    if minted_event:
        final_data['liquidity'] = minted_event.get('liquidity', 0)
        # Update ticks from mint event if more precise or missing
        final_data.setdefault('finalTickLower', minted_event.get('tickLower'))
        final_data.setdefault('finalTickUpper', minted_event.get('tickUpper'))
        logger.info("Liquidity found in PositionMinted")
    elif state_changed_event and state_changed_event.get('hasPosition', False):
         if 'liquidity' not in final_data or final_data.get('liquidity') == 0: # Update only if missing
             final_data['liquidity'] = state_changed_event.get('liquidity', 0)
             logger.info("Liquidity found in PositionStateChanged (Active)")
         final_data.setdefault('finalTickLower', state_changed_event.get('lowerTick'))
         final_data.setdefault('finalTickUpper', state_changed_event.get('upperTick'))
    elif liq_op_event and not is_baseline:
         if 'liquidity' not in final_data or final_data.get('liquidity') == 0:
             final_data['liquidity'] = liq_op_event.get('liquidity', 0)
             logger.info("Liquidity found in LiquidityOperation")
         # Ticks might also be in this event
         final_data.setdefault('finalTickLower', liq_op_event.get('tickLower'))
         final_data.setdefault('finalTickUpper', liq_op_event.get('tickUpper'))

    # Ensure default for liquidity if not found
    final_data.setdefault('liquidity', 0)

    # Add gas info
    final_data['gas_used'] = receipt.get('gasUsed', 0)
    try:
        gas_price = receipt.get('effectiveGasPrice', w3.eth.gas_price)
        final_data['gas_cost_eth'] = float(w3.from_wei(final_data['gas_used'] * gas_price, 'ether'))
    except Exception as e:
        logger.warning(f"Could not calculate gas cost: {e}")
        final_data['gas_cost_eth'] = 0.0

    return final_data

# --- Function to Get Liquidity Directly (Unchanged from previous) ---
def get_liquidity_from_contract(contract_address, is_baseline=False):
    """Get current liquidity directly from contract view function."""
    # ... (Keep the implementation from the previous response using getCurrentPosition/currentPosition) ...
    if not w3 or not contract_address: logger.error("Web3/Address missing"); return 0
    try:
        if is_baseline:
            contract = get_contract(contract_address, "BaselineMinimal")
            position_data = contract.functions.getCurrentPosition().call()
            liquidity = position_data[4] if len(position_data) >= 5 else 0
            logger.info(f"Direct liquidity fetch (Baseline): {liquidity}")
            return liquidity
        else:
            contract = get_contract(contract_address, "PredictiveLiquidityManager")
            if hasattr(contract.functions, 'currentPosition'):
                 position_data = contract.functions.currentPosition().call()
                 liquidity = position_data[1] if len(position_data) >= 2 else 0
                 logger.info(f"Direct liquidity fetch (Predictive): {liquidity}")
                 return liquidity
            else: logger.warning("Predictive ABI missing currentPosition"); return 0
    except Exception as e: logger.error(f"Error direct fetch {contract_address}: {e}"); return 0


# --- Function to Decide if Adjustment is Needed (Off-Chain Check - REFINED) ---
def should_adjust_position(is_baseline: bool, predicted_price_data: dict) -> tuple[bool, dict]:
    """
    Performs off-chain check. Returns (should_adjust, csv_data_if_skipped).
    Requires contract parameters to be fetched first.
    """
    if not w3: logger.error("Web3 non-init"); return True, {}

    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_type = "Baseline" if is_baseline else "Predictive"
    contract_name = "BaselineMinimal" if is_baseline else "PredictiveLiquidityManager"

    if not contract_address: logger.error(f"{contract_type} Addr missing"); return False, {}

    # Prepare base data for CSV if skipped
    csv_data = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'contract_type': contract_type, 'action_taken': False, 'tx_hash': 'SKIPPED',
        'gas_used': 0, 'gas_cost_eth': 0.0,
        'input_price': predicted_price_data.get('original'),
        # Will be filled below
        'sqrtPriceX96': 0, 'currentTick': 0, 'predictedPrice': None, 'actualPrice': None,
        'finalTickLower': 0, 'finalTickUpper': 0, 'liquidity': 0
    }

    try:
        contract = get_contract(contract_address, contract_name)
        params = get_contract_params(contract_address, contract_name, is_baseline)
        tick_spacing = params['tickSpacing']

        # 1. Get current on-chain position state
        current_tick_lower = 0
        current_tick_upper = 0
        has_position = False
        current_liquidity = 0

        if is_baseline:
            pos_data = contract.functions.getCurrentPosition().call()
            has_position = pos_data[1]; current_tick_lower = pos_data[2]; current_tick_upper = pos_data[3]; current_liquidity = pos_data[4]
        else: # Predictive
             pos_data = contract.functions.currentPosition().call()
             current_liquidity = pos_data[1]; current_tick_lower = pos_data[2]; current_tick_upper = pos_data[3]; has_position = pos_data[4]

        csv_data['liquidity'] = current_liquidity # Log current liquidity if skipped

        if not has_position:
            logger.info(f"{contract_type}: No active position. Adjustment required.")
            return True, {} # Always adjust if no position

        # 2. Calculate target ticks in Python
        target_tick_lower = -1
        target_tick_upper = -1

        if is_baseline:
             # Get current tick from pool
             pool_address = factory.getPool(USDC_ADDRESS, WETH_ADDRESS, 3000) # Assuming fee=3000
             # Need Factory ABI - load it
             factory_abi = load_contract_abi("IUniswapV3Factory")
             factory_contract = w3.eth.contract(address=os.getenv('UNISWAP_FACTORY'), abi=factory_abi) # Get factory address from env?
             pool_address = factory_contract.functions.getPool(USDC_ADDRESS, WETH_ADDRESS, 3000).call()


             if pool_address != '0x0000000000000000000000000000000000000000':
                 pool_abi = load_contract_abi("IUniswapV3Pool")
                 pool_contract = w3.eth.contract(address=pool_address, abi=pool_abi)
                 slot0 = pool_contract.functions.slot0().call()
                 sqrtPriceX96_onchain = slot0[0]
                 current_tick = slot0[1]
                 csv_data['sqrtPriceX96'] = sqrtPriceX96_onchain
                 csv_data['currentTick'] = current_tick
                 # Calc price for CSV
                 try:
                      price_ratio = (sqrtPriceX96_onchain / TWO_POW_96)**2
                      price_t1_t0_adj = price_ratio / (10**(params['token1Decimals'] - params['token0Decimals']))
                      csv_data['actualPrice'] = 1.0 / price_t1_t0_adj if price_t1_t0_adj else 0
                 except: pass # ignore price calc errors

                 target_tick_lower, target_tick_upper = calculate_ticks_baseline_py(current_tick, tick_spacing)
             else:
                 logger.error("Baseline: Could not get pool address via Factory. Cannot perform off-chain check.")
                 return True, {} # Adjust if pool cannot be read

        else: # Predictive
            # Price from API/fallback
            price_t0_t1 = predicted_price_data['original']
            csv_data['predictedPrice'] = price_t0_t1
            # Calculate center tick using Python equivalent of _priceToTick
            target_center_tick = price_to_tick_predictive_py(price_t0_t1, params['token0Decimals'], params['token1Decimals'])

            if target_center_tick != -1:
                 # Calculate range using Python equivalent of _calculateTicks
                 target_tick_lower, target_tick_upper = calculate_ticks_predictive_py(
                     target_center_tick,
                     tick_spacing,
                     params['rangeWidthMultiplier']
                 )
            else:
                 logger.error("Predictive: Failed to calculate target center tick. Defaulting to adjust.")
                 return True, {} # Adjust if calculation fails

        # Check for calculation errors
        if target_tick_lower == -1 or target_tick_upper == -1:
            logger.error(f"{contract_type}: Python tick calculation failed. Defaulting to adjust.")
            return True, {}

        csv_data['finalTickLower'] = target_tick_lower
        csv_data['finalTickUpper'] = target_tick_upper

        # 3. Compare target ticks with current ticks
        lower_diff = abs(target_tick_lower - current_tick_lower)
        upper_diff = abs(target_tick_upper - current_tick_upper)

        logger.info(f"{contract_type} Off-Chain Check: Current=[{current_tick_lower}, {current_tick_upper}], Target=[{target_tick_lower}, {target_tick_upper}], Diff=[{lower_diff}, {upper_diff}]")

        if lower_diff <= TICK_ADJUSTMENT_THRESHOLD and upper_diff <= TICK_ADJUSTMENT_THRESHOLD:
            logger.info(f"{contract_type}: Target ticks match current ticks within threshold. Skipping adjustment.")
            save_event_to_csv(csv_data) # Save the calculated 'skipped' data
            return False, csv_data # Don't adjust
        else:
            logger.info(f"{contract_type}: Target ticks differ from current ticks. Adjustment needed.")
            return True, {} # Adjust

    except Exception as e:
        logger.error(f"Error during off-chain check for {contract_type}: {e}", exc_info=True)
        return True, {} # Default to adjusting if check fails


# --- Function to Create Position (UPDATED - Handles Off-Chain Check Result) ---
def create_position(predicted_price_data, is_baseline=False):
    """Creates or adjusts liquidity position AFTER off-chain check."""
    if not w3: logger.error("Web3 not initialized."); return None

    contract_type = "Baseline" if is_baseline else "Predictive"
    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_name = "BaselineMinimal" if is_baseline else "PredictiveLiquidityManager"

    if not contract_address:
         logger.error(f"{contract_type} address is not set."); return None

    logger.info(f"--- Attempting to adjust position for {contract_type} contract ---")
    logger.info(f"Using contract: {contract_name} at {contract_address}")

    # --- Perform Off-Chain Check ---
    should_run_tx, skipped_data = should_adjust_position(is_baseline, predicted_price_data)

    if not should_run_tx:
        logger.info(f"Skipping {contract_type} transaction based on off-chain check.")
        return None

    # --- Proceed with Transaction ---
    logger.info(f"Off-chain check indicates adjustment needed for {contract_type}. Proceeding with transaction...")

    # Check/Send Tokens (Run only if tx is needed)
    logger.info(f"Checking/Sending tokens for {contract_type}...")
    if not send_tokens_to_contract(is_baseline):
         logger.error(f"Failed to ensure sufficient funds for {contract_type}. Aborting.")
         fail_data = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
            'contract_type': contract_type,
            'action_taken': False, 
            'tx_hash': 'FUNDING_FAILED',
            'input_price': predicted_price_data.get('original'),
         }
         save_event_to_csv(fail_data)
         return None

    try:
        contract = get_contract(contract_address, contract_name)
        contract_abi = contract.abi
        account = Account.from_key(PRIVATE_KEY)
        chain_id = int(w3.net.version)

        # Prepare function call
        if is_baseline:
            contract_function = contract.functions.adjustLiquidityWithCurrentPrice()
        else:
            # --- Correct Price Scaling for Predictive ---
            original_price = predicted_price_data["original"]
            params = get_contract_params(contract_address, contract_name, is_baseline)
            token0_dec = params['token0Decimals']
            token1_dec = params['token1Decimals']

            # Scale price by first dividing by token0 decimals to prevent overflow
            scaled_price = original_price / (10 ** token0_dec)  # Example: 1602.02 / 10^6 = 0.00160202
            # Then multiply by token1 decimals
            price_to_send = int(scaled_price * (10 ** token1_dec))  # Example: 0.00160202 * 10^18

            logger.info(f"Calculated scaled price_to_send: {price_to_send} (original: {original_price})")
            contract_function = contract.functions.updatePredictionAndAdjust(price_to_send)

        # Estimate gas and build transaction
        logger.info("Estimating gas...")
        gas_limit = 1_500_000 # Default gas limit
        try:
             gas_estimate = contract_function.estimate_gas({'from': account.address})
             gas_limit = int(gas_estimate * 1.3)
             logger.info(f"Gas estimate: {gas_estimate}, Gas limit set to: {gas_limit}")
        except Exception as est_err:
             logger.warning(f"Gas estimation failed: {est_err}. Using default gas limit: {gas_limit}")

        gas_price = w3.eth.gas_price
        nonce = w3.eth.get_transaction_count(account.address)
        
        # Build transaction with chainId
        transaction = contract_function.build_transaction({
            'chainId': chain_id,
            'from': account.address,
            'gas': gas_limit,
            'gasPrice': int(gas_price * 1.2),  # 20% higher gas price
            'nonce': nonce
        })

        # Sign and send
        signed_txn = w3.eth.account.sign_transaction(transaction, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
        logger.info(f"Transaction sent: {tx_hash.hex()}")

        # Wait for receipt
        logger.info("Waiting for transaction receipt...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

        if receipt['status'] == 1:
            logger.info(f"Transaction successful! Gas used: {receipt.get('gasUsed', 'N/A')}")
            # Extract event data from receipt
            event_data = get_contract_event_data(receipt, contract_address, contract_abi, is_baseline)

            # Fallback to direct liquidity fetch if needed
            if event_data.get('liquidity', 0) == 0:
                 logger.info("Liquidity from events is 0 or missing, attempting direct fetch...")
                 time.sleep(3) # Give state time to settle
                 final_liquidity = get_liquidity_from_contract(contract_address, is_baseline)
                 event_data['liquidity'] = final_liquidity
                 logger.info(f"Liquidity after direct fetch: {final_liquidity}")

            # Add additional info for CSV
            event_data['contract_type'] = contract_type
            event_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            event_data['action_taken'] = True # Action was taken
            event_data['input_price'] = predicted_price_data.get('original')
            if not is_baseline:
                 event_data['predictedPrice'] = predicted_price_data.get('original') # Log the input price
                 # Actual price can be derived from event_data['actualPrice'] if predictive emits it

            else: # Baseline - Calculate actual price from sqrtPriceX96 if available
                 sqrtP = event_data.get('sqrtPriceX96')
                 if sqrtP:
                      try:
                          params = get_contract_params(contract_address, contract_name, is_baseline)
                          price_ratio = (sqrtP / TWO_POW_96)**2
                          price_t1_t0_adj = price_ratio / (10**(params['token1Decimals'] - params['token0Decimals']))
                          event_data['actualPrice'] = 1.0 / price_t1_t0_adj if price_t1_t0_adj else 0
                      except Exception as price_calc_err:
                           logger.warning(f"Could not calc actualPrice from sqrtPriceX96: {price_calc_err}")


            # Ensure gas cost is calculated
            if 'gas_cost_eth' not in event_data or event_data.get('gas_cost_eth') == 0.0:
                 try:
                      gas_price_eff = receipt.get('effectiveGasPrice', gas_price)
                      event_data['gas_cost_eth'] = float(w3.from_wei(receipt.get('gasUsed', 0) * gas_price_eff, 'ether'))
                 except: event_data['gas_cost_eth'] = 0.0


            # Save the final data from the successful transaction
            save_event_to_csv(event_data)
            return event_data # Return data for potential further use
        else:
            logger.error(f"Transaction failed! Hash: {tx_hash.hex()}")
            logger.error(f"Receipt: {receipt}")
            # Log failure to CSV
            fail_data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'contract_type': contract_type,
                'action_taken': False, # Or maybe True since tx was sent? Let's say False as it failed.
                'tx_hash': tx_hash.hex() + '_FAILED',
                'input_price': predicted_price_data.get('original'),
                'gas_used': receipt.get('gasUsed', 0),
                'gas_cost_eth': float(w3.from_wei(receipt.get('gasUsed', 0) * receipt.get('effectiveGasPrice', gas_price), 'ether')) if receipt.get('gasUsed') else 0.0
            }
            save_event_to_csv(fail_data)
            return None

    except Exception as e:
        logger.error(f"Critical error in create_position for {contract_type}: {str(e)}", exc_info=True)
        # Log failure to CSV
        fail_data = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'contract_type': contract_type,
            'action_taken': False, 'tx_hash': 'ERROR_BEFORE_SEND',
            'input_price': predicted_price_data.get('original'),
        }
        save_event_to_csv(fail_data)
        return None


# --- Function to Save Event Data to CSV (UPDATED - Handles Skipped/Defaults) ---
def save_event_to_csv(data_to_save):
    """Saves event data (or skipped action data) to CSV file."""
    if not data_to_save:
        logger.warning("No data provided to save_event_to_csv")
        return

    filepath = 'position_results.csv'
    file_exists = os.path.isfile(filepath)

    fieldnames = [
        'timestamp', 'contract_type', 'action_taken', 'tx_hash',
        'input_price', 'predictedPrice', 'actualPrice', 'sqrtPriceX96',
        'currentTick', 'finalTickLower', 'finalTickUpper', 'liquidity',
        'gas_used', 'gas_cost_eth'
        # Removed 'adjusted' as 'action_taken' is clearer
    ]

    try:
        # Prepare row data with defaults for all fields
        row_data = {field: data_to_save.get(field, '') for field in fieldnames} # Default to empty string

        # Apply specific defaults for numeric types if missing
        for field in ['sqrtPriceX96', 'currentTick', 'finalTickLower', 'finalTickUpper', 'liquidity', 'gas_used']:
             row_data[field] = data_to_save.get(field, 0)
        for field in ['input_price', 'predictedPrice', 'actualPrice', 'gas_cost_eth']:
             row_data[field] = data_to_save.get(field, 0.0)

        # Ensure boolean is explicit
        row_data['action_taken'] = bool(data_to_save.get('action_taken', False))

        # Apply specific values for skipped/failed cases based on tx_hash pattern
        tx_hash_val = str(data_to_save.get('tx_hash', ''))
        if 'SKIPPED' in tx_hash_val or 'FAILED' in tx_hash_val or 'ERROR' in tx_hash_val :
            row_data['action_taken'] = False # Ensure action_taken is False
            row_data['tx_hash'] = tx_hash_val # Keep the specific status
            if 'SKIPPED' in tx_hash_val:
                 row_data['gas_used'] = 0
                 row_data['gas_cost_eth'] = 0.0
                 # Keep calculated ticks and current liquidity if available
                 row_data['liquidity'] = data_to_save.get('liquidity', 0) # Should be current liquidity before skip
                 row_data['finalTickLower'] = data_to_save.get('finalTickLower', 0)
                 row_data['finalTickUpper'] = data_to_save.get('finalTickUpper', 0)


        with open(filepath, 'a', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            if not file_exists:
                writer.writeheader()
            writer.writerow(row_data)
        # logger.info(f"Data saved to {filepath}") # Reduce log noise

    except Exception as e:
        logger.error(f"Error saving to CSV: {str(e)}", exc_info=True)


# --- Main Execution Logic (UPDATED - Calls create_position which now handles checks) ---
def run_tests(args):
    """Runs the adjustment logic for selected contracts."""
    logger.info(f"=== Starting Position Adjustment Cycle ===")
    start_time = time.time()

    predicted_price_data = get_predicted_price()
    if not predicted_price_data:
         logger.error("Failed to get predicted price. Aborting cycle.")
         return

    logger.info(f"Using predicted price: {predicted_price_data['original']} ETH/USDC for cycle")

    # Process Predictive
    if args.both or args.predictive_only:
        create_position(predicted_price_data, is_baseline=False)
        if args.both: time.sleep(5) # Small delay

    # Process Baseline
    if args.both or args.baseline_only:
        create_position(predicted_price_data, is_baseline=True)

    end_time = time.time()
    logger.info(f"=== Position Adjustment Cycle Completed (Duration: {end_time - start_time:.2f}s) ===")


# --- Main Function ---
def main():
    """Main function to parse arguments and execute"""
    parser = argparse.ArgumentParser(description='Uniswap V3 Liquidity Manager Test Script')
    parser.add_argument('--send-tokens-only', action='store_true', help='Only check and send tokens if needed')
    parser.add_argument('--predictive-only', action='store_true', help='Run only Predictive contract logic')
    parser.add_argument('--baseline-only', action='store_true', help='Run only Baseline contract logic')
    parser.add_argument('--schedule', type=int, default=0, metavar='MINUTES', help='Run periodically every X minutes (e.g., --schedule 60)')
    # Default changed: Run both unless specified otherwise
    parser.add_argument('--no-both', action='store_true', help='Do NOT run both contracts if --predictive-only or --baseline-only is not set')

    args = parser.parse_args()

    # Determine which contracts to run
    args.run_predictive = False
    args.run_baseline = False
    args.both = False # Explicitly track if both should run

    if args.predictive_only:
        args.run_predictive = True
    elif args.baseline_only:
        args.run_baseline = True
    elif not args.no_both: # If neither specific flag nor --no-both is set, run both
        args.run_predictive = True
        args.run_baseline = True
        args.both = True # Mark that both are running sequentially
    else: # --no-both is set without specific flags
         logger.warning("No contracts selected to run (--no-both specified without --predictive-only or --baseline-only). Exiting.")
         return


    # Handle send-tokens-only mode
    if args.send_tokens_only:
        if args.run_predictive:
            logger.info("Checking/Sending tokens to Predictive contract...")
            send_tokens_to_contract(is_baseline=False)
        if args.run_baseline:
             logger.info("Checking/Sending tokens to Baseline contract...")
             send_tokens_to_contract(is_baseline=True)
        return

    # --- Main Loop/Scheduler ---
    if args.schedule > 0:
        logger.info(f"Scheduling test cycle every {args.schedule} minutes...")
        # Run once immediately
        try:
            run_tests(args)
        except Exception as e:
             logger.error(f"Initial run failed: {e}", exc_info=True)

        # Schedule subsequent runs
        schedule.every(args.schedule).minutes.do(run_tests, args=args)
        while True:
            try:
                schedule.run_pending()
            except Exception as e:
                 logger.error(f"Error during scheduled run execution: {e}")
            time.sleep(30) # Check schedule every 30 seconds
    else:
        # Run once immediately
        run_tests(args)


if __name__ == "__main__":
    if w3 is None:
         logger.critical("Web3 Initialization failed. Exiting.")
    elif not PRIVATE_KEY:
         logger.critical("PRIVATE_KEY not found in environment variables. Exiting.")
    elif not PREDICTIVE_MANAGER_ADDRESS and not BASELINE_MANAGER_ADDRESS:
         logger.critical("Neither PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS nor BASELINE_MINIMAL_ADDRESS are set. Exiting.")
    else:
         # Add check for necessary ABIs before starting?
         try:
              load_contract_abi("PredictiveLiquidityManager")
              load_contract_abi("BaselineMinimal")
              load_contract_abi("IERC20")
              load_contract_abi("IUniswapV3Pool")
              load_contract_abi("IUniswapV3Factory")
              logger.info("Required ABIs loaded successfully.")
              main()
         except FileNotFoundError as e:
              logger.critical(f"Failed to load required ABI: {e}. Please ensure artifacts are available. Exiting.")
         except Exception as e:
              logger.critical(f"An unexpected error occurred before main execution: {e}", exc_info=True)