// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@uniswap/v3-core/contracts/interfaces/IUniswapV3Pool.sol";
import "@uniswap/v3-core/contracts/interfaces/IUniswapV3Factory.sol";

contract UniswapLiquidityManager is Ownable {
    // متغیرهای قرارداد
    IUniswapV3Factory public immutable factory;
    address public immutable token0;
    address public immutable token1;
    uint24 public immutable fee;

    struct LiquidityPosition {
        uint128 liquidity;
        int24 tickLower;
        int24 tickUpper;
        uint256 amount0;
        uint256 amount1;
    }

    struct PriceData {
        uint256 timestamp;
        uint256 actualPrice;
        uint256 predictedPrice;
        bool increasedLiquidity;
        uint256 liquidityBefore;
        uint256 liquidityAfter;
        uint256 gasUsed;
    }

    // رویدادها
    event PriceUpdated(uint256 actualPrice, uint256 predictedPrice);
    event LiquidityChanged(bool increased, uint256 amount);
    event DataRecorded(
        uint256 timestamp,
        uint256 actualPrice,
        uint256 predictedPrice,
        bool increasedLiquidity,
        uint256 liquidityBefore,
        uint256 liquidityAfter,
        uint256 gasUsed
    );

    // قیمت‌های فعلی و پیش‌بینی‌شده
    uint256 public currentPrice;
    uint256 public predictedPrice;
    uint256 public priceThreshold = 5; // حد تغییر 5 درصد

    // ذخیره تاریخچه قیمت‌ها و نقدینگی
    PriceData[] public priceDataHistory;

    constructor(
        address _factory,
        address _token0,
        address _token1,
        uint24 _fee,
        address _owner // Add owner address parameter
    ) Ownable(_owner) {
        // Pass owner address to Ownable constructor
        factory = IUniswapV3Factory(_factory);
        token0 = _token0;
        token1 = _token1;
        fee = _fee;
    }

    // دریافت قیمت لحظه‌ای از یونی‌سواپ
    function fetchUniswapPrice() public view returns (uint256) {
        address poolAddress = factory.getPool(token0, token1, fee);
        require(poolAddress != address(0), "Pool does not exist");

        IUniswapV3Pool pool = IUniswapV3Pool(poolAddress);
        (uint160 sqrtPriceX96, , , , , , ) = pool.slot0();

        uint256 price = (uint256(sqrtPriceX96) *
            uint256(sqrtPriceX96) *
            1e18) >> (96 * 2);
        return price;
    }

    // تنظیم قیمت پیش‌بینی‌شده توسط اسکریپت VPS
    function setPredictedPrice(uint256 _predictedPrice) external onlyOwner {
        predictedPrice = _predictedPrice;
        currentPrice = fetchUniswapPrice();
        emit PriceUpdated(currentPrice, predictedPrice);
    }

    // مدیریت نقدینگی بر اساس اختلاف قیمت
    function manageLiquidity() external onlyOwner {
        uint256 priceDiff;
        bool shouldIncrease;

        if (predictedPrice > currentPrice) {
            priceDiff = predictedPrice - currentPrice;
            shouldIncrease = true;
        } else {
            priceDiff = currentPrice - predictedPrice;
            shouldIncrease = false;
        }

        if ((priceDiff * 100) / currentPrice > priceThreshold) {
            uint256 liquidityBefore = getLiquidity();
            if (shouldIncrease) {
                increaseLiquidity();
            } else {
                decreaseLiquidity();
            }
            uint256 liquidityAfter = getLiquidity();

            recordData(shouldIncrease, liquidityBefore, liquidityAfter);
        }
    }

    // تابع افزایش نقدینگی
    function increaseLiquidity() internal {
        // کد افزایش نقدینگی در یونی‌سواپ V3
        emit LiquidityChanged(true, 0);
    }

    // تابع کاهش نقدینگی
    function decreaseLiquidity() internal {
        // کد کاهش نقدینگی در یونی‌سواپ V3
        emit LiquidityChanged(false, 0);
    }

    // دریافت مقدار کل نقدینگی
    function getLiquidity() public view returns (uint256) {
        address poolAddress = factory.getPool(token0, token1, fee);
        require(poolAddress != address(0), "Pool does not exist");

        IUniswapV3Pool pool = IUniswapV3Pool(poolAddress);
        return pool.liquidity();
    }

    // ثبت داده‌ها برای تحلیل
    function recordData(
        bool increasedLiquidity,
        uint256 before,
        uint256 liquidityAfterValue
    ) internal {
        uint256 gasBefore = gasleft();

        PriceData memory newData = PriceData({
            timestamp: block.timestamp,
            actualPrice: currentPrice,
            predictedPrice: predictedPrice,
            increasedLiquidity: increasedLiquidity,
            liquidityBefore: before,
            liquidityAfter: liquidityAfterValue,
            gasUsed: gasBefore - gasleft()
        });

        priceDataHistory.push(newData);
        emit DataRecorded(
            block.timestamp,
            currentPrice,
            predictedPrice,
            increasedLiquidity,
            before,
            liquidityAfterValue,
            gasBefore - gasleft()
        );
    }

    // مشاهده داده‌های ثبت‌شده
    function getPriceDataHistory() external view returns (PriceData[] memory) {
        return priceDataHistory;
    }
}
