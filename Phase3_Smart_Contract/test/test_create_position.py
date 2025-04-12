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
load_dotenv()
PREDICTIVE_MANAGER_ADDRESS = os.getenv('PREDICTIVE_LIQUIDITY_MANAGER_ADDRESS')
BASELINE_MANAGER_ADDRESS = os.getenv('BASELINE_MINIMAL_ADDRESS')
USDC_ADDRESS = os.getenv('USDC_ADDRESS')
WETH_ADDRESS = os.getenv('WETH_ADDRESS')
PRIVATE_KEY = os.getenv('PRIVATE_KEY')
RPC_URL = os.getenv('SEPOLIA_RPC_URL')

# Token balance thresholds
MIN_USDC_BALANCE = 10_000_000  # 10 USDC with 6 decimals
MIN_WETH_BALANCE = Web3.to_wei(0.005, 'ether')  # 0.005 WETH

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

def check_token_balances(is_baseline=False):
    """Check token balances in contract"""
    if not w3:
        logging.error("Web3 not initialized. Check your RPC URL.")
        return False, False, 0, 0
        
    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_type = "Baseline" if is_baseline else "Predictive"
    
    # Load token ABIs
    erc20_abi = [
        {"constant": True, "inputs": [{"name": "owner", "type": "address"}], 
         "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], 
         "payable": False, "stateMutability": "view", "type": "function"}
    ]
    
    weth_contract = w3.eth.contract(address=WETH_ADDRESS, abi=erc20_abi)
    usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=erc20_abi)
    
    # Check balances
    weth_balance = weth_contract.functions.balanceOf(contract_address).call()
    usdc_balance = usdc_contract.functions.balanceOf(contract_address).call()
    
    logging.info(f"{contract_type} contract balance: {w3.from_wei(weth_balance, 'ether')} WETH, {usdc_balance / 1e6} USDC")
    
    has_enough_weth = weth_balance >= MIN_WETH_BALANCE
    has_enough_usdc = usdc_balance >= MIN_USDC_BALANCE
    
    return has_enough_weth, has_enough_usdc, weth_balance, usdc_balance

