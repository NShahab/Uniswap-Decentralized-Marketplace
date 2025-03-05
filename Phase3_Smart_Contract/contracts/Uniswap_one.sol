// SPDX-License-Identifier: MIT
pragma solidity ^0.8.17;

import "@uniswap/v3-periphery/contracts/interfaces/ISwapRouter.sol";
import "@chainlink/contracts/src/v0.8/interfaces/AggregatorV3Interface.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract LSTMLiquidityManager {
    ISwapRouter public immutable swapRouter;
    address public immutable tokenA;
    address public immutable tokenB;
    AggregatorV3Interface internal priceFeed; // اتصال به مدل LSTM از طریق Chainlink

    constructor(
        address _swapRouter,
        address _tokenA,
        address _tokenB,
        address _priceFeed
    ) {
        swapRouter = ISwapRouter(_swapRouter);
        tokenA = _tokenA;
        tokenB = _tokenB;
        priceFeed = AggregatorV3Interface(_priceFeed);
    }

    // تابع دریافت قیمت پیش‌بینی شده از LSTM
    function getPredictedPrice() public view returns (int) {
        (, int price, , , ) = priceFeed.latestRoundData();
        return price;
    }

    // تابع سواپ توکن در یونی‌سواپ با استفاده از قیمت پیش‌بینی‌شده
    function swapTokens(uint256 amountIn) external returns (uint256 amountOut) {
        require(amountIn > 0, "Amount must be greater than zero");

        IERC20(tokenA).transferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenA).approve(address(swapRouter), amountIn);

        ISwapRouter.ExactInputSingleParams memory params = ISwapRouter
            .ExactInputSingleParams({
                tokenIn: tokenA,
                tokenOut: tokenB,
                fee: 3000,
                recipient: msg.sender,
                deadline: block.timestamp + 15,
                amountIn: amountIn,
                amountOutMinimum: uint256(getPredictedPrice()), // مقدار حداقل خروجی بر اساس پیش‌بینی
                sqrtPriceLimitX96: 0
            });

        amountOut = swapRouter.exactInputSingle(params);
    }
}
