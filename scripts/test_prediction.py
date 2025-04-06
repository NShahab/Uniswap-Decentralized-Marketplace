import os
import json
import sqlite3
from datetime import datetime
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
import logging

# تنظیمات لاگینگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('test_prediction.log'),
        logging.StreamHandler()
    ]
)

# لود کردن متغیرهای محیطی
load_dotenv()

# تنظیمات اتصال به شبکه سپولیا
SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
PREDICTIVE_MANAGER_ADDRESS = os.getenv("PREDICTIVE_MANAGER_ADDRESS")

# تنظیمات Web3
w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
account = Account.from_key(PRIVATE_KEY)

def setup_database():
    """راه‌اندازی پایگاه داده"""
    conn = sqlite3.connect('prediction_results.db')
    c = conn.cursor()
    
    # ایجاد جدول برای ذخیره نتایج پیش‌بینی
    c.execute('''CREATE TABLE IF NOT EXISTS predictions
                 (timestamp TEXT,
                  predicted_price REAL,
                  actual_price REAL,
                  lower_tick INTEGER,
                  upper_tick INTEGER,
                  gas_used INTEGER,
                  transaction_hash TEXT,
                  status TEXT)''')
    
    conn.commit()
    return conn

def load_contract_abi(contract_name):
    """لود کردن ABI قرارداد"""
    artifacts_path = f"artifacts/contracts/{contract_name}.sol/{contract_name}.json"
    with open(artifacts_path) as f:
        contract_json = json.load(f)
        return contract_json["abi"]

def store_prediction_result(conn, data):
    """ذخیره نتیجه پیش‌بینی در پایگاه داده"""
    c = conn.cursor()
    c.execute('''INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (data['timestamp'],
               data['predicted_price'],
               data['actual_price'],
               data['lower_tick'],
               data['upper_tick'],
               data['gas_used'],
               data['transaction_hash'],
               data['status']))
    conn.commit()

def get_current_price(contract):
    """دریافت قیمت فعلی از قرارداد"""
    try:
        pool_address = contract.functions.getPoolAddress().call()
        pool_abi = load_contract_abi("IUniswapV3Pool")
        pool = w3.eth.contract(address=pool_address, abi=pool_abi)
        slot0 = pool.functions.slot0().call()
        sqrtPriceX96 = slot0[0]
        
        # تبدیل sqrtPriceX96 به قیمت
        price = (sqrtPriceX96 ** 2) / (2 ** 192)
        return float(price)
    except Exception as e:
        logging.error(f"خطا در دریافت قیمت فعلی: {str(e)}")
        return None

def send_prediction(predicted_price, conn):
    """ارسال قیمت پیش‌بینی شده به قرارداد"""
    try:
        # لود کردن ABI و ایجاد آبجکت قرارداد
        predictive_manager_abi = load_contract_abi("PredictiveLiquidityManager")
        predictive_manager = w3.eth.contract(
            address=PREDICTIVE_MANAGER_ADDRESS,
            abi=predictive_manager_abi
        )

        # دریافت قیمت فعلی
        actual_price = get_current_price(predictive_manager)

        # تبدیل قیمت به فرمت مناسب (18 دسیمال)
        price_in_wei = int(predicted_price * 1e18)

        # تخمین گس
        gas_estimate = predictive_manager.functions.updatePredictionAndAdjust(price_in_wei).estimate_gas({
            'from': account.address,
            'gasPrice': w3.eth.gas_price
        })
        
        # افزایش گس لیمیت برای اطمینان
        gas_limit = int(gas_estimate * 1.2)
        gas_price = w3.eth.gas_price

        # ساخت تراکنش
        transaction = predictive_manager.functions.updatePredictionAndAdjust(price_in_wei).build_transaction({
            'from': account.address,
            'gas': gas_limit,
            'gasPrice': gas_price,
            'nonce': w3.eth.get_transaction_count(account.address)
        })

        # امضا و ارسال تراکنش
        signed_txn = w3.eth.account.sign_transaction(transaction, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        
        # انتظار برای تأیید تراکنش
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        # دریافت اطلاعات موقعیت فعلی
        position_details = predictive_manager.functions.getActivePositionDetails().call()
        
        # ذخیره نتیجه در پایگاه داده
        result_data = {
            'timestamp': datetime.now().isoformat(),
            'predicted_price': predicted_price,
            'actual_price': actual_price if actual_price else 0,
            'lower_tick': position_details[2],  # tickLower
            'upper_tick': position_details[3],  # tickUpper
            'gas_used': receipt['gasUsed'],
            'transaction_hash': tx_hash.hex(),
            'status': 'success' if receipt['status'] == 1 else 'failed'
        }
        store_prediction_result(conn, result_data)
        
        if receipt['status'] == 1:
            logging.info(f"✅ تراکنش موفق - هش: {tx_hash.hex()}")
            logging.info(f"گس مصرفی: {receipt['gasUsed']}")
            logging.info(f"محدوده tick: {position_details[2]} تا {position_details[3]}")
            return True
        else:
            logging.error(f"❌ تراکنش ناموفق - هش: {tx_hash.hex()}")
            return False

    except Exception as e:
        logging.error(f"خطا در ارسال پیش‌بینی: {str(e)}")
        return False

def main():
    """تابع اصلی برنامه"""
    # راه‌اندازی پایگاه داده
    conn = setup_database()
    
    try:
        # تست با یک قیمت نمونه (مثلاً 1800 دلار)
        test_price = 1800
        logging.info(f"ارسال قیمت پیش‌بینی شده: {test_price}")
        success = send_prediction(test_price, conn)
        
        if success:
            logging.info("✅ تست موفقیت‌آمیز بود")
        else:
            logging.error("❌ تست ناموفق بود")
            
    finally:
        conn.close()

if __name__ == "__main__":
    main() 