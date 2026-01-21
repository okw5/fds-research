// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title FDSMicroToken
 * @dev 소액 결제용 토큰 (Micro-Payment Token)
 * - 특징:
 *   1. 100만 단위(Simulated KRW) 이하의 소액 거래만 허용
 *   2. 별도의 사전 심사 없이 자유롭게 전송 가능 (Low Friction)
 *   3. 사후 심사를 통해 이상 징후 발견 시 계정 차단(Blacklist) 가능
 */
contract FDSMicroToken is ERC20, Ownable {
    // 소액 결제 기준: 1,000,000 FDS (decimal 고려)
    // 1 FDS = 1 KRW (Simulated)
    // decimals = 18이라면 1,000,000 * 10^18
    uint256 public constant MICRO_CAP = 1_000_000 * 10**18;

    mapping(address => bool) private _blacklist;

    event Blacklisted(address indexed account);
    event UnBlacklisted(address indexed account);

    constructor() ERC20("FDS Micro Token", "FDS-m") Ownable(msg.sender) {
        // 초기 발행 (테스트용)
        _mint(msg.sender, 1_000_000_000 * 10**decimals());
    }

    // --- Blacklist Management ---
    function blacklistAccount(address account) external onlyOwner {
        _blacklist[account] = true;
        emit Blacklisted(account);
    }

    function unBlacklistAccount(address account) external onlyOwner {
        _blacklist[account] = false;
        emit UnBlacklisted(account);
    }

    function isBlacklisted(address account) public view returns (bool) {
        return _blacklist[account];
    }

    // --- Overrides ---

    function _update(address from, address to, uint256 value) internal override {
        // 1. 블랙리스트 체크
        if (_blacklist[from] || _blacklist[to]) {
            revert("Address is blacklisted");
        }

        // 2. 소액 결제 한도 체크 (Minting/Burning 제외하고 순수 이체 시 적용 가능하지만,
        // 여기서는 간단히 모든 이동에 대해 체크하거나, Minting은 예외처리)
        if (from != address(0) && to != address(0)) {
            if (value > MICRO_CAP) {
                revert("MicroToken: Transfer amount exceeds 1,000,000 limit");
            }
        }

        super._update(from, to, value);
    }

    /**
     * [테스트용] 누구나 토큰 발행 가능 (실험 편의성)
     */
    function exploitMint(uint256 amount) external {
        _mint(msg.sender, amount);
    }
}