def send_tokens_to_contract(is_baseline=False):
    """ارسال توکن‌های مورد نیاز به قرارداد - فقط در صورت لزوم"""
    if not w3:
        logging.error("Web3 not initialized")
        return False
    
    account = Account.from_key(PRIVATE_KEY)
    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_type = "Baseline" if is_baseline else "Predictive"
    
    # بررسی موجودی فعلی
    has_enough_weth, has_enough_usdc, weth_balance, usdc_balance = check_token_balances(is_baseline)
    
    if has_enough_weth and has_enough_usdc:
        logging.info(f"{contract_type} contract has sufficient tokens")
        return True
    
    try:
        # محاسبه قیمت گاز
        gas_price = w3.eth.gas_price
        
        # برای Baseline: ارسال مستقیم ETH
        if is_baseline and not has_enough_weth:
            try:
                eth_amount = w3.to_wei(0.1, 'ether')
                
                tx = {
                    'to': contract_address,
                    'value': eth_amount,
                    'gas': 50000,  # کاهش گاز
                    'gasPrice': gas_price,
                    'nonce': w3.eth.get_transaction_count(account.address)
                }
                
                signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                
                # انتظار برای تأیید، با timeout کمتر
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                if receipt.status == 1:
                    logging.info(f"ETH transfer to Baseline successful")
                    time.sleep(2)  # کاهش زمان انتظار
                    return True
                else:
                    logging.error("ETH transfer failed")
                    return False
            except Exception as e:
                logging.error(f"Error sending ETH: {str(e)}")
                return False
        
        # برای Predictive
        if not is_baseline:
            # 1. ارسال WETH در صورت نیاز
            if not has_enough_weth:
                # بارگذاری قرارداد WETH
                weth_abi = [
                    {"constant": False, "inputs": [], "name": "deposit", "outputs": [], 
                     "payable": True, "stateMutability": "payable", "type": "function"},
                    {"constant": False, "inputs": [{"name": "dst", "type": "address"}, 
                                                 {"name": "wad", "type": "uint256"}], 
                     "name": "transfer", "outputs": [{"name": "", "type": "bool"}], 
                     "payable": False, "stateMutability": "nonpayable", "type": "function"}
                ]
                weth_contract = w3.eth.contract(address=WETH_ADDRESS, abi=weth_abi)
                
                # تبدیل ETH به WETH
                eth_amount = w3.to_wei(0.03, 'ether')  # کاهش مقدار ETH
                
                tx_hash = weth_contract.functions.deposit().build_transaction({
                    'from': account.address,
                    'value': eth_amount,
                    'nonce': w3.eth.get_transaction_count(account.address),
                    'gas': 70000,  # کاهش گاز
                    'gasPrice': gas_price
                })
                
                signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
                deposit_tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                
                receipt = w3.eth.wait_for_transaction_receipt(deposit_tx_hash, timeout=120)
                if receipt.status != 1:
                    logging.error("ETH to WETH conversion failed")
                    return False
                
                time.sleep(2)
                
                # ارسال WETH به قرارداد
                weth_balance = weth_contract.functions.balanceOf(account.address).call()
                tx_hash = weth_contract.functions.transfer(contract_address, weth_balance).build_transaction({
                    'from': account.address,
                    'nonce': w3.eth.get_transaction_count(account.address),
                    'gas': 70000,
                    'gasPrice': gas_price
                })
                
                signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
                weth_tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                
                receipt = w3.eth.wait_for_transaction_receipt(weth_tx_hash, timeout=120)
                if receipt.status != 1:
                    logging.error("WETH transfer failed")
                    return False
                
                time.sleep(2)
        
        # 2. ارسال USDC در صورت نیاز
        if not has_enough_usdc:
            # بارگذاری قرارداد USDC
            erc20_abi = [
                {"constant": False, "inputs": [{"name": "to", "type": "address"}, 
                                             {"name": "value", "type": "uint256"}], 
                 "name": "transfer", "outputs": [{"name": "", "type": "bool"}], 
                 "payable": False, "stateMutability": "nonpayable", "type": "function"}
            ]
            usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=erc20_abi)
            
            usdc_amount = 30_000_000  # کاهش مقدار USDC به 30
            
            tx_hash = usdc_contract.functions.transfer(contract_address, usdc_amount).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 70000,
                'gasPrice': gas_price
            })
            
            signed_tx = w3.eth.account.sign_transaction(tx_hash, private_key=PRIVATE_KEY)
            usdc_tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            receipt = w3.eth.wait_for_transaction_receipt(usdc_tx_hash, timeout=120)
            if receipt.status != 1:
                logging.error("USDC transfer failed")
                return False
        
        # بررسی نهایی موجودی
        has_enough_weth_now, has_enough_usdc_now, _, _ = check_token_balances(is_baseline)
        
        # فقط موفقیت توکن‌های مورد نیاز را بررسی می‌کنیم
        if is_baseline:
            return has_enough_weth_now  # برای Baseline فقط ETH لازم است
        else:
            return has_enough_weth_now and has_enough_usdc_now
        
    except Exception as e:
        logging.error(f"Error in token transfer: {str(e)}")
        return False

