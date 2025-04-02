const hre = require("hardhat");
const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
    const [deployer] = await hre.ethers.getSigners();
    console.log("=========================================");
    console.log("Deploying contract with the account:", deployer.address);
    console.log("Account balance:", (await deployer.getBalance()).toString());
    console.log("=========================================");

    const PredictiveLiquidityManagerFinal = await hre.ethers.getContractFactory("PredictiveLiquidityManagerFinal");

    // آدرس‌های به‌روز شده برای شبکه سپولیا
    const FACTORY_ADDRESS = "0x1F98431c8aD98523631AE4a59f267346ea31F984";
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

    console.log("Starting deployment with higher gas settings...");

    try {
        const contract = await PredictiveLiquidityManagerFinal.deploy(
            FACTORY_ADDRESS,
            POSITION_MANAGER,
            SWAP_ROUTER,
            USDC,
            WETH,
            3000,
            WETH,
            deployer.address,
            {
                gasLimit: 8000000,  // افزایش به 8 میلیون
                maxFeePerGas: ethers.utils.parseUnits("100", "gwei"),  // افزایش به 100 gwei
                maxPriorityFeePerGas: ethers.utils.parseUnits("5", "gwei")  // افزایش به 5 gwei
            }
        );

        console.log("Waiting for deployment transaction...");
        console.log("Transaction hash:", contract.deployTransaction.hash);

        await contract.deployed();
        console.log("Contract deployed to:", contract.address);

        // ذخیره آدرس قرارداد در فایل
        updateEnvFile(contract.address);

        console.log("=========================================");
        console.log("Next steps:");
        console.log("1. Visit https://sepolia.etherscan.io/address/" + contract.address);
        console.log("2. Verify contract on Etherscan:");
        console.log(`   npx hardhat verify --network sepolia ${contract.address} ${FACTORY_ADDRESS} ${POSITION_MANAGER} ${SWAP_ROUTER} ${USDC} ${WETH} 3000 ${WETH} ${deployer.address}`);
        console.log("3. Fund contract with USDC and WETH");
        console.log("=========================================");

    } catch (error) {
        console.error("Deployment failed with error:", error);
        throw error;
    }
}

// تابع به‌روزرسانی فایل .env
function updateEnvFile(contractAddress) {
    try {
        const envPath = path.resolve(__dirname, '../.env');
        let envContent = fs.readFileSync(envPath, 'utf8');

        if (envContent.includes('CONTRACT_ADDRESS=')) {
            // جایگزینی آدرس قرارداد موجود
            envContent = envContent.replace(
                /CONTRACT_ADDRESS=(.*)/,
                `CONTRACT_ADDRESS="${contractAddress}"`
            );
        } else {
            // اضافه کردن آدرس قرارداد جدید
            envContent += `\n# Deployed contract address\nCONTRACT_ADDRESS="${contractAddress}"\n`;
        }

        fs.writeFileSync(envPath, envContent);
        console.log(`Contract address saved to .env file: ${contractAddress}`);
    } catch (error) {
        console.warn("Could not update .env file:", error.message);
    }
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
