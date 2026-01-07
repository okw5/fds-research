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

    // --- On-chain Backstop: Rate Limiting ---
    uint256 public constant RATE_LIMIT_PERIOD = 1 hours;
    uint256 public mintLimitPerPeriod; // 기간당 발행 한도
    
    uint256 public currentPeriodEnd;
    uint256 public currentPeriodMintAmount;

    event WatchtowerChanged(address indexed oldWatchtower, address indexed newWatchtower);
    event EmergencyPausedByWatchtower(address indexed triggerer, uint256 timestamp);
    event RateLimitAttributesChanged(uint256 newLimit);
    event CircuitBreakerTriggered(string reason, uint256 timestamp);

    constructor() ERC20("FDS Stablecoin", "FDS") Ownable(msg.sender) {
        // 초기 설정: 총 발행량의 50%를 시간당 한도로 설정 (예지)
        mintLimitPerPeriod = 500000 * 10 ** decimals();
        currentPeriodEnd = block.timestamp + RATE_LIMIT_PERIOD;

        // 초기 발행은 Rate Limit의 영향을 받지 않도록 예외 처리하거나,
        // _update에서 생성자 실행 중임을 감지해야 함.
        // 가장 간단한 방법: 초기 발행분은 currentPeriodMintAmount에 누적하되,
        // 한도 체크 시점보다 limit 설정을 나중에 하거나,
        // 혹은 생성자에서는 revert 시키지 않도록 로직 수정.
        
        // 여기서는 Limit을 아주 크게 잡고 발행 후, 다시 설정하는 방식을 사용.
        mintLimitPerPeriod = type(uint256).max; 
        _mint(msg.sender, 1000000 * 10 ** decimals());
        
        // 실제 운영 수치로 재설정
        mintLimitPerPeriod = 500000 * 10 ** decimals();
        // 초기 발행량은 카운트에서 제외할지, 포함할지 결정.
        // 포함한다면 이미 한도 초과 상태로 시작하므로, 제외하는 것이 맞음 (Reset).
        currentPeriodMintAmount = 0; 
    }

    // 1. 감시자 주소 설정 (Owner만 가능)
    function setWatchtower(address _watchtower) external onlyOwner {
        emit WatchtowerChanged(watchtower, _watchtower);
        watchtower = _watchtower;
    }

    // Rate Limit 설정 변경
    function setRateLimit(uint256 _newLimit) external onlyOwner {
        mintLimitPerPeriod = _newLimit;
        emit RateLimitAttributesChanged(_newLimit);
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

    // Internal Update 함수 오버라이드 (Pausable + Rate Limit 적용)
    function _update(address from, address to, uint256 value) internal override whenNotPaused {
        // Minting (from == 0) 발생 시 Rate Limit 체크
        if (from == address(0)) {
            _checkMintLimit(value);
        }
        super._update(from, to, value);
    }

    // Rate Limit & Auto Circuit Breaker 로직
    function _checkMintLimit(uint256 amount) internal {
        // 기간 경과 시 리셋
        if (block.timestamp > currentPeriodEnd) {
            currentPeriodEnd = block.timestamp + RATE_LIMIT_PERIOD;
            currentPeriodMintAmount = 0;
        }

        currentPeriodMintAmount += amount;

        // 한도 초과 시 즉시 차단 (Auto Circuit Breaker)
        if (currentPeriodMintAmount > mintLimitPerPeriod) {
            _pause(); // 시스템 자동 정지
            emit CircuitBreakerTriggered("Mint Limit Exceeded", block.timestamp);
            revert("Rate limit exceeded: System Paused");
        }
    }
	
	/**
     * [테스트용 취약점] 무한 발행 공격 시뮬레이션 함수
     * 누구나 호출해서 마음대로 토큰을 찍어낼 수 있습니다.
     */
	function exploitMint(uint256 amount) external {
        _mint(msg.sender, amount);
    }
}
