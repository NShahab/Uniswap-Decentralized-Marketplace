require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

module.exports = {
  solidity: "0.8.20",
  paths: {
    sources: "./Phase3_Smart_Contract/contracts", // مسیر جدید به پوشه قراردادها
    tests: "./Phase3_Smart_Contract/test",
    scripts: "./Phase3_Smart_Contract/scripts"
  },
  networks: {
    sepolia: {
      url: process.env.SEPOLIA_RPC_URL,  // لینک Infura یا Alchemy
      accounts: [process.env.PRIVATE_KEY], // کلید خصوصی والت متامسک
    },
  },
};