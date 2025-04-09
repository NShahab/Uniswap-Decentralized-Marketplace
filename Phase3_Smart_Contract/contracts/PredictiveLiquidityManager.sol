// SPDX-License-Identifier: MIT
pragma solidity ^0.7.6;
pragma abicoder v2; // To support structs in parameters

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
 * @notice The main liquidity management contract that adjusts positions based on price predictions
 */
contract PredictiveLiquidityManager is
    Ownable,
    ReentrancyGuard,
    IUniswapV3MintCallback
{
    using SafeERC20 for IERC20;
    using SafeMath for uint256;

    // --- State Variables ---
    IUniswapV3Factory public immutable factory;
    INonfungiblePositionManager public immutable positionManager;
    address public immutable token0;
    address public immutable token1;
    uint8 public immutable token0Decimals;
    uint8 public immutable token1Decimals;
    uint24 public immutable fee;
    int24 public immutable tickSpacing;
    address public immutable WETH9;

    // Structure for liquidity positions
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

    // --- Events ---
    // Event for liquidity operations
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

    // Event for outputting main adjustment logic
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

    // --- Constructor ---
    constructor(
        address _factory,
        address _positionManager,
        address _token0,
        address _token1,
        uint24 _fee,
        address _weth9,
        address _initialOwner
    ) {
        // Store values in immutable variables
        factory = IUniswapV3Factory(_factory);
        positionManager = INonfungiblePositionManager(_positionManager);
        token0 = _token0;
        token1 = _token1;
        fee = _fee;
        WETH9 = _weth9;

        // Check decimals using try-catch
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

        // Store tickSpacing in a temporary variable
        address poolAddress = IUniswapV3Factory(_factory).getPool(
            _token0,
            _token1,
            _fee
        );
        require(poolAddress != address(0), "Pool does not exist");
        tickSpacing = IUniswapV3Pool(poolAddress).tickSpacing();

        // Set approvals for token0 and token1
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

    // --- Automated Liquidity Management (Owner Only) ---
    function updatePredictionAndAdjust(
        uint256 predictedPriceDecimal
    ) external nonReentrant onlyOwner {
        // Calculate current price and predicted tick information
        (
            uint256 currentPriceDecimal,
            int24 currentTick,
            int24 predictedTick,
            int24 targetTickLower,
            int24 targetTickUpper
        ) = _calculatePredictionData(predictedPriceDecimal);

        // Update position if needed
        bool adjusted = _updatePositionIfNeeded(
            targetTickLower,
            targetTickUpper
        );

        // Emit prediction adjustment metrics using a helper function to reduce stack depth
        _emitPredictionMetrics(
            currentPriceDecimal,
            predictedPriceDecimal,
            predictedTick,
            targetTickLower,
            targetTickUpper,
            adjusted
        );
    }

    // Helper function for calculating prediction data - reducing stack depth
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
        // Retrieve current price and tick information
        uint160 sqrtPriceX96;
        int24 tick;
        (sqrtPriceX96, tick) = _getCurrentSqrtPriceAndTick();
        currentTick = tick;
        currentPriceDecimal = _sqrtPriceX96ToPrice(sqrtPriceX96);
        predictedTick = _priceToTick(predictedPriceDecimal);

        // Calculate new position
        (targetTickLower, targetTickUpper) = _calculateTicks(predictedTick);

        return (
            currentPriceDecimal,
            currentTick,
            predictedTick,
            targetTickLower,
            targetTickUpper
        );
    }

    // Helper function to update position if needed - reducing stack depth
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
            currentPosition = Position(0, 0, 0, 0, false);
        }
    }

    // Helper function for emitting liquidity removal events - reducing stack depth
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

        // Executing removal process in a separate function to prevent stack too deep
        _executeRemoval(_tokenId, _liquidity, _tickLower, _tickUpper);
    }

    // Helper function for executing liquidity removal - reducing stack depth
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
                // Silent failure, success = false will be returned at the end
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
                // Silent failure, success = false will be returned at the end
            }

            // Try to burn regardless of collect success
            try positionManager.burn(_tokenId) {} catch {}
        }

        bool overallSuccess = decreaseSuccess && collectSuccess;

        // Using helper function to emit event - reducing stack depth
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

    // Helper function for emitting liquidity mint events - reducing stack depth
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

        // Execute mint and manage position creation in a separate function
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
            // Silent failure, event will be emitted with success = false
        }

        // Using helper function to emit event - reducing stack depth
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

    // --- Internal Calculation Helpers ---
    function _calculateTicks(
        int24 targetCenterTick
    ) internal view returns (int24 tickLower, int24 tickUpper) {
        require(tickSpacing > 0, "Invalid tick spacing");

        // Calculate half width with better symmetry
        int24 halfWidth = (tickSpacing * int24(rangeWidthMultiplier)) / 2;
        if (halfWidth <= 0) halfWidth = tickSpacing;

        // Ensure half width is a multiple of tick spacing for perfect symmetry
        halfWidth = (halfWidth / tickSpacing) * tickSpacing;
        if (halfWidth == 0) halfWidth = tickSpacing;

        // Calculate raw tick boundaries with better centering
        int24 rawTickLower = targetCenterTick - halfWidth;
        int24 rawTickUpper = targetCenterTick + halfWidth;

        // Align with tick spacing
        tickLower = floorToTickSpacing(rawTickLower, tickSpacing);
        tickUpper = floorToTickSpacing(rawTickUpper, tickSpacing);

        // If upper tick is not properly spaced after flooring, add another tick spacing
        if ((rawTickUpper % tickSpacing) != 0) {
            tickUpper += tickSpacing;
        }

        // Ensure proper spacing between ticks
        if (tickLower >= tickUpper) {
            tickUpper = tickLower + tickSpacing;
        }

        // Ensure ticks are within global range
        tickLower = tickLower < TickMath.MIN_TICK
            ? floorToTickSpacing(TickMath.MIN_TICK, tickSpacing)
            : tickLower;

        tickUpper = tickUpper > TickMath.MAX_TICK
            ? floorToTickSpacing(TickMath.MAX_TICK, tickSpacing)
            : tickUpper;

        // Final check to ensure proper ordering
        if (tickLower >= tickUpper) {
            tickUpper = tickLower + tickSpacing;

            // If upper tick exceeds MAX_TICK, adjust both
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

    // Helper function to convert sqrtPriceX96 to price decimal
    function _sqrtPriceX96ToPrice(
        uint160 sqrtPriceX96
    ) internal view returns (uint256) {
        uint256 price = uint256(sqrtPriceX96) * uint256(sqrtPriceX96);
        uint256 adjustedPrice = price >> 192; // Divide by 2^192

        // Adjust for decimal differences between tokens
        if (token1Decimals > token0Decimals) {
            adjustedPrice =
                adjustedPrice /
                (10 ** (token1Decimals - token0Decimals));
        } else if (token0Decimals > token1Decimals) {
            adjustedPrice =
                adjustedPrice *
                (10 ** (token0Decimals - token1Decimals));
        }

        return adjustedPrice;
    }

    function _priceToTick(uint256 priceDecimal) internal view returns (int24) {
        require(priceDecimal > 0, "Price must be > 0");

        // If the input price is ETH/USDC (e.g., 1500)
        // We need to convert it to WETH/USDC (e.g., 1/1500 = 0.00066)
        // To match Uniswap's logic which uses token1/token0 ratio

        // Calculate inverted price
        uint256 invertedPrice;
        if (priceDecimal > 1e12) {
            // If price is large (if price is ETH/USDC)
            // Invert price with high precision
            // Use 1e36 to maintain precision in division
            invertedPrice = uint256(1e36).div(priceDecimal);
        } else {
            // If price is small (likely already inverted), use it as is
            invertedPrice = priceDecimal;
        }

        // Adjust for decimal differences
        uint256 numerator = invertedPrice;
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

        // Calculate ratioX192 considering inverted price
        uint256 ratioX192 = numerator.mul(1 << 192).div(denominator);

        uint160 sqrtPriceX96 = uint160(SqrtMath.sqrt(ratioX192));

        // Check Uniswap constraints
        require(sqrtPriceX96 >= TickMath.MIN_SQRT_RATIO, "Price too low");
        require(sqrtPriceX96 <= TickMath.MAX_SQRT_RATIO, "Price too high");

        return TickMath.getTickAtSqrtRatio(sqrtPriceX96);
    }

    // Helper function to emit prediction metrics event
    function _emitPredictionMetrics(
        uint256 actualPrice,
        uint256 predictedPrice,
        int24 predictedTick,
        int24 finalTickLower,
        int24 finalTickUpper,
        bool adjusted
    ) internal {
        emit PredictionAdjustmentMetrics(
            block.timestamp,
            actualPrice,
            predictedPrice,
            predictedTick,
            finalTickLower,
            finalTickUpper,
            adjusted
        );
    }

    // Implement IUniswapV3MintCallback interface
    function uniswapV3MintCallback(
        uint256 amount0Owed,
        uint256 amount1Owed,
        bytes calldata data
    ) external override {
        // Verify the caller is the Uniswap V3 position manager
        require(
            msg.sender == address(positionManager),
            "Unauthorized callback"
        );

        // Send the required tokens
        if (amount0Owed > 0) {
            IERC20(token0).safeTransfer(msg.sender, amount0Owed);
        }
        if (amount1Owed > 0) {
            IERC20(token1).safeTransfer(msg.sender, amount1Owed);
        }
    }
}
