// SPDX-License-Identifier: MIT
pragma solidity ^0.7.6;
pragma abicoder v2;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/SafeERC20.sol";
import "@uniswap/v3-core/contracts/interfaces/IUniswapV3Pool.sol";
import "@uniswap/v3-core/contracts/interfaces/IUniswapV3Factory.sol";
import "@uniswap/v3-periphery/contracts/interfaces/INonfungiblePositionManager.sol";
import "@uniswap/v3-periphery/contracts/interfaces/ISwapRouter.sol";
import "@uniswap/v3-periphery/contracts/libraries/TransferHelper.sol";

interface IWETH {
    function deposit() external payable;
    function withdraw(uint256) external;
}

/**
 * @title BaselineMinimal
 * @notice نسخه حداقلی قرارداد مدیریت نقدینگی بیس‌لاین
 */
contract BaselineMinimal is Ownable {
    using SafeERC20 for IERC20;

    // --- متغیرهای وضعیت اصلی ---
    IUniswapV3Factory public immutable factory;
    INonfungiblePositionManager public immutable positionManager;
    ISwapRouter public immutable swapRouter;
    address public immutable token0;
    address public immutable token1;
    uint24 public immutable fee;
    int24 public immutable tickSpacing;

    // --- متغیرها برای نگهداری موقعیت ---
    uint256 public currentTokenId;
    bool public hasPosition;
    int24 public lowerTick;
    int24 public upperTick;

    // --- رویدادها ---
    event PositionChanged(bool hasPosition, int24 lowerTick, int24 upperTick);
    event BaselineAdjustmentMetrics(
        uint256 timestamp,
        uint256 currentPrice,
        int24 currentTick,
        int24 finalTickLower,
        int24 finalTickUpper,
        bool adjusted
    );
    event TokensSwapped(uint256 amountIn, uint256 amountOut);

    // --- سازنده ---
    constructor(
        address _factory,
        address _positionManager,
        address _swapRouter,
        address _token0,
        address _token1,
        uint24 _fee
    ) {
        require(_factory != address(0), "Invalid factory address");
        require(_positionManager != address(0), "Invalid position manager");
        require(_swapRouter != address(0), "Invalid swap router");
        require(_token0 != address(0), "Invalid token0");
        require(_token1 != address(0), "Invalid token1");
        require(_fee > 0, "Invalid fee");

        factory = IUniswapV3Factory(_factory);
        positionManager = INonfungiblePositionManager(_positionManager);
        swapRouter = ISwapRouter(_swapRouter);
        token0 = _token0;
        token1 = _token1;
        fee = _fee;

        // تنظیم tickSpacing با استفاده از پول
        address poolAddress = IUniswapV3Factory(_factory).getPool(
            _token0,
            _token1,
            _fee
        );
        require(poolAddress != address(0), "Pool does not exist");
        tickSpacing = IUniswapV3Pool(poolAddress).tickSpacing();

        // تنظیم تأییدیه‌های توکن
        IERC20(_token0).approve(address(_positionManager), type(uint256).max);
        IERC20(_token1).approve(address(_positionManager), type(uint256).max);
        IERC20(_token0).approve(address(_swapRouter), type(uint256).max);
        IERC20(_token1).approve(address(_swapRouter), type(uint256).max);
    }

    // --- تابع دریافت ETH ---
    receive() external payable {
        // تبدیل ETH به WETH
        IWETH(token1).deposit{value: msg.value}();

        // تبدیل نیمی از WETH به USDC
        uint256 halfAmount = msg.value / 2;
        _swapExactInputSingle(token1, token0, halfAmount);

        // تنظیم نقدینگی با توکن‌های جدید
        adjustLiquidityWithCurrentPrice();
    }

    // --- تابع سواپ ---
    function _swapExactInputSingle(
        address tokenIn,
        address tokenOut,
        uint256 amountIn
    ) internal returns (uint256 amountOut) {
        ISwapRouter.ExactInputSingleParams memory params = ISwapRouter
            .ExactInputSingleParams({
                tokenIn: tokenIn,
                tokenOut: tokenOut,
                fee: fee,
                recipient: address(this),
                deadline: block.timestamp,
                amountIn: amountIn,
                amountOutMinimum: 0,
                sqrtPriceLimitX96: 0
            });

        amountOut = swapRouter.exactInputSingle(params);
        emit TokensSwapped(amountIn, amountOut);
    }

    // --- تابع اصلی تنظیم نقدینگی ---
    function adjustLiquidityWithCurrentPrice() public {
        // 1. دریافت اطلاعات قیمت و tick فعلی
        address pool = factory.getPool(token0, token1, fee);
        require(pool != address(0), "Pool not found");

        uint160 sqrtPriceX96;
        int24 currentTick;
        (sqrtPriceX96, currentTick, , , , , ) = IUniswapV3Pool(pool).slot0();

        // 2. محاسبه محدوده tick جدید
        int24 width = tickSpacing * 4;
        int24 newLowerTick = ((currentTick - width / 2) / tickSpacing) *
            tickSpacing;
        int24 newUpperTick = ((currentTick + width / 2) / tickSpacing) *
            tickSpacing;

        // 3. حذف موقعیت موجود
        if (hasPosition) {
            _removePosition();
        }

        // 4. ایجاد موقعیت جدید با موجودی توکن‌ها
        _createPosition(newLowerTick, newUpperTick);

        // 5. انتشار رویداد
        emit BaselineAdjustmentMetrics(
            block.timestamp,
            _sqrtPriceX96ToPrice(sqrtPriceX96),
            currentTick,
            newLowerTick,
            newUpperTick,
            true
        );
    }

    // --- حذف موقعیت ---
    function _removePosition() internal {
        require(hasPosition, "No position to remove");
        require(currentTokenId > 0, "Invalid token ID");

        // حذف نقدینگی
        try
            positionManager.decreaseLiquidity(
                INonfungiblePositionManager.DecreaseLiquidityParams({
                    tokenId: currentTokenId,
                    liquidity: type(uint128).max,
                    amount0Min: 0,
                    amount1Min: 0,
                    deadline: block.timestamp
                })
            )
        {} catch {}

        // جمع‌آوری توکن‌ها
        try
            positionManager.collect(
                INonfungiblePositionManager.CollectParams({
                    tokenId: currentTokenId,
                    recipient: address(this),
                    amount0Max: type(uint128).max,
                    amount1Max: type(uint128).max
                })
            )
        {} catch {}

        // سوزاندن NFT
        try positionManager.burn(currentTokenId) {} catch {}

        // بازنشانی وضعیت
        hasPosition = false;
        currentTokenId = 0;

        emit PositionChanged(false, 0, 0);
    }

    // --- ایجاد موقعیت ---
    function _createPosition(int24 _lowerTick, int24 _upperTick) internal {
        require(_lowerTick < _upperTick, "Invalid tick range");

        uint256 amount0 = IERC20(token0).balanceOf(address(this));
        uint256 amount1 = IERC20(token1).balanceOf(address(this));

        if (amount0 == 0 && amount1 == 0) {
            return;
        }

        try
            positionManager.mint(
                INonfungiblePositionManager.MintParams({
                    token0: token0,
                    token1: token1,
                    fee: fee,
                    tickLower: _lowerTick,
                    tickUpper: _upperTick,
                    amount0Desired: amount0,
                    amount1Desired: amount1,
                    amount0Min: 0,
                    amount1Min: 0,
                    recipient: address(this),
                    deadline: block.timestamp
                })
            )
        returns (uint256 tokenId, uint128, uint256, uint256) {
            if (tokenId > 0) {
                currentTokenId = tokenId;
                hasPosition = true;
                lowerTick = _lowerTick;
                upperTick = _upperTick;

                emit PositionChanged(true, _lowerTick, _upperTick);
            }
        } catch {}
    }

    // --- تابع کمکی برای محاسبه قیمت ---
    function _sqrtPriceX96ToPrice(
        uint160 sqrtPriceX96
    ) internal pure returns (uint256) {
        require(sqrtPriceX96 > 0, "Invalid sqrt price");
        uint256 priceX192 = uint256(sqrtPriceX96) * uint256(sqrtPriceX96);
        return priceX192 >> 96;
    }

    // --- برداشت اضطراری توکن‌ها ---
    function rescueTokens(address token, address to) external onlyOwner {
        require(token != address(0), "Invalid token");
        require(to != address(0), "Invalid recipient");

        uint256 amount = IERC20(token).balanceOf(address(this));
        if (amount > 0) {
            IERC20(token).safeTransfer(to, amount);
        }
    }

    // --- تابع برداشت اضطراری ETH ---
    function rescueETH() external onlyOwner {
        uint256 balance = address(this).balance;
        if (balance > 0) {
            payable(owner()).transfer(balance);
        }
    }

    // --- تابع برداشت اضطراری WETH ---
    function rescueWETH(uint256 amount) external onlyOwner {
        IWETH(token1).withdraw(amount);
        payable(owner()).transfer(amount);
    }
}
