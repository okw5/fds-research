// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TokenVesting {
    address public owner;

    // Struct representing a vesting schedule
    struct VestingSchedule {
        uint256 totalAmount;      // Total amount of tokens to vest
        uint256 startTime;        // Timestamp when vesting starts
        uint256 duration;         // Duration of vesting in seconds
        uint256 amountWithdrawn;  // Amount of tokens already withdrawn
    }

    // Mapping from beneficiary to token address to their vesting schedule
    mapping(address => mapping(address => VestingSchedule)) public vestings;
    // Mapping to keep track of total tokens vested per token
    mapping(address => uint256) public totalVestedPerToken;

    // Reentrancy guard
    bool internal locked;

    // Events
    event VestingStarted(address indexed beneficiary, address indexed token, uint256 totalAmount, uint256 duration);
    event TokensWithdrawn(address indexed beneficiary, address indexed token, uint256 amount);
    event VestingCanceled(address indexed beneficiary, address indexed token, uint256 remainingAmount);
    event FundsRetracted(address indexed token, uint256 amount, address indexed destination);

    // Modifiers
    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    modifier nonReentrant() {
        require(!locked, "ReentrancyGuard: reentrant call");
        locked = true;
        _;
        locked = false;
    }

    constructor() {
        owner = msg.sender;
    }

    /**
     * @dev Starts a new vesting schedule for a beneficiary.
     * @param beneficiary Address of the beneficiary
     * @param token Address of the ERC20 token
     * @param totalAmount Total amount of tokens to vest
     * @param duration Duration of the vesting in seconds (e.g., 86400 for one day)
     *
     * Note: Duration should be specified in seconds.
     */
    function startVesting(
        address beneficiary,
        address token,
        uint256 totalAmount,
        uint256 duration
    ) external onlyOwner {
        require(duration > 0, "Duration must be > 0");
        require(totalAmount > 0, "Total amount must be > 0");

        // Calculate available tokens
        uint256 availableTokens = IERC20(token).balanceOf(address(this)) - totalVestedPerToken[token];
        require(availableTokens >= totalAmount, "Not enough tokens in contract");

        VestingSchedule storage schedule = vestings[beneficiary][token];
        require(schedule.totalAmount == 0, "Vesting already exists for this beneficiary and token");

        schedule.totalAmount = totalAmount;
        schedule.startTime = block.timestamp;
        schedule.duration = duration;
        schedule.amountWithdrawn = 0;

        totalVestedPerToken[token] += totalAmount;

        emit VestingStarted(beneficiary, token, totalAmount, duration);
    }

    /**
     * @dev Allows a beneficiary to withdraw their vested tokens.
     * @param token Address of the ERC20 token
     */
    function withdrawTokens(address token) external nonReentrant {
        VestingSchedule storage schedule = vestings[msg.sender][token];
        require(schedule.totalAmount > 0, "No vesting schedule");

        uint256 vestedAmount;
        if (block.timestamp >= schedule.startTime + schedule.duration) {
            vestedAmount = schedule.totalAmount;
        } else if (block.timestamp < schedule.startTime) {
            vestedAmount = 0;
        } else {
            vestedAmount = (schedule.totalAmount * (block.timestamp - schedule.startTime)) / schedule.duration;
        }

        uint256 withdrawableAmount = vestedAmount - schedule.amountWithdrawn;
        require(withdrawableAmount > 0, "No tokens to withdraw");

        schedule.amountWithdrawn += withdrawableAmount;

        require(IERC20(token).transfer(msg.sender, withdrawableAmount), "Token transfer failed");

        emit TokensWithdrawn(msg.sender, token, withdrawableAmount);
    }

    /**
     * @dev Retrieves vesting information for a beneficiary.
     * @param beneficiary Address of the beneficiary
     * @param token Address of the ERC20 token
     * @return withdrawableTokens Amount of tokens currently available for withdrawal
     * @return timeLeft Time left in seconds for the vesting to complete
     */
    function getVestingInfo(address beneficiary, address token) external view returns (uint256 withdrawableTokens, uint256 timeLeft) {
        VestingSchedule memory schedule = vestings[beneficiary][token];
        require(schedule.totalAmount > 0, "No vesting schedule");

        uint256 vestedAmount;
        if (block.timestamp >= schedule.startTime + schedule.duration) {
            vestedAmount = schedule.totalAmount;
            timeLeft = 0;
        } else if (block.timestamp < schedule.startTime) {
            vestedAmount = 0;
            timeLeft = schedule.startTime + schedule.duration - block.timestamp;
        } else {
            vestedAmount = (schedule.totalAmount * (block.timestamp - schedule.startTime)) / schedule.duration;
            timeLeft = schedule.startTime + schedule.duration - block.timestamp;
        }

        withdrawableTokens = vestedAmount - schedule.amountWithdrawn;
    }

    /**
     * @dev Allows the owner to retract unvested tokens from the contract.
     * @param token Address of the ERC20 token
     * @param amount Amount of tokens to retract
     * @param destination Address where the tokens will be sent
     */
    function retractFunds(address token, uint256 amount, address destination) external onlyOwner nonReentrant {
        uint256 availableTokens = IERC20(token).balanceOf(address(this)) - totalVestedPerToken[token];
        require(availableTokens >= amount, "Not enough unvested tokens");

        require(IERC20(token).transfer(destination, amount), "Token transfer failed");

        emit FundsRetracted(token, amount, destination);
    }

    /**
     * @dev Allows the owner to cancel a beneficiary's vesting schedule.
     * @param beneficiary Address of the beneficiary
     * @param token Address of the ERC20 token
     */
    function cancelVesting(address beneficiary, address token) external onlyOwner {
        VestingSchedule storage schedule = vestings[beneficiary][token];
        require(schedule.totalAmount > 0, "No vesting schedule");

        uint256 remainingAmount = schedule.totalAmount - schedule.amountWithdrawn;

        totalVestedPerToken[token] -= remainingAmount;

        delete vestings[beneficiary][token];

        emit VestingCanceled(beneficiary, token, remainingAmount);
    }

    // Prevent the contract from receiving ETH
    receive() external payable {
        revert("Contract does not accept ETH");
    }

    fallback() external payable {
        revert("Contract does not accept ETH");
    }
}

// Minimal IERC20 interface
interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address recipient, uint256 amount) external returns (bool);
}