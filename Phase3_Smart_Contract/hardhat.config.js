require("@nomicfoundation/hardhat-toolbox");
require("hardhat-deploy");
require("dotenv").config();

// Ensure environment variables are handled gracefully
const SEPOLIA_RPC_URL = process.env.SEPOLIA_RPC_URL || "https://rpc.sepolia.org"; // Add default or empty string
const PRIVATE_KEY = process.env.PRIVATE_KEY || "";
const ETHERSCAN_API_KEY = process.env.ETHERSCAN_API_KEY || "";

module.exports = {
    solidity: {
        compilers: [
            { // --- Keep only 0.7.6 compiler ---
                version: "0.7.6",
                settings: {
                    optimizer: {
                        enabled: true,
                        runs: 200
                    }
                }
            }
            // --- Removed 0.8.19 compiler ---
        ]
    },
    networks: {
        hardhat: { // Optional: Add hardhat network config if needed
            chainId: 31337,
        },
        sepolia: {
            url: SEPOLIA_RPC_URL,
            accounts: PRIVATE_KEY !== "" ? [PRIVATE_KEY] : [],
            chainId: 11155111,
            gas: 8000000,             // افزایش به 8 میلیون
            gasPrice: "auto",
            maxFeePerGas: 100000000000,  // 100 gwei
            maxPriorityFeePerGas: 5000000000,  // 5 gwei
            timeout: 180000           // افزایش به 3 دقیقه
        }
        // Add other networks if needed
    },
    etherscan: {
        apiKey: ETHERSCAN_API_KEY
    },
    namedAccounts: {
        deployer: {
            default: 0, // Default to the first account from the accounts array
        }
    },
    paths: { // Optional: Define paths if your structure differs
        sources: "./contracts",
        tests: "./test",
        cache: "./cache",
        artifacts: "./artifacts"
    },
};