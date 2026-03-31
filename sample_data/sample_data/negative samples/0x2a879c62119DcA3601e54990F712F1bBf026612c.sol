// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.13;

interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
}

contract BalanceChecker {
    // Function to check the token balances for a list of addresses
    function checkBalances(address[] calldata addresses, address tokenAddress) external view returns (uint256[] memory) {
        uint256[] memory balances = new uint256[](addresses.length);
        IERC20 token = IERC20(tokenAddress);

        for (uint i = 0; i < addresses.length; i++) {
            balances[i] = token.balanceOf(addresses[i]);
        }

        return balances;
    }
}