// hardhat.config.js
// No changes needed from the version previously configured for forking.
// Ensure MAINNET_RPC_URL is correctly set in your .env file.
require("@nomicfoundation/hardhat-toolbox");
require("hardhat-deploy");
require("dotenv").config();

const MAINNET_RPC_URL = process.env.MAINNET_RPC_URL || "";
const PRIVATE_KEY = process.env.PRIVATE_KEY || "";
const ETHERSCAN_API_KEY = process.env.ETHERSCAN_API_KEY || "";

module.exports = {
    solidity: {
        compilers: [
            {
                version: "0.7.6",
                settings: { optimizer: { enabled: true, runs: 200 } }
            }
        ]
    },
    defaultNetwork: "hardhat",
    networks: {
        hardhat: { // For running the local node: npx hardhat node
            chainId: 31337,
            forking: {
                url: MAINNET_RPC_URL,
            },
            // accounts: PRIVATE_KEY !== "" ? [{ privateKey: PRIVATE_KEY, balance: "100000000000000000000" }] : [], // Optional: Pre-fund deployer
            gas: "auto",
            gasPrice: "auto"
        },
        localhost: { // For connecting scripts to the running node: --network localhost
            url: "http://127.0.0.1:8545",
            chainId: 31337,
            accounts: PRIVATE_KEY !== "" ? [PRIVATE_KEY] : [],
            timeout: 120000
        }
    },
    etherscan: {
        // apiKey: ETHERSCAN_API_KEY // Not needed for fork
    },
    namedAccounts: {
        deployer: { default: 0 }
    },
    paths: {
        sources: "./contracts",
        tests: "./test", // Assuming tests are in 'test' directory now based on paths in bash script
        cache: "./cache",
        artifacts: "./artifacts"
    },
    mocha: {
        timeout: 180000 // 3 minutes
    }
};