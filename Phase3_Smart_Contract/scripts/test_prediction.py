import os
import json
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

def load_contract_abi(contract_name):
    """لود کردن ABI قرارداد"""
    artifacts_path = f"artifacts/contracts/{contract_name}.sol/{contract_name}.json"
    with open(artifacts_path) as f:
        contract_json = json.load(f)
        return contract_json["abi"]

def send_prediction(predicted_price):
    """ارسال قیمت پیش‌بینی شده به قرارداد"""
    try:
        # لود کردن ABI و ایجاد آبجکت قرارداد
        predictive_manager_abi = load_contract_abi("PredictiveLiquidityManager")
        predictive_manager = w3.eth.contract(
            address=PREDICTIVE_MANAGER_ADDRESS,
            abi=predictive_manager_abi
        )

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
        
        if receipt['status'] == 1:
            logging.info(f"✅ تراکنش موفق - هش: {tx_hash.hex()}")
            logging.info(f"گس مصرفی: {receipt['gasUsed']}")
            return True
        else:
            logging.error(f"❌ تراکنش ناموفق - هش: {tx_hash.hex()}")
            return False

    except Exception as e:
        logging.error(f"خطا در ارسال پیش‌بینی: {str(e)}")
        return False

def main():
    """تابع اصلی برنامه"""
    # تست با یک قیمت نمونه (مثلاً 1800 دلار)
    test_price = 1800
    logging.info(f"ارسال قیمت پیش‌بینی شده: {test_price}")
    success = send_prediction(test_price)
    
    if success:
        logging.info("✅ تست موفقیت‌آمیز بود")
    else:
        logging.error("❌ تست ناموفق بود")

if __name__ == "__main__":
    main() 