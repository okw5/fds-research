// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

// 1. 가짜 준비금 코인 (USDT)
contract MockUSDT is ERC20 {
    constructor() ERC20("Mock USDT", "mUSDT") {
        _mint(msg.sender, 100000000 * 10 ** 18); // 1억 개 발행
    }
}

// 2. 가짜 준비금 금고 (Vault)
contract MockVault {
    IERC20 public reserveToken;

    constructor(address _token) {
        reserveToken = IERC20(_token);
    }

    // [공격용] 누구나 금고의 돈을 빼갈 수 있는 취약점
    function exploitDrain(uint256 amount) external {
        reserveToken.transfer(msg.sender, amount);
    }
}

// 3. 가짜 오라클 (Chainlink 흉내)
contract MockOracle {
    uint256 public price = 1 ether; // 초기 가격 $1.00 (18 decimals)

    function getLatestPrice() external view returns (uint256) {
        return price;
    }
    
    // 가격 강제 변경 (테스트용)
    function setPrice(uint256 _price) external {
        price = _price;
    }
}

// 4. 가짜 거래소 (Uniswap Pool 흉내)
contract MockDEX {
    IERC20 public fdsToken;
    IERC20 public usdtToken;
    
    // 유동성 비율 (단순화된 AMM 모델: Price = reserveUSDT / reserveFDS)
    uint256 public reserveFDS;
    uint256 public reserveUSDT;

    constructor(address _fds, address _usdt) {
        fdsToken = IERC20(_fds);
        usdtToken = IERC20(_usdt);
    }

    // 유동성 공급 (초기 세팅용)
    function addLiquidity(uint256 fdsAmount, uint256 usdtAmount) external {
        fdsToken.transferFrom(msg.sender, address(this), fdsAmount);
        usdtToken.transferFrom(msg.sender, address(this), usdtAmount);
        reserveFDS += fdsAmount;
        reserveUSDT += usdtAmount;
    }

    // 현물 가격 조회 (Spot Price)
    function getSpotPrice() external view returns (uint256) {
        if (reserveFDS == 0) return 0;
        // Price = USDT / FDS * 1e18
        return (reserveUSDT * 1e18) / reserveFDS;
    }

    // [공격용] 플래시 론 덤핑 시뮬레이션
    // FDS를 대량으로 매도해서 가격을 폭락시키는 상황 연출
    function simulateDump(uint256 dumpAmount) external {
        // 실제 스왑 로직 대신, 비율만 망가뜨립니다.
        reserveFDS += dumpAmount;    // FDS가 시장에 쏟아져 나옴
        reserveUSDT -= (dumpAmount / 2); // USDT는 빠져나감 (가정)
    }
}
