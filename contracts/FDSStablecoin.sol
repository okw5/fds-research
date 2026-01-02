// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract FDSStablecoin is ERC20, Pausable, Ownable {
    // 생성자: 토큰 이름과 심볼 설정, 초기 발행량 100만 개
    constructor() ERC20("FDS Stablecoin", "FDS") Ownable(msg.sender) {
        _mint(msg.sender, 1000000 * 10 ** decimals());
    }

    /**
     * @dev [서킷 브레이커 핵심 기능]
     * Watchtower(감시자)가 해킹을 감지하면 이 함수를 호출해 모든 거래를 얼립니다.
     */
    function circuitBreakerTrigger() external onlyOwner {
        _pause();
    }

    /**
     * @dev 상황 종료 후 다시 가동하는 함수
     */
    function resumeService() external onlyOwner {
        _unpause();
    }

    /**
     * @dev 토큰을 전송하기 전에 항상 체크하는 내부 함수 (OpenZeppelin v5 표준)
     * Paused 상태이면 전송이 거부됩니다.
     */
    function _update(address from, address to, uint256 value) internal override whenNotPaused {
        super._update(from, to, value);
    }
}
