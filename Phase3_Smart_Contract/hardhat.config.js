// hardhat.config.js
require("@nomicfoundation/hardhat-toolbox");
require("hardhat-deploy");
require("dotenv").config();

// --- Mainnet RPC URL ---
// Ensure you have a MAINNET_RPC_URL in your .env file
const MAINNET_RPC_URL = process.env.MAINNET_RPC_URL || "";
const PRIVATE_KEY = process.env.PRIVATE_KEY || "";
const ETHERSCAN_API_KEY = process.env.ETHERSCAN_API_KEY || ""; // Not needed for local fork

module.exports = {
    solidity: {
        compilers: [
            {
                version: "0.7.6",
                settings: {
                    optimizer: {
                        enabled: true,
                        runs: 200
                    }
                }
            }
        ]
    },
    defaultNetwork: "hardhat", // Set default to hardhat for easy execution
    networks: {
        hardhat: { // Configuration for the local Hardhat node (used for forking)
            chainId: 31337, // Default Hardhat Network chainId
            forking: {
                url: MAINNET_RPC_URL,
                // blockNumber: <OPTIONAL_PINNED_BLOCK_NUMBER> // Can pin to a specific block if needed
            },
            // Optional: Allocate funds to the deployer account on fork startup
            // accounts: PRIVATE_KEY !== "" ? [{ privateKey: PRIVATE_KEY, balance: "100000000000000000000" }] : [], // Example: 100 ETH
            gas: "auto",     // Or set a specific limit if needed
            gasPrice: "auto" // Let Hardhat estimate
        },
        localhost: { // Configuration for connecting to the running Hardhat node from scripts/tests
            url: "http://127.0.0.1:8545",
            chainId: 31337, // Match the chainId of the hardhat network
            accounts: PRIVATE_KEY !== "" ? [PRIVATE_KEY] : [],
            timeout: 120000
        }
        /* // Sepolia configuration (keep if needed for other purposes, otherwise remove)
        sepolia: {
            url: SEPOLIA_RPC_URL, // Make sure you have a SEPOLIA_RPC_URL if you keep this
            accounts: PRIVATE_KEY !== "" ? [PRIVATE_KEY] : [],
            chainId: 11155111,
            gas: 3000000,
            gasPrice: 30000000000,
            timeout: 120000
        }
        */
    },
    etherscan: {
        // apiKey: ETHERSCAN_API_KEY // Keep if you verify on mainnet/testnets, not needed for fork
    },
    namedAccounts: {
        deployer: {
            default: 0, // Uses the first account in the 'accounts' array for the network
        }
    },
    paths: {
        sources: "./contracts",
        tests: "./tests", // Changed from ./test to ./tests based on python file location
        cache: "./cache",
        artifacts: "./artifacts"
    },
    mocha: {
        timeout: 180000 // 3 minutes
    }
};