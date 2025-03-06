// API route that acts as a proxy for the prediction API
export default async function handler(req, res) {
    try {
        const response = await fetch('http://95.216.156.73:5000/predict_price?symbol=BTCUSDT&interval=4h');
        const data = await response.json();

        // Return the data to the client
        res.status(200).json(data);
    } catch (error) {
        console.error('Error fetching prediction:', error);
        res.status(500).json({ error: 'Failed to fetch prediction data' });
    }
} 