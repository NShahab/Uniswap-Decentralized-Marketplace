const hre = require("hardhat");
const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
    try {
        const [deployer] = await hre.ethers.getSigners();
        console.log("=========================================");
        console.log("Deploying BaselineLiquidityManager with the account:", deployer.address);
        console.log("Account balance:", (await deployer.getBalance()).toString());
        console.log("=========================================");

        // آدرس‌های Uniswap V3 برای شبکه سپولیا
        const FACTORY_ADDRESS = "0x0227628f3F023bb0B980b67D528571c95c6DaC1c";
        const POSITION_MANAGER = "0x1238536071E1c677A632429e3655c799b22cDA52";
        const USDC = "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238";
        const WETH = "0x7b79995e5f793A07Bc00c21412e50Ecae098E7f9";

        console.log("Using the following addresses:");
        console.log("- Factory:", FACTORY_ADDRESS);
        console.log("- Position Manager:", POSITION_MANAGER);
        console.log("- USDC:", USDC);
        console.log("- WETH:", WETH);
        console.log("- Fee:", 3000, "(0.3%)");
        console.log("=========================================");

        // تنظیمات بهینه برای دیپلوی
        const deploymentOptions = {
            gasLimit: 2000000,
            gasPrice: ethers.utils.parseUnits("20", "gwei")
        };

        console.log("Using deployment options:");
        console.log("- Gas Limit:", deploymentOptions.gasLimit.toString());
        console.log("- Gas Price:", ethers.utils.formatUnits(deploymentOptions.gasPrice, "gwei"), "gwei");
        console.log("=========================================");

        console.log("Deploying BaselineLiquidityManager contract...");
        const BaselineLiquidityManager = await hre.ethers.getContractFactory("BaselineLiquidityManager");

        console.log("Creating deployment transaction...");
        const baselineManager = await BaselineLiquidityManager.deploy(
            FACTORY_ADDRESS,
            POSITION_MANAGER,
            USDC,
            WETH,
            3000,
            WETH,
            deployer.address,
            deploymentOptions
        );

        console.log("Waiting for BaselineLiquidityManager deployment transaction to be mined...");
        console.log("Transaction hash:", baselineManager.deployTransaction.hash);
        await baselineManager.deployed();
        console.log("✅ BaselineLiquidityManager deployed to:", baselineManager.address);

        // ذخیره آدرس‌های قراردادها در فایل .env
        updateEnvFile({
            BASELINE_MANAGER_ADDRESS: baselineManager.address
        });

        console.log("=========================================");
        console.log("Deployment completed successfully!");
        console.log("BaselineLiquidityManager:", baselineManager.address);
        console.log("=========================================");
        console.log("Next steps:");
        console.log("1. Verify contract on Etherscan:");
        console.log(`   npx hardhat verify --network sepolia ${baselineManager.address} ${FACTORY_ADDRESS} ${POSITION_MANAGER} ${USDC} ${WETH} 3000 ${WETH} ${deployer.address}`);
        console.log("2. Fund contract with USDC and WETH");
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