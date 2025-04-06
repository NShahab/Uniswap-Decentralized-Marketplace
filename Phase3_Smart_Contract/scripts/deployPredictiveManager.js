const hre = require("hardhat");

async function main() {
    console.log("Starting deployment process...");

    // Addresses on Sepolia
    const UNISWAP_V3_FACTORY = "0x0227628f3F023bb0B980b67D528571c95c6DaC1c";
    const POSITION_MANAGER = "0x1238536071E1c677A632429e3655c799b22cDA52";
    const WETH = "0x7b79995e5f793A07Bc00c21412e50Ecae098E7f9";
    const USDC = "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238";
    const POOL_FEE = 3000; // 0.3%

    console.log("Creating Uniswap V3 Pool...");

    // Get the Factory contract
    const factory = await hre.ethers.getContractAt("IUniswapV3Factory", UNISWAP_V3_FACTORY);

    // Check if pool exists
    let poolAddress = await factory.getPool(USDC, WETH, POOL_FEE);

    if (poolAddress === "0x0000000000000000000000000000000000000000") {
        console.log("Pool does not exist. Creating new pool...");
        // Create pool
        await factory.createPool(USDC, WETH, POOL_FEE);

        // Get the new pool address
        poolAddress = await factory.getPool(USDC, WETH, POOL_FEE);
        console.log("Pool created at:", poolAddress);

        // Initialize pool with a price
        const pool = await hre.ethers.getContractAt("IUniswapV3Pool", poolAddress);
        const sqrtPriceX96 = "792281625142643375935439503360"; // Example initial price
        await pool.initialize(sqrtPriceX96);
        console.log("Pool initialized with initial price");
    } else {
        console.log("Pool already exists at:", poolAddress);
    }

    console.log("\nDeploying PredictiveLiquidityManager...");

    // Get the contract factory
    const PredictiveLiquidityManager = await hre.ethers.getContractFactory("PredictiveLiquidityManager");

    console.log("Deploying with parameters:");
    console.log("Uniswap V3 Factory:", UNISWAP_V3_FACTORY);
    console.log("Position Manager:", POSITION_MANAGER);
    console.log("USDC:", USDC);
    console.log("WETH:", WETH);
    console.log("Pool Fee:", POOL_FEE);

    // Deploy the contract
    const predictiveManager = await PredictiveLiquidityManager.deploy(
        UNISWAP_V3_FACTORY,    // _factory
        POSITION_MANAGER,       // _positionManager
        USDC,                  // _token0 (USDC)
        WETH,                  // _token1 (WETH)
        POOL_FEE,             // _fee
        WETH,                 // _weth9
        "0x0000000000000000000000000000000000000000"  // _initialOwner (will be msg.sender)
    );

    await predictiveManager.deployed();

    console.log("PredictiveLiquidityManager deployed to:", predictiveManager.address);
    console.log("Transaction hash:", predictiveManager.deployTransaction.hash);

    // Wait for 5 block confirmations
    console.log("Waiting for 5 block confirmations...");
    await predictiveManager.deployTransaction.wait(5);
    console.log("Deployment confirmed!");

    // Verify the contract on Etherscan
    console.log("Verifying contract on Etherscan...");
    try {
        await hre.run("verify:verify", {
            address: predictiveManager.address,
            constructorArguments: [
                UNISWAP_V3_FACTORY,
                POSITION_MANAGER,
                USDC,
                WETH,
                POOL_FEE,
                WETH,
                "0x0000000000000000000000000000000000000000"
            ],
        });
        console.log("Contract verified successfully!");
    } catch (error) {
        console.error("Error verifying contract:", error);
    }
}

main()
    .then(() => process.exit(0))
    .catch((error) => {
        console.error(error);
        process.exit(1);
    }); 