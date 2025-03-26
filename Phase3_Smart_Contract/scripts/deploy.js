const { ethers } = require("hardhat"); // این را اصلاح کنید (hardhat را فراخوانی کنید)

async function main() {
    console.log("🏗️ Starting deployment...");

    // 1. دریافت اطلاعات حساب
    const [deployer] = await ethers.getSigners();  // 🔴 اینجا خطا می‌داد، حالا درست شد
    console.log("👤 Deployer address:", deployer.address);

    // اصلاح متد دریافت بالانس
    const balance = await deployer.provider.getBalance(deployer.address);
    console.log("💰 Balance:", ethers.formatEther(balance), "ETH");
    console.log("🔍 Checking ethers.utils:", ethers.utils);

    // 2. پارامترهای استقرار
    const factoryAddress = ethers.getAddress("0x1F98431c8aD98523631AE4a59f267346ea31F984");
    const token0Address = ethers.getAddress("0x7b79995e5f793A07Bc00c21412e50Ecae098E7f9");

    // ✅ آدرس مشکل‌دار را کوچک کنید تا `checksum` تصحیح شود
    const token1Address = ethers.getAddress("0xaa8e23fb1079ea71e0a56f48a2aa51851d8433d0");

    const fee = 3000;

    console.log("\n⚙️ Deployment Parameters:");
    console.log("Factory:", factoryAddress);
    console.log("Token0:", token0Address);
    console.log("Token1:", token1Address);
    console.log("Fee Tier:", fee);

    // 3. استقرار قرارداد
    console.log("\n🚀 Deploying Contract...");
    const Contract = await ethers.getContractFactory("UniswapLiquidityManager"); // 🔴 اینجا خطا می‌داد، حالا اصلاح شد
    const contract = await Contract.deploy(
        factoryAddress,
        token0Address,
        token1Address,
        fee,
        deployer.address
    );

    console.log("⏳ Waiting for deployment confirmation...");
    await contract.waitForDeployment();

    // 4. نتایج
    console.log("\n✅ Success! Contract deployed to:", await contract.getAddress());
    console.log("📄 Transaction Hash:", contract.deploymentTransaction().hash);
}

main()
    .then(() => process.exit(0))
    .catch(error => {
        console.error("🔥 Deployment Failed:", error);
        process.exit(1);
    });
