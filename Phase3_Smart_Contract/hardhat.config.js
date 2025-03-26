require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();
task("balance", "نمایش موجودی حساب", async () => {
    const [account] = await ethers.getSigners();
    const balance = await ethers.provider.getBalance(account.address);
    console.log(`موجودی: ${ethers.formatEther(balance)} ETH`);
});
/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
    solidity: {
        version: "0.8.24",
        settings: {
            optimizer: {
                enabled: true,
                runs: 200
            }
        }
    },
    networks: {
        sepolia: {
            url: process.env.SEPOLIA_RPC_URL,
            accounts: process.env.PRIVATE_KEY ? [process.env.PRIVATE_KEY] : [],
            chainId: 11155111, // حتماً اضافه شود
            gas: "auto"
        }
    },
    etherscan: {
        apiKey: process.env.ETHERSCAN_API_KEY
    },
    paths: {
        sources: "./contracts",
        tests: "./test",
        cache: "./cache",
        artifacts: "./artifacts"
    }
}; 