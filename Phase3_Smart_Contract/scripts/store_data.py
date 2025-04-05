import os
import json
import time
from datetime import datetime
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
import logging
import sqlite3
from pathlib import Path

# تنظیمات لاگینگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('store_data.log'),
        logging.StreamHandler()
    ]
)

# لود کردن متغیرهای محیطی
load_dotenv()

# تنظیمات اتصال به شبکه سپولیا
SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL")
BASELINE_MINIMAL_ADDRESS = os.getenv("BASELINE_MINIMAL_ADDRESS")
PREDICTIVE_MANAGER_ADDRESS = os.getenv("PREDICTIVE_MANAGER_ADDRESS")

# تنظیمات Web3
w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))

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

def setup_database():
    """راه‌اندازی پایگاه داده"""
    conn = sqlite3.connect('liquidity_data.db')
    c = conn.cursor()
    
    # ایجاد جدول برای ذخیره اطلاعات موقعیت‌های BaselineMinimal
    c.execute('''CREATE TABLE IF NOT EXISTS baseline_positions
                 (timestamp TEXT,
                  has_position BOOLEAN,
                  lower_tick INTEGER,
                  upper_tick INTEGER,
                  token0_balance REAL,
                  token1_balance REAL,
                  transaction_hash TEXT)''')
    
    # ایجاد جدول برای ذخیره اطلاعات موقعیت‌های PredictiveManager
    c.execute('''CREATE TABLE IF NOT EXISTS predictive_positions
                 (timestamp TEXT,
                  has_position BOOLEAN,
                  lower_tick INTEGER,
                  upper_tick INTEGER,
                  token0_balance REAL,
                  token1_balance REAL,
                  predicted_price REAL,
                  transaction_hash TEXT)''')
    
    # ایجاد جدول برای ذخیره رویدادها
    c.execute('''CREATE TABLE IF NOT EXISTS events
                 (timestamp TEXT,
                  contract_type TEXT,
                  event_type TEXT,
                  data TEXT)''')
    
    conn.commit()
    return conn

def store_baseline_position(conn, position_data):
    """ذخیره اطلاعات موقعیت BaselineMinimal در پایگاه داده"""
    c = conn.cursor()
    c.execute('''INSERT INTO baseline_positions VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (position_data['timestamp'],
               position_data['has_position'],
               position_data['lower_tick'],
               position_data['upper_tick'],
               position_data['token0_balance'],
               position_data['token1_balance'],
               position_data['transaction_hash']))
    conn.commit()

def store_predictive_position(conn, position_data):
    """ذخیره اطلاعات موقعیت PredictiveManager در پایگاه داده"""
    c = conn.cursor()
    c.execute('''INSERT INTO predictive_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (position_data['timestamp'],
               position_data['has_position'],
               position_data['lower_tick'],
               position_data['upper_tick'],
               position_data['token0_balance'],
               position_data['token1_balance'],
               position_data['predicted_price'],
               position_data['transaction_hash']))
    conn.commit()

def store_event(conn, contract_type, event_type, data):
    """ذخیره رویداد در پایگاه داده"""
    c = conn.cursor()
    c.execute('''INSERT INTO events VALUES (?, ?, ?, ?)''',
              (datetime.now().isoformat(),
               contract_type,
               event_type,
               json.dumps(data)))
    conn.commit()

def get_baseline_position_info():
    """دریافت اطلاعات موقعیت فعلی از قرارداد BaselineMinimal"""
    try:
        # دریافت اطلاعات موقعیت
        has_position = baseline_minimal.functions.hasPosition().call()
        current_token_id = baseline_minimal.functions.currentTokenId().call()
        lower_tick = baseline_minimal.functions.lowerTick().call() if has_position else 0
        upper_tick = baseline_minimal.functions.upperTick().call() if has_position else 0
        
        # دریافت موجودی توکن‌ها
        token0 = baseline_minimal.functions.token0().call()
        token1 = baseline_minimal.functions.token1().call()
        token0_balance = w3.eth.call({'to': token0, 'data': baseline_minimal.encodeABI(fn_name='balanceOf', args=[BASELINE_MINIMAL_ADDRESS])})
        token1_balance = w3.eth.call({'to': token1, 'data': baseline_minimal.encodeABI(fn_name='balanceOf', args=[BASELINE_MINIMAL_ADDRESS])})
        
        return {
            'timestamp': datetime.now().isoformat(),
            'has_position': has_position,
            'token_id': current_token_id,
            'lower_tick': lower_tick,
            'upper_tick': upper_tick,
            'token0_balance': float(token0_balance) / 1e18,
            'token1_balance': float(token1_balance) / 1e18,
            'transaction_hash': ''
        }
    except Exception as e:
        logging.error(f"خطا در دریافت اطلاعات موقعیت BaselineMinimal: {str(e)}")
        return None

