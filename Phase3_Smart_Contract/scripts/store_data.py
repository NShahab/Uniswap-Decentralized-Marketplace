import sqlite3
from web3 import Web3
from datetime import datetime
import json
import os

class DataStore:
    def __init__(self, db_path='liquidity_data.db'):
        self.db_path = db_path
        self.setup_database()
        
    def setup_database(self):
        """Create the database and tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Create table for price and liquidity data
        c.execute('''
            CREATE TABLE IF NOT EXISTS liquidity_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                actual_price REAL,
                predicted_price REAL,
                increased_liquidity BOOLEAN,
                liquidity_before REAL,
                liquidity_after REAL,
                gas_used INTEGER,
                transaction_hash TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def store_event_data(self, event_data):
        """Store event data in the database"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO liquidity_management 
            (timestamp, actual_price, predicted_price, increased_liquidity, 
             liquidity_before, liquidity_after, gas_used, transaction_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.fromtimestamp(event_data['timestamp']),
            event_data['actualPrice'],
            event_data['predictedPrice'],
            event_data['increasedLiquidity'],
            event_data['liquidityBefore'],
            event_data['liquidityAfter'],
            event_data['gasUsed'],
            event_data.get('transactionHash', '')
        ))
        
        conn.commit()
        conn.close()
    
    def get_performance_metrics(self):
        """Calculate performance metrics"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Get basic statistics
        c.execute('''
            SELECT 
                COUNT(*) as total_operations,
                AVG(gas_used) as avg_gas,
                SUM(CASE WHEN increased_liquidity = 1 THEN 1 ELSE 0 END) as increases,
                SUM(CASE WHEN increased_liquidity = 0 THEN 1 ELSE 0 END) as decreases
            FROM liquidity_management
        ''')
        
        stats = c.fetchone()
        
        # Calculate price prediction accuracy
        c.execute('''
            SELECT 
                AVG(ABS(predicted_price - actual_price) / actual_price * 100) as avg_prediction_error
            FROM liquidity_management
        ''')
        
        error = c.fetchone()
        
        conn.close()
        
        return {
            'total_operations': stats[0],
            'average_gas_used': stats[1],
            'liquidity_increases': stats[2],
            'liquidity_decreases': stats[3],
            'average_prediction_error': error[0]
        }

def main():
    # Initialize the data store
    data_store = DataStore()
    
    # Example of storing event data
    event_data = {
        'timestamp': int(datetime.now().timestamp()),
        'actualPrice': 1800.50,
        'predictedPrice': 1850.75,
        'increasedLiquidity': True,
        'liquidityBefore': 1000.0,
        'liquidityAfter': 1200.0,
        'gasUsed': 150000,
        'transactionHash': '0x123...'
    }
    
    # Store the data
    data_store.store_event_data(event_data)
    
    # Get and print performance metrics
    metrics = data_store.get_performance_metrics()
    print("Performance Metrics:")
    print(f"Total Operations: {metrics['total_operations']}")
    print(f"Average Gas Used: {metrics['average_gas_used']}")
    print(f"Liquidity Increases: {metrics['liquidity_increases']}")
    print(f"Liquidity Decreases: {metrics['liquidity_decreases']}")
    print(f"Average Prediction Error: {metrics['average_prediction_error']}%")

if __name__ == "__main__":
    main() 