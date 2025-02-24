import requests
import pandas as pd
import datetime
import numpy as np
import joblib
from tensorflow.keras.models import load_model
from flask import Flask, request, jsonify

def get_binance_data(symbol, interval, limit=50):
    url = "https://api.binance.com/api/v3/klines"
    end_time = datetime.datetime.now()
    start_time = end_time - datetime.timedelta(hours=4 * limit)
    
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": int(start_time.timestamp() * 1000),
        "endTime": int(end_time.timestamp() * 1000),
        "limit": limit
    }
    
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume", "close_time", 
        "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume", 
        "taker_buy_quote_asset_volume", "ignore"
    ])
    
    df["open_time"] = pd.to_datetime(df["open_time"], unit='ms')
    df.set_index("open_time", inplace=True)
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df

def add_indicators(df):
    df['SMA'] = df['close'].rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (df['close'].diff(1).clip(lower=0).rolling(14).mean() / 
                                      df['close'].diff(1).clip(upper=0).abs().rolling(14).mean())))
    df['Bollinger_Upper'] = df['close'].rolling(20).mean() + (df['close'].rolling(20).std() * 2)
    df.dropna(inplace=True)
    return df

def preprocess_input(df, scaler, seq_length=50):
    df = df[['close', 'open', 'high', 'low', 'volume', 'SMA', 'RSI', 'Bollinger_Upper']]
    normalized_data = scaler.transform(df)
    input_seq = np.array([normalized_data[-seq_length:]])
    return input_seq

def predict_price(df, model, scaler):
    input_seq = preprocess_input(df, scaler)
    prediction = model.predict(input_seq)
    predicted_price = scaler.inverse_transform(
        np.concatenate((prediction.reshape(-1, 1), np.zeros((prediction.shape[0], 7))), axis=1)
    )[:, 0]
    return predicted_price[0]

app = Flask(__name__)

# Load trained model and correct scaler
model = load_model('model_LSTM_4h.keras')
scaler = joblib.load('scaler_4h.pkl')

@app.route('/predict_price', methods=['GET'])
def fetch_and_predict():
    symbol = request.args.get('symbol', 'BTCUSDT')
    interval = request.args.get('interval', '4h')
    
    df = get_binance_data(symbol, interval)
    df = add_indicators(df)
    
    predicted_price = predict_price(df, model, scaler)
    
    return jsonify({
        "symbol": symbol,
        "interval": interval,
        "predicted_price": predicted_price
    })

if __name__ == '__main__':
    app.run(debug=True)
