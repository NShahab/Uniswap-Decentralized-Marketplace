// SPDX-License-Identifier: MIT
pragma solidity ^0.7.6;
pragma abicoder v2; // برای پشتیبانی از ساختارها در پارامترها

// OpenZeppelin ~3.4.0 Imports
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/SafeERC20.sol";
import "@openzeppelin/contracts/math/SafeMath.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

// Local Math Library
import "./libraries/SqrtMath.sol";

// Uniswap V3 Core
import "@uniswap/v3-core/contracts/interfaces/IUniswapV3Pool.sol";
import "@uniswap/v3-core/contracts/interfaces/IUniswapV3Factory.sol";
import "@uniswap/v3-core/contracts/interfaces/callback/IUniswapV3MintCallback.sol";
import "@uniswap/v3-core/contracts/libraries/TickMath.sol";

// Uniswap V3 Periphery
import "@uniswap/v3-periphery/contracts/interfaces/INonfungiblePositionManager.sol";
import "@uniswap/v3-periphery/contracts/interfaces/external/IWETH9.sol";

// Interface for decimals()
interface IERC20Decimals {
    function decimals() external view returns (uint8);
}

/**
 * @title PredictiveLiquidityManager
 * @notice قرارداد اصلی مدیریت نقدینگی که موقعیت‌ها را بر اساس پیش‌بینی قیمت تنظیم می‌کند
 */
