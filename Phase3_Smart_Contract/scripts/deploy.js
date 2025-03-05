const hre = require("hardhat");

async function main() {
    // دریافت فکتوری قرارداد
    const SimpleStorage = await hre.ethers.getContractFactory("SimpleStorage");

    // دیپلوی قرارداد
    const simpleStorage = await SimpleStorage.deploy();

    // منتظر بمانید تا قرارداد دیپلوی شود
    await simpleStorage.waitForDeployment();

    // آدرس قرارداد دیپلوی‌شده را دریافت کنید
    const contractAddress = await simpleStorage.getAddress();

    console.log(`SimpleStorage deployed to: ${contractAddress}`);
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});