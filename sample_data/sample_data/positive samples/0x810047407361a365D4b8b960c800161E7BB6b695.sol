// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface IYieldPlatform {
    function deposit() external payable;
    function withdraw(uint256 amount) external;
    function getYield() external view returns (uint256);
}

contract YieldGeneration {
    address public owner;
    IYieldPlatform public platform;
    
    constructor(address _platform) {
        owner = msg.sender;
        platform = IYieldPlatform(_platform);
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Not the contract owner");
        _;
    }

    function invest() external payable onlyOwner {
        require(msg.value > 0, "Investment must be greater than zero");
        platform.deposit{ value: msg.value }();
    }

    function divest(uint256 amount) external onlyOwner {
        platform.withdraw(amount);
    }

    function getGeneratedYield() external view returns (uint256) {
        return platform.getYield();
    }
}