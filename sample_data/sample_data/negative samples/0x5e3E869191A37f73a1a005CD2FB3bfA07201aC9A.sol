// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface KeroppiPlatform {
    function deposit() external payable;
    function withdraw(uint256 amount) external;
    function getKeroppi() external view returns (uint256);
}

contract KeroppiGeneration {
    address public owner;
    KeroppiPlatform public platform;
    
    constructor(address _platform) {
        owner = msg.sender;
        platform = KeroppiPlatform(_platform);
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

    function getGeneratedKeroppi() external view returns (uint256) {
        return platform.getKeroppi();
    }
}