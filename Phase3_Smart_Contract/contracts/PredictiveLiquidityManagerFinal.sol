// SPDX-License-Identifier: MIT
pragma solidity ^0.7.6;
pragma abicoder v2; // اضافه کردن این خط برای پشتیبانی از struct ها در پارامترها

// OpenZeppelin ~3.4.0 Imports --- Updated Paths ---
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
// import "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol"; // Not available in OZ 3.4, decimals usually called directly on IERC20
import "@openzeppelin/contracts/token/ERC20/SafeERC20.sol"; // Path updated
import "@openzeppelin/contracts/math/SafeMath.sol"; // --- Added SafeMath ---
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol"; // Path updated

// Local Math Library (copied from OZ 4.x, made 0.7.6 compatible)
import "./libraries/SqrtMath.sol"; // --- Added Local Math Import ---

// Uniswap V3 Core (نسخه 1.0.0)
import "@uniswap/v3-core/contracts/interfaces/IUniswapV3Pool.sol";
import "@uniswap/v3-core/contracts/interfaces/IUniswapV3Factory.sol";
import "@uniswap/v3-core/contracts/interfaces/callback/IUniswapV3MintCallback.sol";
import "@uniswap/v3-core/contracts/libraries/TickMath.sol";

// Uniswap V3 Periphery (نسخه 1.4.3)
import "@uniswap/v3-periphery/contracts/interfaces/INonfungiblePositionManager.sol";
import "@uniswap/v3-periphery/contracts/interfaces/ISwapRouter.sol";
import "@uniswap/v3-periphery/contracts/interfaces/external/IWETH9.sol";
// import "@uniswap/v3-periphery/contracts/interfaces/IPeripheryPayments.sol"; // --- Removed Import ---

// اضافه کردن این اینترفیس قبل از تعریف قرارداد اصلی
interface IERC20Decimals {
    function decimals() external view returns (uint8);
}

/**
 * @title IPredictiveLiquidityManager
 * @notice اینترفیس قرارداد مدیریت نقدینگی پیش‌بینی
 */