def get_contract_event_data(contract, receipt, is_baseline=False):
    """Extract event data from transaction receipt with focus on liquidity"""
    try:
        result_data = {}
        
        # Get adjustment metrics events
        if is_baseline:
            events = contract.events.BaselineAdjustmentMetrics().process_receipt(receipt)
            if events and len(events) > 0:
                result_data.update(dict(events[0]['args']))
        else:
            events = contract.events.PredictionAdjustmentMetrics().process_receipt(receipt)
            if events and len(events) > 0:
                result_data.update(dict(events[0]['args']))
        
        # Look for LiquidityOperation event which should contain liquidity
        try:
            liquidity_events = contract.events.LiquidityOperation().process_receipt(receipt)
            if liquidity_events and len(liquidity_events) > 0:
                # Use the last LiquidityOperation event (usually the MINT operation)
                last_event = liquidity_events[-1]
                
                # Log all fields for debugging
                logging.info(f"Found LiquidityOperation event:")
                for key, value in last_event['args'].items():
                    logging.info(f"  {key}: {value}")
                
                # Update result with liquidity data
                if 'liquidity' in last_event['args']:
                    result_data['liquidity'] = last_event['args']['liquidity']
                    logging.info(f"Found liquidity in event: {last_event['args']['liquidity']}")
        except Exception as e:
            logging.warning(f"Error processing LiquidityOperation: {str(e)}")
            
            # If we couldn't get liquidity from events, try to get it directly after transaction
            try:
                if not is_baseline and hasattr(contract.functions, 'currentPosition'):
                    position = contract.functions.currentPosition().call()
                    if isinstance(position, (list, tuple)) and len(position) > 1:
                        result_data['liquidity'] = position[1]
                        logging.info(f"Got liquidity from currentPosition: {position[1]}")
            except Exception as e2:
                logging.warning(f"Error getting position after transaction: {str(e2)}")
        
        return result_data
                
    except Exception as e:
        logging.error(f"Error extracting event data: {str(e)}")
        traceback.print_exc()
        return None

def get_current_liquidity(contract_address, is_baseline=False):
    """Get current liquidity directly from contract"""
    try:
        if not w3:
            return 0
            
        contract_name = "BaselineMinimal" if is_baseline else "PredictiveLiquidityManager"
        contract_abi = load_contract_abi(contract_name)
        contract = w3.eth.contract(address=contract_address, abi=contract_abi)
        
        # سعی کنیم تابع getActivePositionDetails را صدا بزنیم
        if is_baseline:
            try:
                if 'getActivePositionDetails' in dir(contract.functions):
                    position = contract.functions.getActivePositionDetails().call()
                    logging.info(f"Active position details from Baseline: {position}")
                    # معمولاً موقعیت‌ها در این ساختار هستند: [tokenId, liquidity, tickLower, tickUpper, active]
                    if len(position) >= 2:  # حداقل باید tokenId و liquidity داشته باشد
                        return position[1]  # liquidity معمولاً دومین مقدار است
            except Exception as e:
                logging.warning(f"Error getting position details from Baseline: {str(e)}")
        else:
            try:
                if 'getPosition' in dir(contract.functions):
                    position = contract.functions.getPosition().call()
                    logging.info(f"Position details from Predictive: {position}")
                    # ساختار دقیق را از قرارداد بررسی کنید
                    if isinstance(position, tuple) and len(position) > 0:
                        for i, value in enumerate(position):
                            logging.info(f"  Position value {i}: {value}")
                        # اگر liquidity در این نتیجه وجود دارد، آن را برگردانیم
                        if len(position) >= 2:
                            return position[1]  # ممکن است جایگاه دقیق متفاوت باشد
            except Exception as e:
                logging.warning(f"Error getting position from Predictive: {str(e)}")
        
        return 0
    except Exception as e:
        logging.error(f"Error in get_current_liquidity: {str(e)}")
        return 0

