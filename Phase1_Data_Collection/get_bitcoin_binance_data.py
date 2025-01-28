import requests
import pandas as pd
import datetime
from tenacity import retry, stop_after_attempt, wait_fixed
import os

@retry(stop=stop_after_attempt(5), wait=wait_fixed(10))
def get_binance_data(symbol, interval, start, end):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000),
        "limit": 1000
    }

    data = []
    while True:
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            klines = response.json()
            if not klines:
                break
            data.extend(klines)
            params["startTime"] = klines[-1][0] + 1
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            raise

    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume", "close_time", 
        "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume", 
        "taker_buy_quote_asset_volume", "ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit='ms')
    df.set_index("open_time", inplace=True)
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df

def download_new_data(symbol, interval, start_date, end_date):
    # دانلود داده‌های جدید
    df = get_binance_data(symbol, interval, start_date, end_date)

    # ساخت نام فایل جدید
    new_file_name = f'binance_data_{start_date.strftime("%Y%m%d")}_to_{end_date.strftime("%Y%m%d")}.csv'

    # ذخیره‌سازی داده‌های جدید در یک فایل CSV
    df.to_csv(new_file_name, index=True)
    print(f"New data from {start_date} to {end_date} saved to {new_file_name}.")
    return new_file_name

def update_data(symbol, interval):
    # تاریخ امروز
    today = datetime.datetime.now()

    # بررسی وجود آخرین فایل دانلود شده
    existing_files = [f for f in os.listdir() if f.startswith('binance_data_') and f.endswith('.csv')]
    last_file_date = None

    # پیدا کردن آخرین تاریخ موجود
    if existing_files:
        # خواندن آخرین فایل
        last_file = sorted(existing_files)[-1]
        last_start_date_str = last_file.split('_')[2]  # استخراج تاریخ شروع از نام فایل
        last_file_date = datetime.datetime.strptime(last_start_date_str, "%Y%m%d")

    # اگر آخرین تاریخ موجود نیست یا امروز بعد از آن است
    if last_file_date is None or today > last_file_date:
        # دانلود داده‌های جدید از آخرین تاریخ تا امروز
        if last_file_date is None:
            # اگر هیچ فایلی وجود نداشته باشد، از تاریخ شروع دلخواه شروع می‌کنیم
            last_file_date = datetime.datetime(2018, 1, 1)  # تاریخ شروع پیش‌فرض

        # دانلود داده‌های جدید
        download_new_data(symbol, interval, last_file_date, today)
    else:
        print("No new data to download.")

# مشخصات
symbol = "BTCUSDT"
interval = "15m"

# به‌روزرسانی داده‌ها
update_data(symbol, interval)