contract PredictiveLiquidityManager is
    Ownable,
    ReentrancyGuard,
    IUniswapV3MintCallback
{
    using SafeERC20 for IERC20;
    using SafeMath for uint256;

    // --- متغیرهای وضعیت ---
    IUniswapV3Factory public immutable factory;
    INonfungiblePositionManager public immutable positionManager;
    address public immutable token0;
    address public immutable token1;
    uint8 public immutable token0Decimals;
    uint8 public immutable token1Decimals;
    uint24 public immutable fee;
    int24 public immutable tickSpacing;
    address public immutable WETH9;

    // ساختار موقعیت‌های نقدینگی
    struct Position {
        uint256 tokenId;
        uint128 liquidity;
        int24 tickLower;
        int24 tickUpper;
        bool active;
    }
    Position public currentPosition;

    // پارامترهای استراتژی
    uint24 public rangeWidthMultiplier = 4;

    // --- رویدادها ---
    // رویداد برای عملیات‌های نقدینگی
    event LiquidityOperation(
        string operationType,
        uint256 indexed tokenId,
        int24 tickLower,
        int24 tickUpper,
        uint128 liquidity,
        uint256 amount0,
        uint256 amount1,
        bool success
    );

    // رویداد برای خروجی منطق تنظیم اصلی
    event PredictionAdjustmentMetrics(
        uint256 timestamp,
        uint256 actualPrice,
        uint256 predictedPrice,
        int24 predictedTick,
        int24 finalTickLower,
        int24 finalTickUpper,
        bool adjusted
    );

    event StrategyParamUpdated(string indexed paramName, uint256 newValue);

    // --- سازنده ---
    constructor(
        address _factory,
        address _positionManager,
        address _token0,
        address _token1,
        uint24 _fee,
        address _weth9,
        address _initialOwner
    ) {
        // ذخیره مقادیر در متغیرهای immutable
        factory = IUniswapV3Factory(_factory);
        positionManager = INonfungiblePositionManager(_positionManager);
        token0 = _token0;
        token1 = _token1;
        fee = _fee;
        WETH9 = _weth9;

        // بررسی decimals با استفاده از try-catch
        try IERC20Decimals(_token0).decimals() returns (uint8 _decimals) {
            token0Decimals = _decimals;
        } catch {
            revert("Token0 does not support decimals()");
        }

        try IERC20Decimals(_token1).decimals() returns (uint8 _decimals) {
            token1Decimals = _decimals;
        } catch {
            revert("Token1 does not support decimals()");
        }

        // ذخیره tickSpacing در یک متغیر موقت
        address poolAddress = IUniswapV3Factory(_factory).getPool(
            _token0,
            _token1,
            _fee
        );
        require(poolAddress != address(0), "Pool does not exist");
        tickSpacing = IUniswapV3Pool(poolAddress).tickSpacing();

        // تنظیم approvals
        IERC20(_token0).safeApprove(
            address(_positionManager),
            type(uint256).max
        );
        IERC20(_token1).safeApprove(
            address(_positionManager),
            type(uint256).max
        );

        if (_initialOwner != address(0)) {
            transferOwnership(_initialOwner);
        }
    }

    // --- مدیریت نقدینگی خودکار (فقط مالک) ---
    function updatePredictionAndAdjust(
        uint256 predictedPriceDecimal
    ) external nonReentrant onlyOwner {
        // محاسبه اطلاعات قیمت و tick های پیش‌بینی شده
        (
            uint256 currentPriceDecimal,
            int24 currentTick,
            int24 predictedTick,
            int24 targetTickLower,
            int24 targetTickUpper
        ) = _calculatePredictionData(predictedPriceDecimal);

        // به‌روزرسانی موقعیت در صورت نیاز
        bool adjusted = _updatePositionIfNeeded(
            targetTickLower,
            targetTickUpper
        );

        // رویداد با استفاده از تابع کمکی برای کاهش عمق پشته
        _emitPredictionMetrics(
            currentPriceDecimal,
            predictedPriceDecimal,
            predictedTick,
            adjusted
        );
    }

    // تابع کمکی برای محاسبه داده‌های پیش‌بینی - کاهش عمق پشته
    function _calculatePredictionData(
        uint256 predictedPriceDecimal
    )
        internal
        view
        returns (
            uint256 currentPriceDecimal,
            int24 currentTick,
            int24 predictedTick,
            int24 targetTickLower,
            int24 targetTickUpper
        )
    {
        // بازیابی اطلاعات قیمت و tick فعلی
        uint160 sqrtPriceX96;
        int24 tick;
        (sqrtPriceX96, tick) = _getCurrentSqrtPriceAndTick();
        currentTick = tick;
        currentPriceDecimal = _sqrtPriceX96ToPrice(sqrtPriceX96);
        predictedTick = _priceToTick(predictedPriceDecimal);

        // محاسبه موقعیت جدید
        (targetTickLower, targetTickUpper) = _calculateTicks(predictedTick);

        return (
            currentPriceDecimal,
            currentTick,
            predictedTick,
            targetTickLower,
            targetTickUpper
        );
    }

    // تابع کمکی برای به‌روزرسانی موقعیت در صورت نیاز - کاهش عمق پشته
    function _updatePositionIfNeeded(
        int24 targetTickLower,
        int24 targetTickUpper
    ) internal returns (bool adjusted) {
        if (
            !currentPosition.active ||
            targetTickLower != currentPosition.tickLower ||
            targetTickUpper != currentPosition.tickUpper
        ) {
            _adjustLiquidity(targetTickLower, targetTickUpper);
            return true;
        }
        return false;
    }

    // --- کمک‌کننده‌های مدیریت نقدینگی داخلی ---
    function _adjustLiquidity(int24 tickLower, int24 tickUpper) internal {
        if (currentPosition.active) {
            _removeLiquidity();
        }
        uint256 balance0 = IERC20(token0).balanceOf(address(this));
        uint256 balance1 = IERC20(token1).balanceOf(address(this));
        if (balance0 > 0 || balance1 > 0) {
            _mintLiquidity(tickLower, tickUpper, balance0, balance1);
        } else {
            currentPosition = Position(0, 0, 0, 0, false);
        }
    }

    // تابع کمکی برای انتشار رویدادهای حذف نقدینگی - کاهش عمق پشته
    function _emitLiquidityRemoveEvent(
        uint256 tokenId,
        int24 tickLower,
        int24 tickUpper,
        uint128 liquidity,
        uint256 amount0,
        uint256 amount1,
        bool success
    ) internal {
        emit LiquidityOperation(
            "REMOVE",
            tokenId,
            tickLower,
            tickUpper,
            liquidity,
            amount0,
            amount1,
            success
        );
    }

    function _removeLiquidity() internal {
        require(
            currentPosition.active && currentPosition.tokenId != 0,
            "No active position"
        );
        uint256 _tokenId = currentPosition.tokenId;
        uint128 _liquidity = currentPosition.liquidity;
        int24 _tickLower = currentPosition.tickLower;
        int24 _tickUpper = currentPosition.tickUpper;

        currentPosition = Position(0, 0, 0, 0, false);

        // اجرای فرآیند حذف در یک تابع جداگانه برای جلوگیری از stack too deep
        _executeRemoval(_tokenId, _liquidity, _tickLower, _tickUpper);
    }

    // تابع کمکی برای اجرای حذف نقدینگی - کاهش عمق پشته
    function _executeRemoval(
        uint256 _tokenId,
        uint128 _liquidity,
        int24 _tickLower,
        int24 _tickUpper
    ) internal {
        bool decreaseSuccess = false;
        bool collectSuccess = false;
        uint256 amount0Collected = 0;
        uint256 amount1Collected = 0;

        if (_liquidity > 0) {
            try
                positionManager.decreaseLiquidity(
                    INonfungiblePositionManager.DecreaseLiquidityParams({
                        tokenId: _tokenId,
                        liquidity: _liquidity,
                        amount0Min: 0,
                        amount1Min: 0,
                        deadline: block.timestamp
                    })
                )
            {
                decreaseSuccess = true;
            } catch {
                // شکست خاموش، در انتها success = false برگردانده خواهد شد
            }
        } else {
            decreaseSuccess = true;
        }

        if (decreaseSuccess) {
            try
                positionManager.collect(
                    INonfungiblePositionManager.CollectParams({
                        tokenId: _tokenId,
                        recipient: address(this),
                        amount0Max: type(uint128).max,
                        amount1Max: type(uint128).max
                    })
                )
            returns (uint256 a0, uint256 a1) {
                amount0Collected = a0;
                amount1Collected = a1;
                collectSuccess = true;
            } catch {
                // شکست خاموش، در انتها success = false برگردانده خواهد شد
            }

            // سعی در burn بدون توجه به موفقیت collect
            try positionManager.burn(_tokenId) {} catch {}
        }

        bool overallSuccess = decreaseSuccess && collectSuccess;

        // استفاده از تابع کمکی برای انتشار رویداد - کاهش عمق پشته
        _emitLiquidityRemoveEvent(
            _tokenId,
            _tickLower,
            _tickUpper,
            _liquidity,
            amount0Collected,
            amount1Collected,
            overallSuccess
        );
    }

    // تابع کمکی برای انتشار رویدادهای ضرب نقدینگی - کاهش عمق پشته
    function _emitLiquidityMintEvent(
        uint256 tokenId,
        int24 tickLower,
        int24 tickUpper,
        uint128 liquidity,
        uint256 amount0,
        uint256 amount1,
        bool success
    ) internal {
        emit LiquidityOperation(
            "MINT",
            tokenId,
            tickLower,
            tickUpper,
            liquidity,
            amount0,
            amount1,
            success
        );
    }

    function _mintLiquidity(
        int24 tickLower,
        int24 tickUpper,
        uint256 amount0Desired,
        uint256 amount1Desired
    ) internal {
        require(!currentPosition.active, "Position already active");

        INonfungiblePositionManager.MintParams
            memory params = INonfungiblePositionManager.MintParams({
                token0: token0,
                token1: token1,
                fee: fee,
                tickLower: tickLower,
                tickUpper: tickUpper,
                amount0Desired: amount0Desired,
                amount1Desired: amount1Desired,
                amount0Min: 0,
                amount1Min: 0,
                recipient: address(this),
                deadline: block.timestamp
            });

        // اجرای ضرب و مدیریت ایجاد موقعیت در یک تابع جداگانه
        _executeMint(params, tickLower, tickUpper);
    }

    function _executeMint(
        INonfungiblePositionManager.MintParams memory params,
        int24 tickLower,
        int24 tickUpper
    ) internal {
        uint256 tokenId = 0;
        uint128 liquidity = 0;
        uint256 amount0Actual = 0;
        uint256 amount1Actual = 0;
        bool success = false;

        try positionManager.mint(params) returns (
            uint256 _tokenId,
            uint128 _liquidity,
            uint256 _amount0,
            uint256 _amount1
        ) {
            tokenId = _tokenId;
            liquidity = _liquidity;
            amount0Actual = _amount0;
            amount1Actual = _amount1;

            if (liquidity > 0) {
                currentPosition = Position(
                    tokenId,
                    liquidity,
                    tickLower,
                    tickUpper,
                    true
                );
                success = true;
            } else if (tokenId != 0) {
                try positionManager.burn(tokenId) {} catch {}
            }
        } catch {
            // شکست خاموش، رویداد با success = false منتشر خواهد شد
        }

        // استفاده از تابع کمکی برای انتشار رویداد - کاهش عمق پشته
        _emitLiquidityMintEvent(
            tokenId,
            tickLower,
            tickUpper,
            liquidity,
            amount0Actual,
            amount1Actual,
            success
        );

        if (!success) {
            currentPosition = Position(0, 0, 0, 0, false);
        }
    }

    // --- کمک‌کننده‌های محاسبه داخلی ---
    function _calculateTicks(
        int24 targetCenterTick
    ) internal view returns (int24 tickLower, int24 tickUpper) {
        require(tickSpacing > 0, "Invalid tick spacing");

        // محاسبه نیم عرض و اعمال حداقل عرض یک فاصله tick
        int24 halfWidth = (tickSpacing * int24(rangeWidthMultiplier)) / 2;
        if (halfWidth <= 0) halfWidth = tickSpacing;

        // محاسبه مرزهای tick خام
        int24 rawTickLower = targetCenterTick - halfWidth;
        int24 rawTickUpper = targetCenterTick + halfWidth;

        // تراز با فاصله tick
        tickLower = floorToTickSpacing(rawTickLower, tickSpacing);
        tickUpper = floorToTickSpacing(rawTickUpper, tickSpacing);

        // اطمینان از فاصله‌گذاری مناسب تیک‌ها
        if (tickLower >= tickUpper) {
            tickUpper = tickLower + tickSpacing;
        }

        // اطمینان از اینکه تیک‌ها در محدوده جهانی قرار دارند
        tickLower = tickLower < TickMath.MIN_TICK
            ? floorToTickSpacing(TickMath.MIN_TICK, tickSpacing)
            : tickLower;

        tickUpper = tickUpper > TickMath.MAX_TICK
            ? floorToTickSpacing(TickMath.MAX_TICK, tickSpacing)
            : tickUpper;

        // بررسی نهایی برای اطمینان از ترتیب مناسب
        if (tickLower >= tickUpper) {
            tickUpper = tickLower + tickSpacing;

            // اگر tick بالا از MAX_TICK فراتر رود، هر دو را تنظیم کنید
            if (tickUpper > TickMath.MAX_TICK) {
                tickUpper = floorToTickSpacing(TickMath.MAX_TICK, tickSpacing);
                tickLower = tickUpper - tickSpacing;
            }
        }

        return (tickLower, tickUpper);
    }

    function floorToTickSpacing(
        int24 tick,
        int24 _tickSpacing
    ) internal pure returns (int24) {
        require(_tickSpacing > 0, "Tick spacing must be positive");
        int24 compressed = tick / _tickSpacing;
        if (tick < 0 && (tick % _tickSpacing != 0)) {
            compressed--;
        }
        return compressed * _tickSpacing;
    }

    function _getCurrentSqrtPriceAndTick()
        internal
        view
        returns (uint160 sqrtPriceX96, int24 tick)
    {
        address poolAddress = factory.getPool(token0, token1, fee);
        require(poolAddress != address(0), "Pool doesn't exist");
        (sqrtPriceX96, tick, , , , , ) = IUniswapV3Pool(poolAddress).slot0();
    }

    function _priceToTick(uint256 priceDecimal) internal view returns (int24) {
        require(priceDecimal > 0, "Price must be > 0");

        uint256 numerator = priceDecimal;
        uint256 denominator = 1e18;

        if (token1Decimals > token0Decimals) {
            numerator = numerator.mul(
                10 ** (uint256(token1Decimals).sub(token0Decimals))
            );
        } else if (token0Decimals > token1Decimals) {
            denominator = denominator.mul(
                10 ** (uint256(token0Decimals).sub(token1Decimals))
            );
        }

        uint256 ratioX192 = numerator.mul(1 << 192).div(denominator);

        uint160 sqrtPriceX96 = uint160(SqrtMath.sqrt(ratioX192));

        require(sqrtPriceX96 >= TickMath.MIN_SQRT_RATIO, "Price too low");
        require(sqrtPriceX96 <= TickMath.MAX_SQRT_RATIO, "Price too high");

        return TickMath.getTickAtSqrtRatio(sqrtPriceX96);
    }

    function _sqrtPriceX96ToPrice(
        uint160 sqrtPriceX96
    ) internal view returns (uint256 priceDecimal) {
        uint256 ratioX192 = uint256(sqrtPriceX96).mul(uint256(sqrtPriceX96));

        uint256 numerator = ratioX192;
        uint256 denominator = (1 << 192);

        if (token0Decimals > token1Decimals) {
            numerator = numerator.mul(
                10 ** (uint256(token0Decimals).sub(token1Decimals))
            );
        } else if (token1Decimals > token0Decimals) {
            denominator = denominator.mul(
                10 ** (uint256(token1Decimals).sub(token0Decimals))
            );
        }

        priceDecimal = numerator.mul(1e18).div(denominator);
    }

    // --- Uniswap V3 Mint Callback ---
    function uniswapV3MintCallback(
        uint256 amount0Owed,
        uint256 amount1Owed,
        bytes calldata /* data */
    ) external override {
        address pool = factory.getPool(token0, token1, fee);
        require(msg.sender == pool, "Callback sender invalid");

        if (amount0Owed > 0) {
            require(
                IERC20(token0).balanceOf(address(this)) >= amount0Owed,
                "Insufficient T0 for callback"
            );
            IERC20(token0).safeTransfer(msg.sender, amount0Owed);
        }
        if (amount1Owed > 0) {
            require(
                IERC20(token1).balanceOf(address(this)) >= amount1Owed,
                "Insufficient T1 for callback"
            );
            IERC20(token1).safeTransfer(msg.sender, amount1Owed);
        }
    }

    // --- تنظیم پارامتر استراتژی ---
    function setRangeWidthMultiplier(uint24 _multiplier) external onlyOwner {
        require(_multiplier > 0, "Multiplier must be positive");
        rangeWidthMultiplier = _multiplier;
        emit StrategyParamUpdated("rangeWidthMultiplier", _multiplier);
    }

    // --- توابع نمایشی ---
    function getActivePositionDetails()
        external
        view
        returns (
            uint256 tokenId,
            uint128 liquidity,
            int24 tickLower,
            int24 tickUpper,
            bool active
        )
    {
        return (
            currentPosition.tokenId,
            currentPosition.liquidity,
            currentPosition.tickLower,
            currentPosition.tickUpper,
            currentPosition.active
        );
    }

    function getContractBalances()
        external
        view
        returns (uint256 balance0, uint256 balance1, uint256 balanceWETH)
    {
        balance0 = IERC20(token0).balanceOf(address(this));
        balance1 = IERC20(token1).balanceOf(address(this));
        balanceWETH = WETH9 != address(0)
            ? IERC20(WETH9).balanceOf(address(this))
            : 0;
    }

    function getPoolAddress() external view returns (address) {
        return factory.getPool(token0, token1, fee);
    }

    // کمک‌کننده برای بررسی مقدار مطلق
    function abs(int256 x) private pure returns (uint256) {
        return uint256(x >= 0 ? x : -x);
    }

    // تابع کمکی برای انتشار متریک‌ها - کاهش عمق پشته در تابع اصلی
    function _emitPredictionMetrics(
        uint256 currentPriceDecimal,
        uint256 predictedPriceDecimal,
        int24 predictedTick,
        bool adjusted
    ) internal {
        emit PredictionAdjustmentMetrics(
            block.timestamp,
            currentPriceDecimal,
            predictedPriceDecimal,
            predictedTick,
            currentPosition.tickLower,
            currentPosition.tickUpper,
            adjusted
        );
    }

    // --- Receive function ---
    receive() external payable {}
}