def get_liquidity_from_contract(is_baseline=False):
    """Get liquidity directly from contract using available functions"""
    if not w3:
        logging.error("Web3 not initialized")
        return 0
    
    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_type = "Baseline" if is_baseline else "Predictive"
    contract_name = "BaselineMinimal" if is_baseline else "PredictiveLiquidityManager"
    
    try:
        # بارگذاری ABI قرارداد
        contract_abi = load_contract_abi(contract_name)
        contract = w3.eth.contract(address=contract_address, abi=contract_abi)
        
        if is_baseline:
            # برای Baseline contract
            # ابتدا چک کنیم آیا موقعیتی وجود دارد
            if hasattr(contract.functions, 'hasPosition'):
                has_position = contract.functions.hasPosition().call()
                if not has_position:
                    logging.info(f"Baseline contract has no active position")
                    return 0
                
                # اگر موقعیتی وجود دارد باید تابعی پیدا کنیم که جزئیات آن را برگرداند
                # فعلاً اطلاعات دقیقی نداریم
                return 0
            
        else:
            # برای Predictive contract
            if hasattr(contract.functions, 'currentPosition'):
                try:
                    position = contract.functions.currentPosition().call()
                    
                    # بررسی مقادیر برگشتی
                    if isinstance(position, (list, tuple)) and len(position) > 1:
                        # برای Predictive، liquidity دومین مقدار (ایندکس 1) است
                        liquidity = position[1]
                        logging.info(f"Got liquidity from currentPosition: {liquidity}")
                        return liquidity
                except Exception as e:
                    logging.warning(f"Error getting currentPosition: {str(e)}")
            
        return 0
        
    except Exception as e:
        logging.error(f"Error getting liquidity from contract: {str(e)}")
        traceback.print_exc()
        return 0

def create_position(predicted_price, is_baseline=False):
    """ایجاد موقعیت نقدینگی با پیش‌بینی قیمت"""
    if not w3:
        logging.error("Web3 not initialized. Check your RPC URL.")
        return None
        
    contract_type = "Baseline" if is_baseline else "Predictive"
    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_name = "BaselineMinimal" if is_baseline else "PredictiveLiquidityManager"
    
    # تست نیاز به ارسال توکن
    has_enough_weth, has_enough_usdc, _, _ = check_token_balances(is_baseline)
    if not has_enough_weth or not has_enough_usdc:
        if not send_tokens_to_contract(is_baseline):
            logging.error(f"Failed to send required tokens to {contract_type} contract.")
            return None
    
    # آماده‌سازی داده‌های قیمت
    inverted_price_rounded = round(predicted_price["inverted"], 6)
    price_to_send = int(inverted_price_rounded * 1e6)
    
    logging.info(f"Creating position with {contract_type} contract - Price: {predicted_price['original']} ETH/USDC")
    
    try:
        # بارگذاری ABI و ایجاد شیء قرارداد
        contract_abi = load_contract_abi(contract_name)
        contract = w3.eth.contract(address=contract_address, abi=contract_abi)
        account = Account.from_key(PRIVATE_KEY)
        
        # انتخاب تابع قرارداد براساس نوع
        contract_function = contract.functions.adjustLiquidityWithCurrentPrice() if is_baseline else contract.functions.updatePredictionAndAdjust(price_to_send)
        
        # تخمین گاز و ساخت تراکنش با حاشیه امن کمتر
        gas_estimate = contract_function.estimate_gas({'from': account.address})
        gas_limit = int(gas_estimate * 1.2)  # کاهش از 1.5 به 1.2
        gas_price = w3.eth.gas_price
        
        transaction = contract_function.build_transaction({
            'from': account.address,
            'gas': gas_limit,
            'gasPrice': gas_price,
            'nonce': w3.eth.get_transaction_count(account.address)
        })
        
        # امضا و ارسال تراکنش
        signed_txn = w3.eth.account.sign_transaction(transaction, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
        logging.info(f"Transaction sent: {tx_hash.hex()}")
        
        # انتظار برای تأیید تراکنش
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)  # کاهش timeout
        
        if receipt['status'] == 1:
            gas_used = receipt['gasUsed']
            gas_cost_eth = w3.from_wei(gas_used * gas_price, 'ether')
            logging.info(f"Transaction successful - Gas: {gas_used}, Cost: {gas_cost_eth} ETH")
            
            # استخراج داده‌های رویداد
            event_data = get_contract_event_data(contract, receipt, is_baseline)
            
            if event_data:
                # افزودن اطلاعات اضافی به داده‌های رویداد
                event_data.update({
                    'contract_type': contract_type,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'tx_hash': tx_hash.hex(),
                    'gas_used': gas_used,
                    'gas_cost_eth': float(gas_cost_eth),
                    # input_price برای هر قرارداد متفاوت است
                    'input_price': event_data.get('actualPrice', '') if is_baseline else predicted_price['original']
                })
                
                return event_data
            else:
                logging.warning(f"No event data found in receipt")
                return None
        else:
            logging.error(f"Transaction failed: {tx_hash.hex()}")
            return None
            
    except Exception as e:
        logging.error(f"Error in position creation: {str(e)}")
        traceback.print_exc()
        return None

