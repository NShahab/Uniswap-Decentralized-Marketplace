const hre = require("hardhat");
const fs = require('fs');
const path = require('path');

async function main() {
    console.log("Starting deployment process on the forked network...");

    // --- Mainnet Addresses ---
    const UNISWAP_V3_FACTORY_MAINNET = "0x1F98431c8aD98523631AE4a59f267346ea31F984";
    const POSITION_MANAGER_MAINNET = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88";
    const WETH_MAINNET = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2";
    const USDC_MAINNET = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48";
    const POOL_FEE = 500; // 0.05% fee tier (500)

    const [deployer] = await hre.ethers.getSigners();
    console.log("Deploying contracts with the account:", deployer.address);
    console.log("Account balance:", (await deployer.getBalance()).toString());

    // --- Verify Pool Existence ---
    console.log("Checking if the mainnet pool exists (WETH/USDC 0.05%)...");
    const factory = await hre.ethers.getContractAt("IUniswapV3Factory", UNISWAP_V3_FACTORY_MAINNET);
    const token0ForPool = USDC_MAINNET < WETH_MAINNET ? USDC_MAINNET : WETH_MAINNET;
    const token1ForPool = USDC_MAINNET < WETH_MAINNET ? WETH_MAINNET : USDC_MAINNET;
    const poolAddress = await factory.getPool(token0ForPool, token1ForPool, POOL_FEE);

    if (poolAddress === "0x0000000000000000000000000000000000000000") {
        console.error("ERROR: The specified pool does not exist on Mainnet Fork!");
        console.error(`Checked for pool: ${token0ForPool}/${token1ForPool} fee ${POOL_FEE}`);
        process.exit(1);
    } else {
        console.log("Pool exists on Mainnet Fork at:", poolAddress);
    }

    // --- Deploy PredictiveLiquidityManager ---
    console.log("\nDeploying PredictiveLiquidityManager...");
    const PredictiveLiquidityManager = await hre.ethers.getContractFactory("PredictiveLiquidityManager");

    const constructorToken0 = USDC_MAINNET < WETH_MAINNET ? USDC_MAINNET : WETH_MAINNET;
    const constructorToken1 = USDC_MAINNET < WETH_MAINNET ? WETH_MAINNET : USDC_MAINNET;

    console.log("Deploying with parameters:");
    console.log("  Factory:", UNISWAP_V3_FACTORY_MAINNET);
    console.log("  Position Manager:", POSITION_MANAGER_MAINNET);
    console.log("  Token0 (for constructor):", constructorToken0);
    console.log("  Token1 (for constructor):", constructorToken1);
    console.log("  Pool Fee:", POOL_FEE);
    console.log("  Initial Owner:", deployer.address);

    const predictiveManager = await PredictiveLiquidityManager.deploy(
        UNISWAP_V3_FACTORY_MAINNET,
        POSITION_MANAGER_MAINNET,
        constructorToken0,
        constructorToken1,
        POOL_FEE,
        deployer.address
    );
    await predictiveManager.deployed();

    console.log("PredictiveLiquidityManager deployed to:", predictiveManager.address);
    console.log("Transaction hash:", predictiveManager.deployTransaction.hash);

    // --- Save Deployed Address ---
    const addresses = {
        predictiveManager: predictiveManager.address,
    };
    const outputPath = path.join(__dirname, '..', 'deployed_addresses.json');
    try {
        fs.writeFileSync(outputPath, JSON.stringify(addresses, null, 2));
        console.log(`Deployed addresses saved to ${outputPath}`);
    } catch (err) {
        console.error("Error saving deployed addresses:", err);
    }

    // Wait for 1 block confirmation
    console.log("Waiting for 1 block confirmation...");
    await predictiveManager.deployTransaction.wait(1);
    console.log("Deployment confirmed on the fork!");
}

main()
    .then(() => process.exit(0))
    .catch((error) => {
        console.error("Deployment script failed:", error);
        process.exit(1);
    });