import React, { useState } from 'react'
import Head from 'next/head'
import Link from 'next/link'
import { ethers } from 'ethers'

export default function Home() {
    const [isConnecting, setIsConnecting] = useState(false);
    const [connectionStatus, setConnectionStatus] = useState(null);

    const connectWallet = async () => {
        if (typeof window.ethereum !== 'undefined') {
            try {
                setIsConnecting(true);
                await window.ethereum.request({ method: 'eth_requestAccounts' });
                const provider = new ethers.providers.Web3Provider(window.ethereum);

                setConnectionStatus({
                    type: 'success',
                    message: 'Your wallet has been connected successfully.'
                });
            } catch (error) {
                setConnectionStatus({
                    type: 'danger',
                    message: 'Please make sure MetaMask is installed and unlocked.'
                });
            } finally {
                setIsConnecting(false);
            }
        } else {
            setConnectionStatus({
                type: 'warning',
                message: 'Please install MetaMask first.'
            });
        }
    }

    return (
        <>
            <Head>
                <title>Uniswap Marketplace</title>
                <meta name="description" content="Decentralized exchange with price predictions" />
            </Head>

            <div className="container py-5">
                <div className="text-center mb-5">
                    <h1 className="display-4 mb-3">Uniswap Marketplace</h1>
                    <p className="lead">Connect your wallet to get started</p>
                </div>

                <div className="row justify-content-center">
                    <div className="col-md-6">
                        <div className="card shadow-sm">
                            <div className="card-body text-center p-5">
                                <h2 className="h4 mb-4">Welcome to Decentralized Exchange</h2>

                                {connectionStatus && (
                                    <div className={`alert alert-${connectionStatus.type} mb-4`} role="alert">
                                        {connectionStatus.message}
                                    </div>
                                )}

                                <div className="d-grid gap-3">
                                    <button
                                        className="btn btn-primary btn-lg"
                                        onClick={connectWallet}
                                        disabled={isConnecting}
                                    >
                                        {isConnecting ? (
                                            <>
                                                <span className="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                                                Connecting...
                                            </>
                                        ) : 'Connect MetaMask'}
                                    </button>

                                    <Link href="/Dashboard" className="btn btn-outline-secondary">
                                        View Dashboard
                                    </Link>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </>
    )
} 