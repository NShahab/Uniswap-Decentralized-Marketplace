const hre = require("hardhat");
const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
    try {
        const [deployer] = await hre.ethers.getSigners();
        console.log("=========================================");
        console.log("Deploying contracts with the account:", deployer.address);
        console.log("Account balance:", (await deployer.getBalance()).toString());
        console.log("=========================================");

        // آدرس‌های Uniswap V3 برای شبکه سپولیا
        const FACTORY_ADDRESS = "0x0227628f3F023bb0B980b67D528571c95c6DaC1c";
        const POSITION_MANAGER = "0x1238536071E1c677A632429e3655c799b22cDA52";
        const SWAP_ROUTER = "0x3bFA4769FB09eefC5a80d6E87c3B9C650f7Ae48E";
        const WETH = "0x7b79995e5f793A07Bc00c21412e50Ecae098E7f9";
        const USDC = "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238";

        console.log("Using the following addresses:");
        console.log("- Factory:", FACTORY_ADDRESS);
        console.log("- Position Manager:", POSITION_MANAGER);
        console.log("- Swap Router:", SWAP_ROUTER);
        console.log("- WETH:", WETH);
        console.log("- USDC:", USDC);
        console.log("- Fee:", 3000, "(0.3%)");
        console.log("=========================================");

        // تنظیمات بهینه برای دیپلوی
        const deploymentOptions = {
            gasLimit: 3000000, // کاهش به 3 میلیون
            gasPrice: ethers.utils.parseUnits("30", "gwei") // استفاده از gasPrice به جای maxFeePerGas
        };

        console.log("Using deployment options:");
        console.log("- Gas Limit:", deploymentOptions.gasLimit.toString());
        console.log("- Gas Price:", ethers.utils.formatUnits(deploymentOptions.gasPrice, "gwei"), "gwei");
        console.log("=========================================");

        console.log("1. Deploying TokenOperationsManager contract...");
        const TokenOperationsManager = await hre.ethers.getContractFactory("TokenOperationsManager");

        console.log("Creating deployment transaction...");
        const tokenManager = await TokenOperationsManager.deploy(
            SWAP_ROUTER,
            WETH,
            deployer.address,
            deploymentOptions
        );

        console.log("Waiting for TokenOperationsManager deployment transaction to be mined...");
        console.log("Transaction hash:", tokenManager.deployTransaction.hash);
        await tokenManager.deployed();
        console.log("✅ TokenOperationsManager deployed to:", tokenManager.address);

        console.log("=========================================");
        console.log("2. Deploying PredictiveLiquidityManager contract...");
        const PredictiveLiquidityManager = await hre.ethers.getContractFactory("PredictiveLiquidityManager");

        console.log("Creating deployment transaction...");
        const predictiveManager = await PredictiveLiquidityManager.deploy(
            FACTORY_ADDRESS,
            POSITION_MANAGER,
            USDC,
            WETH,
            3000,
            WETH,
            deployer.address,
            deploymentOptions
        );

        console.log("Waiting for PredictiveLiquidityManager deployment transaction to be mined...");
        console.log("Transaction hash:", predictiveManager.deployTransaction.hash);
        await predictiveManager.deployed();
        console.log("✅ PredictiveLiquidityManager deployed to:", predictiveManager.address);

        // ذخیره آدرس‌های قراردادها در فایل .env
        updateEnvFile({
            TOKEN_MANAGER_ADDRESS: tokenManager.address,
            PREDICTIVE_MANAGER_ADDRESS: predictiveManager.address
        });

        console.log("=========================================");
        console.log("Deployment completed successfully!");
        console.log("TokenOperationsManager:", tokenManager.address);
        console.log("PredictiveLiquidityManager:", predictiveManager.address);
        console.log("=========================================");
        console.log("Next steps:");
        console.log("1. Verify contracts on Etherscan:");
        console.log(`   npx hardhat verify --network sepolia ${tokenManager.address} ${SWAP_ROUTER} ${WETH} ${deployer.address}`);
        console.log(`   npx hardhat verify --network sepolia ${predictiveManager.address} ${FACTORY_ADDRESS} ${POSITION_MANAGER} ${USDC} ${WETH} 3000 ${WETH} ${deployer.address}`);
        console.log("2. Fund both contracts with USDC and WETH");
        console.log("=========================================");
    } catch (error) {
        console.error("❌ Deployment failed with error:", error);

        // نمایش جزئیات بیشتر در صورت وجود
        if (error.reason) {
            console.error("Error reason:", error.reason);
        }

        if (error.code) {
            console.error("Error code:", error.code);
        }

        if (error.transaction) {
            console.error("Failed transaction details:", {
                hash: error.transaction.hash,
                from: error.transaction.from,
                to: error.transaction.to,
                gasLimit: error.transaction.gasLimit.toString(),
                gasPrice: error.transaction.gasPrice
                    ? ethers.utils.formatUnits(error.transaction.gasPrice, "gwei") + " gwei"
                    : "unknown"
            });
        }

        throw error;
    }
}

// تابع به‌روزرسانی فایل .env
function updateEnvFile(addresses) {
    try {
        const envPath = path.resolve(__dirname, '../.env');
        let envContent = '';

        try {
            envContent = fs.readFileSync(envPath, 'utf8');
        } catch (error) {
            console.log("Creating new .env file");
            envContent = '';
        }

        // به‌روزرسانی یا اضافه کردن آدرس‌های قراردادها
        for (const [key, value] of Object.entries(addresses)) {
            if (envContent.includes(`${key}=`)) {
                envContent = envContent.replace(
                    new RegExp(`${key}=.*`),
                    `${key}="${value}"`
                );
            } else {
                envContent += `\n${key}="${value}"\n`;
            }
        }

        fs.writeFileSync(envPath, envContent);
        console.log(`Contract addresses saved to .env file`);
    } catch (error) {
        console.warn("Could not update .env file:", error.message);
    }
}

main().catch((error) => {
    console.error("Unhandled error:", error);
    process.exit(1);
}); 