def save_event_to_csv(event_data):
    """ذخیره داده‌های رویداد در فایل CSV"""
    if not event_data:
        logging.warning("No event data to save")
        return
    
    file_exists = os.path.isfile('position_results.csv')
    
    try:
        # فیلدهای ضروری CSV
        fieldnames = [
            'timestamp',
            'contract_type',
            'tx_hash',
            'input_price',
            'liquidity',
            'gas_used',
            'gas_cost_eth',
            'actualPrice',
            'predictedPrice',
            'finalTickLower',
            'finalTickUpper',
            'adjusted'
        ]
        
        # نگاشت نام‌های فیلد
        field_mapping = {
            'currentPrice': 'actualPrice',
            'tickLower': 'finalTickLower',
            'tickUpper': 'finalTickUpper'
        }
        
        with open('position_results.csv', 'a', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
            
            # آماده‌سازی داده‌های سطر CSV
            row_data = {}
            
            # نگاشت مستقیم فیلدهای موجود
            for field in fieldnames:
                if field in event_data:
                    row_data[field] = event_data[field]
                elif field in field_mapping and field_mapping[field] in event_data:
                    row_data[field] = event_data[field_mapping[field]]
                else:
                    row_data[field] = ''
            
            writer.writerow(row_data)
            
    except Exception as e:
        logging.error(f"Error saving to CSV: {str(e)}")

def test_events(contract_address, is_baseline=False):
    """Test event processing for a specific contract"""
    if not w3:
        logging.error("Web3 not initialized")
        return
    
    contract_type = "Baseline" if is_baseline else "Predictive"
    contract_name = "BaselineMinimal" if is_baseline else "PredictiveLiquidityManager"
    
    logging.info(f"Testing events for {contract_type} contract at {contract_address}...")
    
    # بارگذاری ABI قرارداد
    contract_abi = load_contract_abi(contract_name)
    contract = w3.eth.contract(address=contract_address, abi=contract_abi)
    
    # لیست همه رویدادهای موجود در قرارداد
    event_names = []
    for attr_name in dir(contract.events):
        if not attr_name.startswith('_') and callable(getattr(contract.events, attr_name)):
            event_names.append(attr_name)
    
    logging.info(f"Available events in {contract_type} contract: {event_names}")
    
    # بررسی آیا LiquidityOperation وجود دارد
    if 'LiquidityOperation' in event_names:
        logging.info("LiquidityOperation event is available in contract")
    else:
        logging.warning("LiquidityOperation event is NOT available in contract")
        
        # جستجو برای رویدادهای مرتبط با liquidity
        for event_name in event_names:
            if 'liquidity' in event_name.lower():
                logging.info(f"Found potential liquidity event: {event_name}")

def debug_contract_position(is_baseline=False):
    """دیباگ قرارداد و بررسی توابع موجود"""
    if not w3:
        logging.error("Web3 not initialized")
        return
    
    contract_address = BASELINE_MANAGER_ADDRESS if is_baseline else PREDICTIVE_MANAGER_ADDRESS
    contract_type = "Baseline" if is_baseline else "Predictive"
    contract_name = "BaselineMinimal" if is_baseline else "PredictiveLiquidityManager"
    
    logging.info(f"Debugging {contract_type} contract at {contract_address}...")
    
    try:
        # بارگذاری ABI قرارداد
        contract_abi = load_contract_abi(contract_name)
        contract = w3.eth.contract(address=contract_address, abi=contract_abi)
        
        # لیست توابع موجود در قرارداد
        all_functions = []
        for attr_name in dir(contract.functions):
            if not attr_name.startswith('_') and callable(getattr(contract.functions, attr_name)):
                all_functions.append(attr_name)
        
        logging.info(f"Available functions in {contract_type} contract: {all_functions}")
        
        # بررسی توابع خاص
        if is_baseline:
            # تست توابع Baseline
            if 'currentTokenId' in all_functions:
                token_id = contract.functions.currentTokenId().call()
                logging.info(f"Token ID from currentTokenId: {token_id}")
            
            if 'hasPosition' in all_functions:
                has_position = contract.functions.hasPosition().call()
                logging.info(f"Has position: {has_position}")
            
            # باید دنبال تابعی بگردیم که جزئیات موقعیت را برمی‌گرداند
            position_funcs = ['getPosition', 'position', 'getActivePosition', 'getActivePositionDetails']
            for func in position_funcs:
                if func in all_functions:
                    try:
                        result = getattr(contract.functions, func)().call()
                        logging.info(f"Result from {func}: {result}")
                        if isinstance(result, (list, tuple)):
                            for i, val in enumerate(result):
                                logging.info(f"  {func}[{i}]: {val}")
                    except Exception as e:
                        logging.warning(f"Error calling {func}: {str(e)}")
        else:
            # تست توابع Predictive
            if 'currentPosition' in all_functions:
                try:
                    position = contract.functions.currentPosition().call()
                    logging.info(f"Result from currentPosition: {position}")
                    if isinstance(position, (list, tuple)):
                        for i, val in enumerate(position):
                            logging.info(f"  currentPosition[{i}]: {val}")
                except Exception as e:
                    logging.warning(f"Error calling currentPosition: {str(e)}")
        
        # بررسی رویدادهای قرارداد
        all_events = []
        for attr_name in dir(contract.events):
            if not attr_name.startswith('_') and callable(getattr(contract.events, attr_name)):
                all_events.append(attr_name)
        
        logging.info(f"Available events in {contract_type} contract: {all_events}")
        
        # بررسی آخرین تراکنش‌های این قرارداد
        block = w3.eth.get_block('latest')
        block_number = block['number']
        logging.info(f"Current block number: {block_number}")
        
        # جستجوی آخرین 1000 بلاک برای تراکنش‌های این قرارداد
        events_found = False
        for event_name in all_events:
            try:
                # فقط برای رویدادهای مرتبط با liquidity
                if 'liquid' in event_name.lower() or 'position' in event_name.lower():
                    logging.info(f"Searching for {event_name} events...")
                    event_filter = getattr(contract.events, event_name).create_filter(
                        fromBlock=max(0, block_number - 1000),
                        toBlock=block_number
                    )
                    events = event_filter.get_all_entries()
                    
                    if events:
                        events_found = True
                        logging.info(f"Found {len(events)} {event_name} events")
                        # آخرین رویداد را با جزئیات نمایش دهیم
                        if len(events) > 0:
                            last_event = events[-1]
                            logging.info(f"Latest {event_name} event:")
                            logging.info(f"  Block: {last_event['blockNumber']}")
                            logging.info(f"  Transaction: {last_event['transactionHash'].hex()}")
                            for arg_name, arg_value in last_event['args'].items():
                                logging.info(f"  {arg_name}: {arg_value}")
            except Exception as e:
                logging.warning(f"Error searching for {event_name} events: {str(e)}")
        
        if not events_found:
            logging.warning(f"No relevant events found for {contract_type} contract")
        
        return None

    except Exception as e:
        logging.error(f"Error debugging contract: {str(e)}")
        traceback.print_exc()
        return None

def get_liquidity_from_uniswap_api(token_id):
    """دریافت اطلاعات موقعیت از API یونی‌سوآپ"""
    try:
        # این یک مثال فرضی است - نیاز به API واقعی یونی‌سوآپ دارد
        api_url = f"https://api.uniswap.org/v1/positions/{token_id}"
        response = requests.get(api_url)
        if response.status_code == 200:
            data = response.json()
            return data.get('liquidity', 0)
    except Exception as e:
        logging.error(f"Error getting liquidity from API: {str(e)}")
    return 0

def main():
    """Main function to parse arguments and execute"""
    parser = argparse.ArgumentParser(description='Test Position Creation')
    parser.add_argument('--send-tokens-only', action='store_true', help='Only send tokens')
    parser.add_argument('--predictive-only', action='store_true', help='Test only Predictive contract')
    parser.add_argument('--baseline-only', action='store_true', help='Test only Baseline contract')
    parser.add_argument('--schedule', action='store_true', help='Run on schedule (every hour)')
    parser.add_argument('--both', action='store_true', help='Run both contracts in sequence')
    parser.add_argument('--debug', action='store_true', help='Run debug mode without transactions')
    
    args = parser.parse_args()
    
    # اضافه کردن حالت دیباگ
    if args.debug:
        logging.info("=== Running in debug mode ===")
        if args.both or (not args.predictive_only and not args.baseline_only):
            logging.info("Debugging both contracts...")
            debug_contract_position(is_baseline=False)
            debug_contract_position(is_baseline=True)
        elif args.predictive_only:
            logging.info("Debugging Predictive contract...")
            debug_contract_position(is_baseline=False)
        elif args.baseline_only:
            logging.info("Debugging Baseline contract...")
            debug_contract_position(is_baseline=True)
        return
    
    # Send tokens only if requested
    if args.send_tokens_only:
        if args.both:
            logging.info("Sending tokens to both contracts...")
            # First send to predictive
            result_pred = send_tokens_to_contract(is_baseline=False)
            if result_pred:
                logging.info("Tokens sent successfully to predictive contract!")
            else:
                logging.error("Failed to send tokens to predictive contract")
            
            # Then send to baseline
            result_base = send_tokens_to_contract(is_baseline=True)
            if result_base:
                logging.info("Tokens sent successfully to baseline contract!")
            else:
                logging.error("Failed to send tokens to baseline contract")
        else:
            is_baseline = args.baseline
            contract_type = "baseline" if is_baseline else "predictive"
            logging.info(f"Sending tokens to {contract_type} contract...")
            result = send_tokens_to_contract(is_baseline=is_baseline)
            if result:
                logging.info(f"Tokens sent successfully to {contract_type} contract!")
            else:
                logging.error(f"Failed to send tokens to {contract_type} contract")
        return
    
    def run_tests():
        logging.info("=== Starting Position Creation Test ===")
        
        # Get predicted price
        predicted_price = get_predicted_price()
        logging.info(f"Predicted price: {predicted_price['original']} ETH/USDC")
        
        # Test Predictive contract
        if args.both or (not args.baseline_only and not args.baseline):
            logging.info("\n=== Testing Predictive Contract ===")
            event_data = create_position(predicted_price, is_baseline=False)
            if event_data:
                save_event_to_csv(event_data)
                time.sleep(5)  # Wait for transaction to settle
        
        # Test Baseline contract
        if args.both or args.baseline_only or args.baseline:
            logging.info("\n=== Testing Baseline Contract ===")
            event_data = create_position(predicted_price, is_baseline=True)
            if event_data:
                save_event_to_csv(event_data)
        
        logging.info("=== Position Creation Test Completed ===")
    
    # Run immediately or schedule
    if args.schedule:
        logging.info("Scheduling test to run every hour")
        schedule.every().hour.do(run_tests)
        
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute for scheduled jobs
    else:
        run_tests()

    # در تابع main
    test_events(PREDICTIVE_MANAGER_ADDRESS, is_baseline=False)
    test_events(BASELINE_MANAGER_ADDRESS, is_baseline=True)

if __name__ == "__main__":
    main()