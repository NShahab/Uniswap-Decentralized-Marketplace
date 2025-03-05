require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config({ path: '../.env' });

module.exports = {
    solidity: "0.8.20",
    paths: {
        sources: "./contracts",
        tests: "./test",
        cache: "./cache",
        artifacts: "./artifacts"
    },
    networks: {
        sepolia: {
            url: process.env.SEPOLIA_RPC_URL,
            accounts: [process.env.PRIVATE_KEY],
        },
        hardhat: {
            chainId: 31337,
        }
    },
    gasReporter: {
        enabled: true,
        currency: "USD",
        coinmarketcap: process.env.COINMARKETCAP_API_KEY
    },
    etherscan: {
        apiKey: process.env.ETHERSCAN_API_KEY
    }
}; 