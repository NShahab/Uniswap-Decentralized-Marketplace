// SPDX-License-Identifier: MIT
pragma solidity ^0.7.6;
pragma abicoder v2; // To support structs in parameters

// OpenZeppelin ~3.4.0 Imports
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/SafeERC20.sol";
import "@openzeppelin/contracts/math/SafeMath.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

// Uniswap V3 Periphery
import "@uniswap/v3-periphery/contracts/interfaces/ISwapRouter.sol";
import "@uniswap/v3-periphery/contracts/interfaces/external/IWETH9.sol";

/**
 * @title TokenOperationsManager
 * @notice Contract for managing token operations like swaps, deposits, and withdrawals
 */
contract TokenOperationsManager is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;
    using SafeMath for uint256;

    // --- State Variables ---
    ISwapRouter public immutable swapRouter;
    address public immutable WETH9;

    // Struct for swap parameters
    struct SwapParams {
        address tokenIn;
        address tokenOut;
        uint24 poolFee;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    // --- Events ---
    // Combined event for token deposits and withdrawals
    event TokenOperation(
        string operationType,
        address indexed token,
        address indexed user,
        uint256 amount
    );

    // Simplified swap event
    event Swapped(
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 amountOut
    );

    // --- Constructor ---
    constructor(address _swapRouter, address _weth9, address _initialOwner) {
        // Store values in immutable variables
        swapRouter = ISwapRouter(_swapRouter);
        WETH9 = _weth9;

        if (_initialOwner != address(0)) {
            transferOwnership(_initialOwner);
        }
    }

    // --- Token Management Functions ---
    function swap(
        SwapParams calldata params
    ) external nonReentrant onlyOwner returns (uint256 amountOut) {
        // Transfer tokens from sender to contract
        IERC20(params.tokenIn).safeTransferFrom(
            msg.sender,
            address(this),
            params.amountIn
        );

        // Execute swap in separate function to reduce stack depth
        amountOut = _executeSwap(params);

        return amountOut;
    }

    // Helper function for executing swaps - reduces stack depth
    function _executeSwap(
        SwapParams calldata params
    ) internal returns (uint256 amountOut) {
        // Approve router to spend tokens
        IERC20(params.tokenIn).safeApprove(
            address(swapRouter),
            params.amountIn
        );

        // Execute swap
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
        emit Swapped(params.tokenIn, params.tokenOut, amountOut);

        // Reset approval
        IERC20(params.tokenIn).safeApprove(address(swapRouter), 0);

        return amountOut;
    }

    // --- Combined Token Management Functions (Owner Only) ---
    function manageToken(
        string memory operation,
        address token,
        uint256 amount,
        address payable recipient
    ) external payable nonReentrant onlyOwner {
        require(amount > 0, "Amount must be > 0");
        bytes32 opHash = keccak256(abi.encodePacked(operation));

        if (opHash == keccak256("DEPOSIT")) {
            _handleDeposit(token, amount);
        } else if (opHash == keccak256("WITHDRAW")) {
            _handleWithdrawal(token, amount, recipient);
        } else {
            revert("Invalid operation type");
        }
    }

    //  Helper function for handling deposits - reduces stack depth
    function _handleDeposit(address token, uint256 amount) internal {
        require(msg.sender == owner(), "Only owner can deposit");

        if (token == WETH9) {
            require(msg.value == amount, "ETH value mismatch");
            require(WETH9 != address(0), "WETH9 address not set");
            IWETH9(WETH9).deposit{value: amount}();
            emit TokenOperation("DEPOSIT", WETH9, msg.sender, amount);
        } else {
            require(msg.value == 0, "ETH sent for token deposit");
            IERC20(token).safeTransferFrom(msg.sender, address(this), amount);
            emit TokenOperation("DEPOSIT", token, msg.sender, amount);
        }
    }

    // Helper function for handling withdrawals - reduces stack depth
    function _handleWithdrawal(
        address token,
        uint256 amount,
        address payable recipient
    ) internal {
        require(recipient != address(0), "Invalid recipient");
        require(msg.value == 0, "ETH sent for withdrawal");

        if (token == WETH9) {
            require(WETH9 != address(0), "WETH9 address not set");
            uint256 balanceWETH = IERC20(WETH9).balanceOf(address(this));
            require(balanceWETH >= amount, "Insufficient WETH balance");
            IWETH9(WETH9).withdraw(amount);
            recipient.transfer(amount);
            emit TokenOperation("WITHDRAW", WETH9, recipient, amount);
        } else {
            uint256 balanceToken = IERC20(token).balanceOf(address(this));
            require(balanceToken >= amount, "Insufficient token balance");
            IERC20(token).safeTransfer(recipient, amount);
            emit TokenOperation("WITHDRAW", token, recipient, amount);
        }
    }

    // --- Payment Functions ---
    receive() external payable {}

    function refundETH() external payable onlyOwner {
        uint256 balance = address(this).balance;
        require(balance > 0, "No ETH to refund");
        payable(msg.sender).transfer(balance);
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
    ) external payable onlyOwner {
        require(WETH9 != address(0), "WETH9 not set");
        require(recipient != address(0), "Invalid recipient");
        uint256 balance = IWETH9(WETH9).balanceOf(address(this));
        require(balance >= amountMinimum, "Insufficient WETH");
        if (balance > 0) {
            IWETH9(WETH9).withdraw(balance);
            payable(recipient).transfer(balance);
        }
    }

    // --- View Functions ---
    function getTokenBalance(address token) external view returns (uint256) {
        return IERC20(token).balanceOf(address(this));
    }

    function getETHBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
