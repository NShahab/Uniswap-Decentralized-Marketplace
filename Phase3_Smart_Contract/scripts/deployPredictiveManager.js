const hre = require("hardhat");
const fs = require('fs');
const path = require('path');

async function main() {
    console.log("Starting deployment process on the forked network...");

    // --- Mainnet Addresses ---
    // Ensure these are correct for the Mainnet
    const UNISWAP_V3_FACTORY_MAINNET = "0x1F98431c8aD98523631AE4a59f267346ea31F984";
    const POSITION_MANAGER_MAINNET = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88";
    const WETH_MAINNET = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2";
    const USDC_MAINNET = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"; // Mainnet USDC (6 decimals)
    const POOL_FEE = 500; // 0.05% fee tier for WETH/USDC - Make sure this pool exists!

    const [deployer] = await hre.ethers.getSigners();
    console.log("Deploying contracts with the account:", deployer.address);
    console.log("Account balance:", (await deployer.getBalance()).toString());

    // --- Verify Pool Existence ---
    console.log(`Checking if the mainnet pool exists (WETH/USDC Fee: ${POOL_FEE})...`);
    const factory = await hre.ethers.getContractAt("IUniswapV3Factory", UNISWAP_V3_FACTORY_MAINNET);
    // Ensure correct order for getPool based on addresses (token0 < token1)
    const token0ForPool = USDC_MAINNET < WETH_MAINNET ? USDC_MAINNET : WETH_MAINNET;
    const token1ForPool = USDC_MAINNET < WETH_MAINNET ? WETH_MAINNET : USDC_MAINNET;
    const poolAddress = await factory.getPool(token0ForPool, token1ForPool, POOL_FEE);

    if (poolAddress === "0x0000000000000000000000000000000000000000") {
        console.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
        console.error("ERROR: The specified pool does not exist on the Mainnet fork!");
        console.error(`Checked for pool: ${token0ForPool} / ${token1ForPool} Fee: ${POOL_FEE}`);
        console.error("Please verify the token addresses and the POOL_FEE variable.");
        console.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
        process.exit(1); // Exit if pool doesn't exist
    } else {
        console.log(`Pool exists on Mainnet Fork at: ${poolAddress}`);
    }

    // --- Deploy PredictiveLiquidityManager ---
    console.log("\nDeploying PredictiveLiquidityManager...");
    const PredictiveLiquidityManager = await hre.ethers.getContractFactory("PredictiveLiquidityManager");

    // Determine token0/token1 for the constructor based on address order
    const constructorToken0 = USDC_MAINNET < WETH_MAINNET ? USDC_MAINNET : WETH_MAINNET;
    const constructorToken1 = USDC_MAINNET < WETH_MAINNET ? WETH_MAINNET : USDC_MAINNET;

    console.log("Deploying with parameters:");
    console.log("  Factory:", UNISWAP_V3_FACTORY_MAINNET);
    console.log("  Position Manager:", POSITION_MANAGER_MAINNET);
    console.log("  Token0 (for constructor):", constructorToken0); // e.g., USDC
    console.log("  Token1 (for constructor):", constructorToken1); // e.g., WETH
    console.log("  Pool Fee:", POOL_FEE);
    console.log("  Initial Owner:", deployer.address); // Set deployer as owner

    const predictiveManager = await PredictiveLiquidityManager.deploy(
        UNISWAP_V3_FACTORY_MAINNET,
        POSITION_MANAGER_MAINNET,
        constructorToken0,    // _token0 (must be the one with the lower address)
        constructorToken1,    // _token1 (must be the one with the higher address)
        POOL_FEE,
        deployer.address      // _initialOwner (set deployer as owner)
    );
    await predictiveManager.deployed();

    console.log("PredictiveLiquidityManager deployed to:", predictiveManager.address);
    console.log("Transaction hash:", predictiveManager.deployTransaction.hash);

    // --- Save Deployed Address ---
    const addresses = {
        predictiveManager: predictiveManager.address,
        // Add other deployed addresses if needed
    };
    const outputPath = path.join(__dirname, '..', 'deployed_addresses.json'); // Path to the file in the project root

    try {
        // --- Delete existing file first (optional step) ---
        try {
            fs.unlinkSync(outputPath); // Attempt to delete the file if it exists
            console.log(`Deleted previous address file: ${outputPath}`);
        } catch (deleteErr) {
            if (deleteErr.code !== 'ENOENT') { // Ignore error if file simply doesn't exist
                console.error("Warning: Error deleting previous address file:", deleteErr);
                // Decide if you want to stop or continue if deletion fails for other reasons
            } else {
                console.log("No previous address file to delete.");
            }
        }

        // --- Write the new file ---
        fs.writeFileSync(outputPath, JSON.stringify(addresses, null, 2));
        console.log(`Deployed addresses saved to ${outputPath}`);

    } catch (err) {
        console.error("FATAL ERROR: Could not save deployed addresses:", err);
        // Handle error appropriately, maybe exit
        process.exit(1);
    }


    // Wait for 1 block confirmation (usually enough on local fork)
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