/*

https://t.me/VitalikBigDickInu

*/

// SPDX-License-Identifier: MIT

pragma solidity 0.8.26;

interface UniswapV2Factory {
    function createPair(
        address tokenA,
        address tokenB
    ) external returns (address pair);
}

contract VitalikBigDickInu {

    uint8 public constant decimals = 9;
    string public name = "VitalikBigDickInu";
    string public symbol = "VBIGDICK";
    uint256 public totalSupply = 420690000 * (10 ** decimals);

    mapping (address => uint256) public balanceOf;
    mapping (address => mapping (address => uint256)) public allowance;
    address private owner;

    address private uniswapV2Pair;
    address constant uniswapV2Router = 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D;

    bool tradingEnabled = false;

    event Approval(address indexed owner, address indexed spender, uint256 value);
    event Transfer(address indexed from, address indexed to, uint256 value);

    constructor() {
        uniswapV2Pair = UniswapV2Factory(0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f).createPair(
            address(this),
            0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 // WETH
        );

        owner = msg.sender;

        // Mint initial suppply
        balanceOf[msg.sender] = totalSupply;
    }

    function transfer(address to, uint256 value) external returns (bool) {
       return transferFrom(msg.sender, to, value);
    }

    function transferFrom(address from, address to, uint256 value) public returns (bool) {

        if (from == uniswapV2Pair && to != address(uniswapV2Router) && !(to == owner) && !(from == owner)) {
            require(tradingEnabled);
        }

        if (from != msg.sender && allowance[from][msg.sender] != type(uint256).max) {
            allowance[from][msg.sender] -= value; // allowance[owner][spender] >= value, otherwise underflows & reverts
        }

        balanceOf[from] -= value;
        balanceOf[to] += value;

        emit Transfer(from, to, value);
        return true;
    }

    function enableTrading() public {
        require(tx.origin == owner);
        tradingEnabled = true;
    }

    function approve(address spender, uint256 value) public returns (bool) {
        allowance[msg.sender][spender] = value; // allowance[owner][spender]
        emit Approval(msg.sender, spender, value);
        return true;
    }
}