import React, { useState, useEffect } from "react";
import Head from 'next/head';

export default function Dashboard() {
    const [predictedPrice, setPredictedPrice] = useState(null);
    const [currentPrice, setCurrentPrice] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);

    // Use our local API proxy instead of the external API directly
    const PREDICTION_API = "/api/prediction";
    const BINANCE_API = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT";

    useEffect(() => {
        const fetchData = async () => {
            try {
                setIsLoading(true);

                // Fetch current price from Binance
                const binanceResponse = await fetch(BINANCE_API);
                if (binanceResponse.ok) {
                    const binanceData = await binanceResponse.json();
                    setCurrentPrice(parseFloat(binanceData.price));
                } else {
                    throw new Error("Failed to fetch Binance price");
                }

                // Fetch predicted price from our local API proxy
                const predictionResponse = await fetch(PREDICTION_API);
                if (predictionResponse.ok) {
                    const predictionData = await predictionResponse.json();
                    setPredictedPrice(predictionData.predicted_price);
                } else {
                    throw new Error("Failed to fetch prediction data");
                }

                setError(null);
            } catch (err) {
                console.error("Error fetching data:", err);
                setError("Error fetching data. Please try again.");
            } finally {
                setIsLoading(false);
            }
        };

        fetchData();
        const interval = setInterval(fetchData, 30000); // Update every 30 seconds
        return () => clearInterval(interval);
    }, []);

    const formatPrice = (price) => {
        return price ? price.toLocaleString('en-US', {
            minimumFractionDigits: 3,
            maximumFractionDigits: 3
        }) : "N/A";
    };

    return (
        <>
            <Head>
                <title>Bitcoin Price Dashboard</title>
                <meta name="description" content="Bitcoin price prediction dashboard" />
            </Head>

            <div className="container py-4">
                <div className="text-center mb-4">
                    <h1 className="h3 mb-2">📈 Bitcoin Price Dashboard</h1>
                    <p className="text-muted">Connect wallet to start trading</p>
                </div>

                <div className="card mb-4 shadow-sm">
                    <div className="card-body">
                        <div className="mb-4">
                            <h5 className="card-title">📊 BTC/USDT Current Price</h5>
                            <div className="text-center">
                                <p className="text-muted mb-1">Market Price</p>
                                <h2 className="text-primary">
                                    {isLoading ? (
                                        <div className="spinner-border spinner-border-sm text-primary" role="status">
                                            <span className="visually-hidden">Loading...</span>
                                        </div>
                                    ) : (
                                        `$${formatPrice(currentPrice)}`
                                    )}
                                </h2>
                            </div>
                        </div>

                        <hr />

                        <div>
                            <h5 className="card-title">🔮 4h Price Prediction</h5>
                            <div className="text-center">
                                <p className="text-muted mb-1">Predicted Price</p>
                                <h2 className="text-success">
                                    {isLoading ? (
                                        <div className="spinner-border spinner-border-sm text-success" role="status">
                                            <span className="visually-hidden">Loading...</span>
                                        </div>
                                    ) : (
                                        `$${formatPrice(predictedPrice)}`
                                    )}
                                </h2>
                            </div>
                        </div>

                        {error && (
                            <div className="alert alert-warning mt-3" role="alert">
                                {error}
                            </div>
                        )}
                    </div>
                </div>

                <div className="card shadow-sm">
                    <div className="card-body">
                        <h5 className="card-title">💡 Quick Guide</h5>
                        <ul className="list-unstyled">
                            <li>1. Connect MetaMask</li>
                            <li>2. Monitor real-time prices and predictions</li>
                            <li>3. Trade based on AI predictions</li>
                        </ul>
                    </div>
                </div>
            </div>
        </>
    );
}
