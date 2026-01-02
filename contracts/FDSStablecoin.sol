// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

contract FDSStablecoin is ERC20, Pausable, Ownable {
    using ECDSA for bytes32;

    // 감시자(Watchtower) 서버의 지갑 주소
    address public watchtower;
    
    // 재사용 공격 방지용 nonce (한 번 쓴 서명은 폐기)
    mapping(address => uint256) public nonces;

    event WatchtowerChanged(address indexed oldWatchtower, address indexed newWatchtower);
    event EmergencyPausedByWatchtower(address indexed triggerer, uint256 timestamp);

    constructor() ERC20("FDS Stablecoin", "FDS") Ownable(msg.sender) {
        _mint(msg.sender, 1000000 * 10 ** decimals());
    }

    // 1. 감시자 주소 설정 (Owner만 가능)
    function setWatchtower(address _watchtower) external onlyOwner {
        emit WatchtowerChanged(watchtower, _watchtower);
        watchtower = _watchtower;
    }

    // 2. 서명 기반 비상 정지 (누구나 호출 가능하지만, 유효한 서명이 있어야 함)
    // 파라미터: 서명(signature)
    function pauseByWatchtower(bytes calldata signature) external {
        require(watchtower != address(0), "Watchtower not set");
        require(!paused(), "Already paused");

        // 서명 검증을 위한 메시지 해시 생성
        // 내용: "EMERGENCY_PAUSE", 체인ID, 컨트랙트주소, 현재 nonce
        bytes32 structHash = keccak256(abi.encodePacked(
            "EMERGENCY_PAUSE", 
            block.chainid, 
            address(this), 
            nonces[watchtower]
        ));

        // 이더리움 서명 표준에 맞게 해시 변환
        bytes32 ethSignedMessageHash = MessageHashUtils.toEthSignedMessageHash(structHash);

        // 서명에서 주소 복원
        address signer = ECDSA.recover(ethSignedMessageHash, signature);

        // 서명한 사람이 진짜 Watchtower인지 확인
        require(signer == watchtower, "Invalid signature");

        // Nonce 증가 (이 서명은 이제 재사용 불가)
        nonces[watchtower]++;

        // 시스템 동결
        _pause();
        emit EmergencyPausedByWatchtower(msg.sender, block.timestamp);
    }

    // (기존) 관리자 수동 정지
    function circuitBreakerTrigger() external onlyOwner {
        _pause();
    }

    // (기존) 서비스 재개
    function resumeService() external onlyOwner {
        _unpause();
    }

    function _update(address from, address to, uint256 value) internal override whenNotPaused {
        super._update(from, to, value);
    }
}
