const { expect } = require("chai");

describe("SimpleStorage", function () {
    let simpleStorage;

    beforeEach(async function () {
        const SimpleStorage = await ethers.getContractFactory("SimpleStorage");
        simpleStorage = await SimpleStorage.deploy(); // این خط قرارداد را دیپلوی می‌کند
    });

    it("Should store and retrieve a value correctly", async function () {
        // مقدار 42 را ذخیره کنید
        await simpleStorage.set(42);

        // مقدار ذخیره‌شده را بازیابی کنید
        const value = await simpleStorage.get();

        // بررسی کنید که مقدار بازیابی‌شده برابر با 42 است
        expect(value).to.equal(42);
    });
});