interface IPredictiveLiquidityManager {
    struct SwapParams {
        address tokenIn;
        address tokenOut;
        uint24 poolFee;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    function updatePredictionAndAdjust(uint256 predictedPriceDecimal) external;
    function swap(
        SwapParams calldata params
    ) external returns (uint256 amountOut);
    function setRangeWidthMultiplier(uint24 _multiplier) external;
    function getActivePositionDetails()
        external
        view
        returns (
            uint256 tokenId,
            uint128 liquidity,
            int24 tickLower,
            int24 tickUpper,
            bool active
        );
    function getContractBalances()
        external
        view
        returns (uint256 balance0, uint256 balance1, uint256 balanceWETH);
    function getPoolAddress() external view returns (address);
}

// --- Contract Definition ---
contract PredictiveLiquidityManagerFinal is
    Ownable,
    ReentrancyGuard,
    IUniswapV3MintCallback
    // IPeripheryPayments  -- Removed inheritance
{
    using SafeERC20 for IERC20;
    using SafeMath for uint256; // --- Using SafeMath for uint256 ---
    // using Math for uint256; // Use local Math library directly where needed

    // --- State Variables ---
    IUniswapV3Factory public immutable factory;
    INonfungiblePositionManager public immutable positionManager;
    ISwapRouter public immutable swapRouter;
    address public immutable token0;
    address public immutable token1;
    uint8 public immutable token0Decimals;
    uint8 public immutable token1Decimals;
    uint24 public immutable fee;
    int24 public immutable tickSpacing;
    address public immutable WETH9;

    struct Position {
        uint256 tokenId;
        uint128 liquidity;
        int24 tickLower;
        int24 tickUpper;
        bool active;
    }
    Position public currentPosition;

    // Strategy Parameters
    uint24 public rangeWidthMultiplier = 4;

    // Swap Parameters Struct
    struct SwapParams {
        address tokenIn;
        address tokenOut;
        uint24 poolFee;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    // ایونت‌های اصلی
    event OperationReported(
        uint256 actualPrice,
        uint256 predictedPrice,
        int24 currentTick,
        int24 predictedTick,
        bool adjusted,
        uint256 gasUsed
    );

    event LiquidityAdjusted(
        uint256 tokenId,
        int24 tickLower,
        int24 tickUpper,
        uint128 liquidity
    );

    event LiquidityRemoved(
        uint256 indexed tokenId,
        uint256 amount0,
        uint256 amount1
    );

    event Swapped(
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 amountIn,
        uint256 amountOut
    );

    event Deposited(
        address indexed token,
        address indexed sender,
        uint256 amount
    );

    event Withdrawn(
        address indexed token,
        address indexed recipient,
        uint256 amount
    );

    event LiquidityMintFailed(
        uint256 amount0Desired,
        uint256 amount1Desired,
        string reason
    );

    event LiquidityRemoveFailed(uint256 indexed tokenId, string reason);

    event StrategyParamUpdated(string paramName, uint256 newValue);

    // ایونت جدید برای جمع‌آوری داده‌ها
    event LiquidityManagementMetrics(
        uint256 timestamp, // زمان عملیات
        uint256 actualPrice, // قیمت واقعی
        uint256 predictedPrice, // قیمت پیش‌بینی شده LSTM
        int24 currentTick, // تیک فعلی
        int24 predictedTick, // تیک پیش‌بینی شده
        int24 tickLower, // تیک پایین محدوده نقدینگی
        int24 tickUpper, // تیک بالای محدوده نقدینگی
        uint128 liquidity, // مقدار نقدینگی
        uint256 amount0, // مقدار توکن 0
        uint256 amount1 // مقدار توکن 1
    );

    // --- Constructor ---
    constructor(
        address _factory,
        address _positionManager,
        address _swapRouter,
        address _token0,
        address _token1,
        uint24 _fee,
        address _weth9,
        address _initialOwner
    ) {
        // ذخیره مقادیر در متغیرهای immutable
        factory = IUniswapV3Factory(_factory);
        positionManager = INonfungiblePositionManager(_positionManager);
        swapRouter = ISwapRouter(_swapRouter);
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

        // تنظیم مجوزها با استفاده از آدرس‌های ورودی به جای متغیرهای immutable
        IERC20(_token0).safeApprove(
            address(_positionManager),
            type(uint256).max
        );
        IERC20(_token1).safeApprove(
            address(_positionManager),
            type(uint256).max
        );
        IERC20(_token0).safeApprove(address(_swapRouter), type(uint256).max);
        IERC20(_token1).safeApprove(address(_swapRouter), type(uint256).max);

        if (_weth9 != address(0)) {
            IERC20(_weth9).safeApprove(
                address(_positionManager),
                type(uint256).max
            );
            IERC20(_weth9).safeApprove(address(_swapRouter), type(uint256).max);
        }

        if (_initialOwner != address(0)) {
            transferOwnership(_initialOwner);
        }
    }

    // --- Automated Liquidity Management (Owner Only) ---
    function updatePredictionAndAdjust(
        uint256 predictedPriceDecimal
    ) external nonReentrant onlyOwner {
        uint256 gasStart = gasleft();
        bool adjusted = false;

        // دریافت اطلاعات قیمت و تیک فعلی
        (
            uint160 sqrtPriceX96,
            int24 currentTick
        ) = _getCurrentSqrtPriceAndTick();
        uint256 currentPriceDecimal = _sqrtPriceX96ToPrice(sqrtPriceX96);
        int24 predictedTick = _priceToTick(predictedPriceDecimal);

        // محاسبه موقعیت جدید
        (int24 targetTickLower, int24 targetTickUpper) = _calculateTicks(
            predictedTick
        );

        // بروزرسانی موقعیت در صورت نیاز
        if (
            !currentPosition.active ||
            targetTickLower != currentPosition.tickLower ||
            targetTickUpper != currentPosition.tickUpper
        ) {
            _adjustLiquidity(targetTickLower, targetTickUpper);
            adjusted = true;
        }

        // ارسال داده‌ها برای گزارش عملیاتی
        emit OperationReported(
            currentPriceDecimal,
            predictedPriceDecimal,
            currentTick,
            predictedTick,
            adjusted,
            gasStart - gasleft()
        );

        // ارسال داده‌ها برای تحلیل
        emit LiquidityManagementMetrics(
            block.timestamp,
            currentPriceDecimal,
            predictedPriceDecimal,
            currentTick,
            predictedTick,
            currentPosition.tickLower,
            currentPosition.tickUpper,
            currentPosition.liquidity,
            IERC20(token0).balanceOf(address(this)),
            IERC20(token1).balanceOf(address(this))
        );
    }

    function swap(
        SwapParams calldata params
    ) external nonReentrant onlyOwner returns (uint256 amountOut) {
        require(
            params.tokenIn == token0 || params.tokenIn == token1,
            "Invalid tokenIn"
        );
        require(
            params.tokenOut == token0 || params.tokenOut == token1,
            "Invalid tokenOut"
        );

        // انتقال توکن‌ها
        IERC20(params.tokenIn).safeTransferFrom(
            msg.sender,
            address(this),
            params.amountIn
        );
        IERC20(params.tokenIn).safeApprove(
            address(swapRouter),
            params.amountIn
        );

        // انجام سواپ
        ISwapRouter.ExactInputSingleParams memory swapParams = ISwapRouter
            .ExactInputSingleParams({
                tokenIn: params.tokenIn,
                tokenOut: params.tokenOut,
                fee: params.poolFee,
                recipient: address(this),
                deadline: block.timestamp,
                amountIn: params.amountIn,
                amountOutMinimum: params.amountOutMinimum,
                sqrtPriceLimitX96: params.sqrtPriceLimitX96
            });

        amountOut = swapRouter.exactInputSingle(swapParams);
        emit Swapped(
            params.tokenIn,
            params.tokenOut,
            params.amountIn,
            amountOut
        );

        // ریست تأییدیه
        IERC20(params.tokenIn).safeApprove(address(swapRouter), 0);

        return amountOut;
    }

    // --- Internal Liquidity Management Helpers ---
    function _adjustLiquidity(int24 tickLower, int24 tickUpper) internal {
        if (currentPosition.active) {
            _removeLiquidity();
        }
        uint256 balance0 = IERC20(token0).balanceOf(address(this));
        uint256 balance1 = IERC20(token1).balanceOf(address(this));
        if (balance0 > 0 || balance1 > 0) {
            _mintLiquidity(tickLower, tickUpper, balance0, balance1);
        } else {
            currentPosition.active = false;
            currentPosition.tokenId = 0;
            currentPosition.liquidity = 0;
        }
    }

    function _removeLiquidity() internal {
        require(
            currentPosition.active && currentPosition.tokenId != 0,
            "No active position"
        );
        uint256 currentTokenId = currentPosition.tokenId;
        uint128 currentLiquidity = currentPosition.liquidity;

        // پاک کردن وضعیت قبل از فراخوانی خارجی
        currentPosition.active = false;
        uint256 _tokenId = currentPosition.tokenId;
        currentPosition.tokenId = 0;
        currentPosition.liquidity = 0;
        currentPosition.tickLower = 0;
        currentPosition.tickUpper = 0;

        bool decreased = false;
        bool collected = false;
        string memory errorMsg = "";

        // کاهش نقدینگی
        if (currentLiquidity > 0) {
            try
                positionManager.decreaseLiquidity(
                    INonfungiblePositionManager.DecreaseLiquidityParams({
                        tokenId: _tokenId,
                        liquidity: currentLiquidity,
                        amount0Min: 0,
                        amount1Min: 0,
                        deadline: block.timestamp
                    })
                )
            {
                decreased = true;
            } catch Error(string memory reason) {
                errorMsg = reason;
            } catch {
                errorMsg = "Decrease failed";
            }
        } else {
            decreased = true;
        }

        // جمع‌آوری توکن‌ها
        (uint256 amount0, uint256 amount1) = (0, 0);
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
            (amount0, amount1) = (a0, a1);
            collected = true;
        } catch Error(string memory reason) {
            if (bytes(errorMsg).length == 0) errorMsg = reason;
        } catch {
            if (bytes(errorMsg).length == 0) errorMsg = "Collect failed";
        }

        // سوزاندن NFT
        if (decreased) {
            try positionManager.burn(_tokenId) {} catch {}
        }

        if (!decreased || !collected) {
            emit LiquidityRemoveFailed(_tokenId, errorMsg);
        }

        emit LiquidityRemoved(_tokenId, amount0, amount1);
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

        uint256 tokenId;
        uint128 liquidity;
        uint256 amount0Actual;
        uint256 amount1Actual;

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
                emit LiquidityAdjusted(
                    tokenId,
                    tickLower,
                    tickUpper,
                    liquidity
                );
            } else {
                try positionManager.burn(tokenId) {} catch {}
                emit LiquidityMintFailed(
                    amount0Desired,
                    amount1Desired,
                    "Zero liquidity minted"
                );
            }
        } catch Error(string memory reason) {
            emit LiquidityMintFailed(amount0Desired, amount1Desired, reason);
        } catch {
            emit LiquidityMintFailed(
                amount0Desired,
                amount1Desired,
                "Unknown mint error"
            );
        }
    }

    // --- Internal Calculation Helpers ---
    function _calculateTicks(
        int24 targetCenterTick
    ) internal view returns (int24 tickLower, int24 tickUpper) {
        int24 halfWidth = tickSpacing * int24(rangeWidthMultiplier);

        tickLower = (targetCenterTick / tickSpacing) * tickSpacing - halfWidth;
        tickUpper = (targetCenterTick / tickSpacing) * tickSpacing + halfWidth;

        if (tickLower < TickMath.MIN_TICK) tickLower = TickMath.MIN_TICK;
        if (tickUpper > TickMath.MAX_TICK) tickUpper = TickMath.MAX_TICK;
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
        uint256 priceForSqrt;
        if (token1Decimals >= token0Decimals) {
            uint256 factor = 10 **
                (uint256(token1Decimals).sub(uint256(token0Decimals)));
            priceForSqrt = priceDecimal.div(factor);
        } else {
            uint256 factor = 10 **
                (uint256(token0Decimals).sub(uint256(token1Decimals)));
            priceForSqrt = priceDecimal.mul(factor);
        }

        uint160 sqrtPriceX96 = uint160(
            SqrtMath.sqrt(priceForSqrt).mul(2 ** 96)
        );
        return TickMath.getTickAtSqrtRatio(sqrtPriceX96);
    }

    function _sqrtPriceX96ToPrice(
        uint160 sqrtPriceX96
    ) internal view returns (uint256 priceDecimal) {
        uint256 ratioX192 = uint256(sqrtPriceX96).mul(uint256(sqrtPriceX96));
        uint256 priceUnadjusted = ratioX192 >> 192;

        if (token1Decimals >= token0Decimals) {
            uint256 factor = 10 **
                (uint256(token1Decimals).sub(uint256(token0Decimals)));
            priceDecimal = priceUnadjusted.mul(factor);
        } else {
            uint256 factor = 10 **
                (uint256(token0Decimals).sub(uint256(token1Decimals)));
            priceDecimal = priceUnadjusted.div(factor);
        }
    }

    // --- Emit Event ---
    function _emitOperationReported(
        uint256 _actualPrice,
        uint256 _predictedPrice,
        int24 _currentTick,
        int24 _predictedTick,
        bool _adjusted,
        uint256 _gasUsed
    ) internal {
        emit OperationReported(
            _actualPrice,
            _predictedPrice,
            _currentTick,
            _predictedTick,
            _adjusted,
            _gasUsed
        );
    }

    // --- Uniswap V3 Mint Callback ---
    function uniswapV3MintCallback(
        uint256 amount0Owed,
        uint256 amount1Owed,
        bytes calldata /* data */
    ) external override {
        require(
            msg.sender == address(positionManager),
            "Callback sender mismatch"
        );

        if (amount0Owed > 0) {
            IERC20(token0).safeTransfer(msg.sender, amount0Owed);
        }
        if (amount1Owed > 0) {
            IERC20(token1).safeTransfer(msg.sender, amount1Owed);
        }
    }

    // --- Payments Functions ---
    receive() external payable {} // Keep payable receive

    function refundETH() external payable {
        require(address(this).balance > 0, "No ETH to refund");
        payable(msg.sender).transfer(address(this).balance);
    }

    function sweepToken(
        address token,
        uint256 amountMinimum,
        address recipient
    ) external payable onlyOwner {
        require(recipient != address(0), "Invalid recipient");
        uint256 balance = IERC20(token).balanceOf(address(this));
        require(balance >= amountMinimum, "Insufficient balance");
        IERC20(token).safeTransfer(recipient, balance);
    }

    function unwrapWETH9(
        uint256 amountMinimum,
        address recipient
    ) external payable {
        require(WETH9 != address(0), "WETH9 not set");
        require(recipient != address(0), "Invalid recipient");
        uint256 balance = IWETH9(WETH9).balanceOf(address(this));
        require(balance >= amountMinimum, "Insufficient WETH");
        IWETH9(WETH9).withdraw(balance);
        payable(recipient).transfer(balance);
    }

    // --- Token Handling (Owner Only) ---
    function depositToken(
        address _token,
        uint256 _amount
    ) external nonReentrant onlyOwner {
        require(
            _token == token0 ||
                _token == token1 ||
                (_token == WETH9 && WETH9 != address(0)), // Allow WETH9 deposit only if set
            "Invalid deposit token"
        );
        require(_amount > 0, "Deposit amount zero");
        IERC20(_token).safeTransferFrom(msg.sender, address(this), _amount);
        emit Deposited(_token, msg.sender, _amount);
    }

    function depositETH() external payable nonReentrant onlyOwner {
        require(WETH9 != address(0), "WETH9 address not set");
        require(msg.value > 0, "Deposit ETH value zero");
        // Wrap received ETH into WETH9
        IWETH9(WETH9).deposit{value: msg.value}();
        emit Deposited(WETH9, msg.sender, msg.value); // Emit WETH9 address
    }

    function withdrawToken(
        address _token,
        uint256 _amount,
        address _recipient
    ) external nonReentrant onlyOwner {
        require(_recipient != address(0), "Invalid recipient address");
        require(_amount > 0, "Withdraw amount zero");
        // Check sufficient balance before transfer
        require(
            IERC20(_token).balanceOf(address(this)) >= _amount,
            "Insufficient balance"
        );
        IERC20(_token).safeTransfer(_recipient, _amount);
        emit Withdrawn(_token, _recipient, _amount);
    }

    function withdrawETH(
        uint256 _amount,
        address payable _recipient // Use address payable directly
    ) external nonReentrant onlyOwner {
        require(WETH9 != address(0), "WETH9 address not set");
        require(_recipient != address(0), "Invalid recipient address");
        require(_amount > 0, "Withdraw amount zero");
        // Check sufficient WETH balance before unwrapping
        require(
            IWETH9(WETH9).balanceOf(address(this)) >= _amount,
            "Insufficient WETH balance"
        );

        // Unwrap WETH9 to ETH
        IWETH9(WETH9).withdraw(_amount);
        // Transfer ETH to recipient
        _recipient.transfer(_amount); // Use transfer or low-level call
        emit Withdrawn(WETH9, _recipient, _amount); // Emit WETH9 address
    }

    // --- Strategy Parameter Adjustment ---
    function setRangeWidthMultiplier(uint24 _multiplier) external onlyOwner {
        require(_multiplier > 0 && _multiplier <= 100, "Invalid multiplier");
        rangeWidthMultiplier = _multiplier;
        emit StrategyParamUpdated("rangeWidthMultiplier", _multiplier);
    }

    // --- View Functions (Remain mostly the same) ---
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

    // Helper to check absolute value for decimals difference
    function abs(int256 x) private pure returns (uint256) {
        return uint256(x >= 0 ? x : -x);
    }
}
