import os
import json
import time
from datetime import datetime
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
from pathlib import Path
import logging

# تنظیمات لاگینگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('price_keeper.log'),
        logging.StreamHandler()
    ]
)

# لود کردن متغیرهای محیطی
load_dotenv()

# تنظیمات اتصال به شبکه سپولیا
SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
BASELINE_MINIMAL_ADDRESS = os.getenv("BASELINE_MINIMAL_ADDRESS")
PREDICTIVE_MANAGER_ADDRESS = os.getenv("PREDICTIVE_MANAGER_ADDRESS")

# تنظیمات Web3
w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
account = Account.from_key(PRIVATE_KEY)

# لود کردن ABI قرارداد
def load_contract_abi(contract_name):
    artifacts_path = Path("artifacts/contracts") / f"{contract_name}.sol" / f"{contract_name}.json"
    with open(artifacts_path) as f:
        contract_json = json.load(f)
        return contract_json["abi"]

# تنظیم قراردادها
baseline_minimal_abi = load_contract_abi("BaselineMinimal")
predictive_manager_abi = load_contract_abi("PredictiveLiquidityManager")

baseline_minimal = w3.eth.contract(
    address=BASELINE_MINIMAL_ADDRESS,
    abi=baseline_minimal_abi
)

predictive_manager = w3.eth.contract(
    address=PREDICTIVE_MANAGER_ADDRESS,
    abi=predictive_manager_abi
)

def adjust_baseline_liquidity():
    """تنظیم نقدینگی در قرارداد BaselineMinimal"""
    try:
        # بررسی موجودی اتر
        balance = w3.eth.get_balance(account.address)
        min_balance = w3.to_wei(0.1, 'ether')  # حداقل 0.1 ETH
        
        if balance < min_balance:
            logging.warning(f"موجودی کم است: {w3.from_wei(balance, 'ether')} ETH")
            return False

        # تخمین گس
        gas_estimate = baseline_minimal.functions.adjustLiquidityWithCurrentPrice().estimate_gas({
            'from': account.address,
            'gasPrice': w3.eth.gas_price
        })
        
        # افزایش گس لیمیت برای اطمینان
        gas_limit = int(gas_estimate * 1.2)
        gas_price = w3.eth.gas_price

        # ساخت تراکنش
        transaction = baseline_minimal.functions.adjustLiquidityWithCurrentPrice().build_transaction({
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
            logging.info(f"✅ تراکنش BaselineMinimal موفق - هش: {tx_hash.hex()}")
            logging.info(f"گس مصرفی: {receipt['gasUsed']}")
            return True
        else:
            logging.error(f"❌ تراکنش BaselineMinimal ناموفق - هش: {tx_hash.hex()}")
            return False

    except Exception as e:
        logging.error(f"خطا در تنظیم نقدینگی BaselineMinimal: {str(e)}")
        return False

def adjust_predictive_liquidity():
    """تنظیم نقدینگی در قرارداد PredictiveLiquidityManager"""
    try:
        # بررسی موجودی اتر
        balance = w3.eth.get_balance(account.address)
        min_balance = w3.to_wei(0.1, 'ether')  # حداقل 0.1 ETH
        
        if balance < min_balance:
            logging.warning(f"موجودی کم است: {w3.from_wei(balance, 'ether')} ETH")
            return False

        # تخمین گس
        gas_estimate = predictive_manager.functions.adjustLiquidityWithPrediction().estimate_gas({
            'from': account.address,
            'gasPrice': w3.eth.gas_price
        })
        
        # افزایش گس لیمیت برای اطمینان
        gas_limit = int(gas_estimate * 1.2)
        gas_price = w3.eth.gas_price

        # ساخت تراکنش
        transaction = predictive_manager.functions.adjustLiquidityWithPrediction().build_transaction({
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
            logging.info(f"✅ تراکنش PredictiveManager موفق - هش: {tx_hash.hex()}")
            logging.info(f"گس مصرفی: {receipt['gasUsed']}")
            return True
        else:
            logging.error(f"❌ تراکنش PredictiveManager ناموفق - هش: {tx_hash.hex()}")
            return False

    except Exception as e:
        logging.error(f"خطا در تنظیم نقدینگی PredictiveManager: {str(e)}")
        return False

def main():
    """تابع اصلی برنامه"""
    logging.info("🚀 شروع مانیتورینگ قیمت و تنظیم نقدینگی...")
    
    # بررسی اتصال به شبکه
    if not w3.is_connected():
        logging.error("❌ خطا در اتصال به شبکه اتریوم")
        return

    logging.info(f"📡 متصل به شبکه سپولیا - آدرس کیف پول: {account.address}")
    logging.info(f"BaselineMinimal آدرس: {BASELINE_MINIMAL_ADDRESS}")
    logging.info(f"PredictiveManager آدرس: {PREDICTIVE_MANAGER_ADDRESS}")
    
    # حلقه اصلی برنامه
    while True:
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logging.info(f"⏰ زمان بررسی: {current_time}")
            
            # تنظیم نقدینگی در BaselineMinimal
            baseline_success = adjust_baseline_liquidity()
            if baseline_success:
                logging.info("✅ تنظیم نقدینگی BaselineMinimal با موفقیت انجام شد")
            else:
                logging.warning("⚠️ تنظیم نقدینگی BaselineMinimal ناموفق بود")

            # تنظیم نقدینگی در PredictiveManager
            predictive_success = adjust_predictive_liquidity()
            if predictive_success:
                logging.info("✅ تنظیم نقدینگی PredictiveManager با موفقیت انجام شد")
            else:
                logging.warning("⚠️ تنظیم نقدینگی PredictiveManager ناموفق بود")
            
            # انتظار برای 5 دقیقه
            time.sleep(300)

        except KeyboardInterrupt:
            logging.info("🛑 برنامه توسط کاربر متوقف شد")
            break
        except Exception as e:
            logging.error(f"خطای کلی: {str(e)}")
            time.sleep(60)  # انتظار برای 1 دقیقه قبل از تلاش مجدد

if __name__ == "__main__":
    main() 