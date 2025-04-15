// scripts/deploy.js
const hre = require("hardhat");
const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

// آدرس‌های رسمی Uniswap V3 در شبکه Sepolia
const UNISWAP_V3 = {
    FACTORY: "0x0227628f3F023bb0B980b67D528571c95c6DaC1c",
    POSITION_MANAGER: "0x1238536071E1c677A632429e3655c799b22cDA52",
    SWAP_ROUTER: "0x3bFA4769FB09eefC5a80d6E87c3B9C650f7Ae48E"
};

// آدرس توکن‌ها در Sepolia
const TOKENS = {
    USDC: "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238", // USDC رسمی Sepolia
    WETH: "0x7b79995e5f793A07Bc00c21412e50Ecae098E7f9"  // WETH رسمی Sepolia
};

// تنظیمات استقرار
const DEPLOY_SETTINGS = {
    FEE_TIER: 3000, // 0.3%
    GAS_LIMIT: 5000000, // 5 میلیون گس
    GAS_PRICE: ethers.utils.parseUnits("50", "gwei") // 50 gwei
};

async function main() {
    try {
        const [deployer] = await hre.ethers.getSigners();

        console.log("\n=============== Deployment Information ===============");
        console.log(`Network: ${hre.network.name}`);
        console.log(`Deployer: ${deployer.address}`);
        console.log(`Deployer Balance: ${ethers.utils.formatEther(await deployer.getBalance())} ETH`);
        console.log("=====================================================");

        console.log("\n=============== Contract Addresses ===============");
        console.log(`Uniswap V3 Factory: ${UNISWAP_V3.FACTORY}`);
        console.log(`Position Manager: ${UNISWAP_V3.POSITION_MANAGER}`);
        console.log(`Swap Router: ${UNISWAP_V3.SWAP_ROUTER}`);
        console.log(`USDC: ${TOKENS.USDC}`);
        console.log(`WETH: ${TOKENS.WETH}`);
        console.log(`Fee Tier: ${DEPLOY_SETTINGS.FEE_TIER} (0.3%)`);
        console.log("=================================================");

        console.log("\n=============== Deployment Settings ===============");
        console.log(`Gas Limit: ${DEPLOY_SETTINGS.GAS_LIMIT}`);
        console.log(`Gas Price: ${ethers.utils.formatUnits(DEPLOY_SETTINGS.GAS_PRICE, "gwei")} gwei`);

        const estimatedCost = DEPLOY_SETTINGS.GAS_LIMIT *
            parseFloat(ethers.utils.formatUnits(DEPLOY_SETTINGS.GAS_PRICE, "ether"));
        console.log(`Estimated Max Cost: ${estimatedCost.toFixed(6)} ETH`);
        console.log("=================================================");

        console.log("\nDeploying BaselineMinimal contract...");
        const BaselineMinimal = await hre.ethers.getContractFactory("BaselineMinimal");

        console.log("\nDeploying... (This may take a few minutes)");
        const baselineMinimal = await BaselineMinimal.deploy(
            UNISWAP_V3.FACTORY,
            UNISWAP_V3.POSITION_MANAGER,
            UNISWAP_V3.SWAP_ROUTER,
            TOKENS.USDC,
            TOKENS.WETH,
            DEPLOY_SETTINGS.FEE_TIER,
            {
                gasLimit: DEPLOY_SETTINGS.GAS_LIMIT,
                gasPrice: DEPLOY_SETTINGS.GAS_PRICE
            }
        );

        console.log("\nWaiting for deployment confirmation...");
        const receipt = await baselineMinimal.deployTransaction.wait(2);

        console.log("\n=============== Deployment Result ===============");
        console.log(`✅ Contract deployed successfully!`);
        console.log(`Contract Address: ${baselineMinimal.address}`);
        console.log(`Transaction Hash: ${receipt.transactionHash}`);
        console.log(`Block Number: ${receipt.blockNumber}`);
        console.log(`Gas Used: ${receipt.gasUsed.toString()}`);
        console.log(`Actual Cost: ${ethers.utils.formatEther(receipt.gasUsed.mul(receipt.effectiveGasPrice))} ETH`);
        console.log("================================================");

        // ذخیره اطلاعات در فایل .env
        updateEnvFile({
            BASELINE_MINIMAL_ADDRESS: baselineMinimal.address,
            UNISWAP_FACTORY: UNISWAP_V3.FACTORY,
            POSITION_MANAGER: UNISWAP_V3.POSITION_MANAGER,
            SWAP_ROUTER: UNISWAP_V3.SWAP_ROUTER,
            USDC_ADDRESS: TOKENS.USDC,
            WETH_ADDRESS: TOKENS.WETH
        });

        console.log("\n=============== Next Steps ===============");
        console.log("1. Verify contract on Etherscan:");
        console.log(`   npx hardhat verify --network sepolia \\
      ${baselineMinimal.address} \\
      "${UNISWAP_V3.FACTORY}" \\
      "${UNISWAP_V3.POSITION_MANAGER}" \\
      "${UNISWAP_V3.SWAP_ROUTER}" \\
      "${TOKENS.USDC}" \\
      "${TOKENS.WETH}" \\
      ${DEPLOY_SETTINGS.FEE_TIER}`);
        console.log("\n2. Fund the contract with initial liquidity");
        console.log("\n3. Call adjustLiquidityWithCurrentPrice() to initialize the position");
        console.log("=========================================");

    } catch (error) {
        console.error("\n❌ Deployment failed!");
        console.error("Error:", error.message);

        if (error.transaction) {
            console.log("\nTransaction Details:");
            console.log(`Hash: ${error.transaction.hash}`);
            console.log(`From: ${error.transaction.from}`);
            console.log(`To: ${error.transaction.to}`);
            console.log(`Gas Limit: ${error.transaction.gasLimit.toString()}`);
            console.log(`Gas Price: ${ethers.utils.formatUnits(error.transaction.gasPrice || 0, "gwei")} gwei`);
        }

        process.exit(1);
    }
}

function updateEnvFile(envVars) {
    const envPath = path.resolve(__dirname, '../.env');
    let envContent = fs.existsSync(envPath) ? fs.readFileSync(envPath, 'utf8') : '';

    // حذف مقادیر قدیمی اگر وجود داشته باشند
    Object.keys(envVars).forEach(key => {
        const regex = new RegExp(`^${key}=.*$`, 'gm');
        envContent = envContent.replace(regex, '');
    });

    // اضافه کردن مقادیر جدید
    envContent += '\n# ====== BaselineMinimal Deployment ======\n';
    Object.entries(envVars).forEach(([key, value]) => {
        envContent += `${key}="${value}"\n`;
    });

    fs.writeFileSync(envPath, envContent.trim());
    console.log("\nContract addresses saved to .env file");
}

main()
    .then(() => process.exit(0))
    .catch((error) => {
        console.error("Unhandled error:", error);
        process.exit(1);
    });