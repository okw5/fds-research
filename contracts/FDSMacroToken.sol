// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/**
 * @title FDSMacroToken
 * @dev 거액 결제용 토큰 (Macro-Payment Token)
 * - 특징:
 *   1. 100만 단위 초과의 거액 거래 전용 (권장)
 *   2. [Pre-Audit] 사전 심사(서명)가 있어야만 이체 가능
 *   3. [Circuit Breaker] 사전 심사를 통과했더라도, 
 *      단기간 내 과도한 물량 이동 시 시스템 전체 자동 정지 (서버 키 탈취/오작동 대비)
 */
contract FDSMacroToken is ERC20, Pausable, Ownable {
    using ECDSA for bytes32;

    // 감시자(Watchtower) 서버 주소 (서명 발급 주체)
    address public watchtower;
    
    // 서명 재사용 방지용
    mapping(address => uint256) public nonces;

    // --- Rate Limiting (Circuit Breaker) ---
    uint256 public constant RATE_LIMIT_PERIOD = 1 hours;
    uint256 public mintLimitPerPeriod; 
    
    uint256 public currentPeriodEnd;
    uint256 public currentPeriodVolume; // Mint뿐만 아니라 Transfer 양도 포함할지 결정. 여기서는 "유출량" 제어로 Transfer 포함.

    event WatchtowerChanged(address indexed oldWatchtower, address indexed newWatchtower);
    event CircuitBreakerTriggered(string reason, uint256 timestamp);
    event TransferWithSignal(address indexed from, address indexed to, uint256 value, uint256 nonce);

    constructor() ERC20("FDS Macro Token", "FDS-M") Ownable(msg.sender) {
        // 초기 발행
        _mint(msg.sender, 1_000_000_000 * 10**decimals());

        // 초기 Rate Limit 설정 (예: 1시간에 10억 토큰 허용 - 초기엔 넉넉하게)
        mintLimitPerPeriod = 1_000_000_000 * 10**decimals();
        currentPeriodEnd = block.timestamp + RATE_LIMIT_PERIOD;
    }

    function setWatchtower(address _watchtower) external onlyOwner {
        watchtower = _watchtower;
        emit WatchtowerChanged(address(0), _watchtower);
    }

    /**
     * @dev 일반 transfer는 사용 불가. 반드시 서명이 포함된 transferWithSignal 사용 강제.
     */
    function transfer(address to, uint256 value) public override returns (bool) {
        revert("FDSMacroToken: Use transferWithSignal instead");
    }

    function transferFrom(address from, address to, uint256 value) public override returns (bool) {
        revert("FDSMacroToken: Use transferWithSignal instead (checking allowance not implemented for demo)");
    }

    /**
     * @dev 사전 심사(Signature) 기반 이체 함수
     * @param to 받는 사람
     * @param amount 금액
     * @param signature Watchtower가 발급한 서명 (keccak256("MACRO_TRANSFER", chainId, from, to, amount, nonce))
     */
    function transferWithSignal(address to, uint256 amount, bytes calldata signature) external whenNotPaused returns (bool) {
        address from = msg.sender;
        require(watchtower != address(0), "Watchtower not set");

        // 1. 서명 검증
        bytes32 structHash = keccak256(abi.encodePacked(
            "MACRO_TRANSFER",
            block.chainid,
            address(this),
            from,
            to,
            amount,
            nonces[from]
        ));
        bytes32 ethSignedMessageHash = MessageHashUtils.toEthSignedMessageHash(structHash);
        address signer = ECDSA.recover(ethSignedMessageHash, signature);

        require(signer == watchtower, "Invalid signature from Watchtower");

        // 2. Nonce 증가
        nonces[from]++;

        // 3. 서킷 브레이커 체크 (총량 제한)
        _checkVolumeLimit(amount);

        // 4. 실제 이체 수행
        _transfer(from, to, amount);
        
        emit TransferWithSignal(from, to, amount, nonces[from]-1);
        return true;
    }

    // 내부 함수: 총량 제한 체크
    function _checkVolumeLimit(uint256 amount) internal {
        if (block.timestamp > currentPeriodEnd) {
            currentPeriodEnd = block.timestamp + RATE_LIMIT_PERIOD;
            currentPeriodVolume = 0;
        }

        currentPeriodVolume += amount;

        if (currentPeriodVolume > mintLimitPerPeriod) {
            _pause();
            emit CircuitBreakerTriggered("Volume Limit Exceeded", block.timestamp);
            revert("Rate limit exceeded: System Paused");
        }
    }

    // Owner는 강제로 Pause/Unpause 가능
    function emergencyPause() external onlyOwner {
        _pause();
    }

    function resumeService() external onlyOwner {
        _unpause();
        currentPeriodVolume = 0;
    }

    /**
     * [테스트용] 누구나 토큰 발행 가능
     */
    function exploitMint(uint256 amount) external {
        _mint(msg.sender, amount);
    }
}