def get_predictive_position_info():
    """دریافت اطلاعات موقعیت فعلی از قرارداد PredictiveManager"""
    try:
        # دریافت اطلاعات موقعیت
        has_position = predictive_manager.functions.hasPosition().call()
        current_token_id = predictive_manager.functions.currentTokenId().call()
        lower_tick = predictive_manager.functions.lowerTick().call() if has_position else 0
        upper_tick = predictive_manager.functions.upperTick().call() if has_position else 0
        predicted_price = predictive_manager.functions.predictedPrice().call()
        
        # دریافت موجودی توکن‌ها
        token0 = predictive_manager.functions.token0().call()
        token1 = predictive_manager.functions.token1().call()
        token0_balance = w3.eth.call({'to': token0, 'data': predictive_manager.encodeABI(fn_name='balanceOf', args=[PREDICTIVE_MANAGER_ADDRESS])})
        token1_balance = w3.eth.call({'to': token1, 'data': predictive_manager.encodeABI(fn_name='balanceOf', args=[PREDICTIVE_MANAGER_ADDRESS])})
        
        return {
            'timestamp': datetime.now().isoformat(),
            'has_position': has_position,
            'token_id': current_token_id,
            'lower_tick': lower_tick,
            'upper_tick': upper_tick,
            'token0_balance': float(token0_balance) / 1e18,
            'token1_balance': float(token1_balance) / 1e18,
            'predicted_price': float(predicted_price) / 1e18,
            'transaction_hash': ''
        }
    except Exception as e:
        logging.error(f"خطا در دریافت اطلاعات موقعیت PredictiveManager: {str(e)}")
        return None

def listen_for_events():
    """گوش دادن به رویدادهای قراردادها"""
    try:
        # فیلتر رویدادهای BaselineMinimal
        baseline_position_filter = baseline_minimal.events.PositionChanged.create_filter(fromBlock='latest')
        baseline_metrics_filter = baseline_minimal.events.BaselineAdjustmentMetrics.create_filter(fromBlock='latest')
        
        # فیلتر رویدادهای PredictiveManager
        predictive_position_filter = predictive_manager.events.PositionChanged.create_filter(fromBlock='latest')
        predictive_metrics_filter = predictive_manager.events.PredictiveAdjustmentMetrics.create_filter(fromBlock='latest')
        
        return {
            'baseline': (baseline_position_filter, baseline_metrics_filter),
            'predictive': (predictive_position_filter, predictive_metrics_filter)
        }
    except Exception as e:
        logging.error(f"خطا در ایجاد فیلتر رویدادها: {str(e)}")
        return None

def main():
    """تابع اصلی برنامه"""
    logging.info("🚀 شروع ذخیره‌سازی داده‌ها...")
    
    # بررسی اتصال به شبکه
    if not w3.is_connected():
        logging.error("❌ خطا در اتصال به شبکه اتریوم")
        return

    # راه‌اندازی پایگاه داده
    conn = setup_database()
    
    # ایجاد فیلترهای رویداد
    filters = listen_for_events()
    if not filters:
        return
    
    logging.info("📡 در حال گوش دادن به رویدادها...")
    
    # حلقه اصلی برنامه
    while True:
        try:
            # ذخیره اطلاعات موقعیت BaselineMinimal
            baseline_info = get_baseline_position_info()
            if baseline_info:
                store_baseline_position(conn, baseline_info)
                logging.info(f"✅ اطلاعات موقعیت BaselineMinimal ذخیره شد: {json.dumps(baseline_info, indent=2)}")
            
            # ذخیره اطلاعات موقعیت PredictiveManager
            predictive_info = get_predictive_position_info()
            if predictive_info:
                store_predictive_position(conn, predictive_info)
                logging.info(f"✅ اطلاعات موقعیت PredictiveManager ذخیره شد: {json.dumps(predictive_info, indent=2)}")
            
            # بررسی رویدادهای جدید BaselineMinimal
            for event in filters['baseline'][0].get_new_entries():
                store_event(conn, 'BaselineMinimal', 'PositionChanged', dict(event))
                logging.info(f"�� رویداد BaselineMinimal.PositionChanged ذخیره شد: {dict(event)}")
            
            for event in filters['baseline'][1].get_new_entries():
                store_event(conn, 'BaselineMinimal', 'BaselineAdjustmentMetrics', dict(event))
                logging.info(f"📊 رویداد BaselineMinimal.BaselineAdjustmentMetrics ذخیره شد: {dict(event)}")
            
            # بررسی رویدادهای جدید PredictiveManager
            for event in filters['predictive'][0].get_new_entries():
                store_event(conn, 'PredictiveManager', 'PositionChanged', dict(event))
                logging.info(f"📝 رویداد PredictiveManager.PositionChanged ذخیره شد: {dict(event)}")
            
            for event in filters['predictive'][1].get_new_entries():
                store_event(conn, 'PredictiveManager', 'PredictiveAdjustmentMetrics', dict(event))
                logging.info(f"📊 رویداد PredictiveManager.PredictiveAdjustmentMetrics ذخیره شد: {dict(event)}")
            
            # انتظار برای 1 دقیقه
            time.sleep(60)
            
        except KeyboardInterrupt:
            logging.info("🛑 برنامه توسط کاربر متوقف شد")
            break
        except Exception as e:
            logging.error(f"خطای کلی: {str(e)}")
            time.sleep(60)  # انتظار برای 1 دقیقه قبل از تلاش مجدد
    
    conn.close()

if __name__ == "__main__":
    main() 