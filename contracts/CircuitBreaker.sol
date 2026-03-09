// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/**
 * @title CircuitBreaker
 * @dev 통합 Circuit Breaker — Watchtower 서명 기반 자동 방어
 *
 * 기존 FDSStablecoin.sol / FDSMacroToken.sol의 보안 로직을 통합:
 *   - ECDSA 서명 검증 기반 비상 정지
 *   - 주소 블랙리스트 (Micro 대응)
 *   - Timeout 기반 자동 복구
 *   - 상태 조회
 *
 * On-chain 방어 메커니즘:
 *   1) Macro: emergencyPause() → 전체/선택적 정지
 *   2) Micro: blacklistAddress() → 주소 차단
 *   3) Recovery: autoRecover() → 타임아웃 복구
 */
contract CircuitBreaker is Pausable, Ownable {
    using ECDSA for bytes32;

    // ── 상태 변수 ──
    address public watchtower;
    mapping(address => uint256) public nonces;
    mapping(address => bool) public blacklisted;

    // Timeout 자동 복구
    uint256 public pausedAt;
    uint256 public autoRecoverTimeout;

    // 통계
    uint256 public totalPauseCount;
    uint256 public totalBlacklistCount;
    uint256 public totalRecoverCount;

    // ── 이벤트 ──
    event WatchtowerChanged(address indexed oldWatchtower, address indexed newWatchtower);
    event EmergencyPaused(address indexed triggerer, string reason, uint256 timestamp);
    event AddressBlacklisted(address indexed target, address indexed triggerer, uint256 timestamp);
    event AddressUnblacklisted(address indexed target, uint256 timestamp);
    event AutoRecovered(uint256 timestamp, uint256 pauseDuration);
    event ManualRecovered(address indexed recoverer, uint256 timestamp);
    event TimeoutUpdated(uint256 oldTimeout, uint256 newTimeout);

    // ── 생성자 ──
    constructor(
        address _watchtower,
        uint256 _autoRecoverTimeout
    ) Ownable(msg.sender) {
        require(_watchtower != address(0), "Invalid watchtower address");
        watchtower = _watchtower;
        autoRecoverTimeout = _autoRecoverTimeout > 0 ? _autoRecoverTimeout : 1 hours;
        emit WatchtowerChanged(address(0), _watchtower);
    }

    // ── Modifier ──
    modifier notBlacklisted(address account) {
        require(!blacklisted[account], "Address is blacklisted");
        _;
    }

    // ══════════════════════════════════════════════════════════════════════
    // Macro 대응: 비상 정지
    // ══════════════════════════════════════════════════════════════════════

    /**
     * @notice Watchtower 서명 기반 비상 정지 (누구나 호출 가능, 서명 필수)
     * @param signature Watchtower가 발급한 ECDSA 서명
     *
     * 메시지 구조: keccak256("EMERGENCY_PAUSE", chainId, contractAddr, nonce)
     * Python 측: SignalSigner.sign_pause_signal()
     */
    function emergencyPause(bytes calldata signature) external {
        require(!paused(), "Already paused");
        require(watchtower != address(0), "Watchtower not set");

        bytes32 structHash = keccak256(abi.encodePacked(
            "EMERGENCY_PAUSE",
            block.chainid,
            address(this),
            nonces[watchtower]
        ));
        bytes32 ethSignedMessageHash = MessageHashUtils.toEthSignedMessageHash(structHash);
        address signer = ECDSA.recover(ethSignedMessageHash, signature);

        require(signer == watchtower, "Invalid watchtower signature");

        nonces[watchtower]++;
        pausedAt = block.timestamp;
        totalPauseCount++;
        _pause();

        emit EmergencyPaused(msg.sender, "watchtower_signal", block.timestamp);
    }

    /**
     * @notice Owner 직접 비상 정지 (서명 불필요)
     */
    function ownerPause() external onlyOwner {
        require(!paused(), "Already paused");
        pausedAt = block.timestamp;
        totalPauseCount++;
        _pause();
        emit EmergencyPaused(msg.sender, "owner_direct", block.timestamp);
    }

    // ══════════════════════════════════════════════════════════════════════
    // Micro 대응: 주소 블랙리스트
    // ══════════════════════════════════════════════════════════════════════

    /**
     * @notice 주소 블랙리스트 추가 (Owner만)
     * @param target 블랙리스트할 주소
     */
    function blacklistAddress(address target) external onlyOwner {
        require(target != address(0), "Cannot blacklist zero address");
        require(!blacklisted[target], "Already blacklisted");

        blacklisted[target] = true;
        totalBlacklistCount++;
        emit AddressBlacklisted(target, msg.sender, block.timestamp);
    }

    /**
     * @notice 블랙리스트 해제 (Owner만)
     * @param target 해제할 주소
     */
    function unblacklistAddress(address target) external onlyOwner {
        require(blacklisted[target], "Not blacklisted");
        blacklisted[target] = false;
        emit AddressUnblacklisted(target, block.timestamp);
    }

    // ══════════════════════════════════════════════════════════════════════
    // 복구 메커니즘
    // ══════════════════════════════════════════════════════════════════════

    /**
     * @notice Timeout 기반 자동 복구 (누구나 호출 가능)
     * pausedAt 이후 autoRecoverTimeout 경과 시 자동 해제
     */
    function autoRecover() external {
        require(paused(), "Not paused");
        require(
            block.timestamp >= pausedAt + autoRecoverTimeout,
            "Timeout not yet reached"
        );

        uint256 duration = block.timestamp - pausedAt;
        totalRecoverCount++;
        _unpause();

        emit AutoRecovered(block.timestamp, duration);
    }

    /**
     * @notice Owner 수동 복구
     */
    function manualRecover() external onlyOwner {
        require(paused(), "Not paused");
        totalRecoverCount++;
        _unpause();
        emit ManualRecovered(msg.sender, block.timestamp);
    }

    // ══════════════════════════════════════════════════════════════════════
    // 설정 변경
    // ══════════════════════════════════════════════════════════════════════

    function setWatchtower(address _watchtower) external onlyOwner {
        require(_watchtower != address(0), "Invalid watchtower");
        emit WatchtowerChanged(watchtower, _watchtower);
        watchtower = _watchtower;
    }

    function setAutoRecoverTimeout(uint256 _timeout) external onlyOwner {
        require(_timeout >= 5 minutes, "Timeout too short");
        emit TimeoutUpdated(autoRecoverTimeout, _timeout);
        autoRecoverTimeout = _timeout;
    }

    // ══════════════════════════════════════════════════════════════════════
    // 상태 조회
    // ══════════════════════════════════════════════════════════════════════

    /**
     * @notice 현재 시스템 상태 조회
     */
    function getStatus() external view returns (
        bool isPaused,
        uint256 pauseTimestamp,
        uint256 timeUntilAutoRecover,
        uint256 pauseCount,
        uint256 blacklistCount,
        uint256 recoverCount
    ) {
        isPaused = paused();
        pauseTimestamp = pausedAt;

        if (isPaused && block.timestamp < pausedAt + autoRecoverTimeout) {
            timeUntilAutoRecover = (pausedAt + autoRecoverTimeout) - block.timestamp;
        } else {
            timeUntilAutoRecover = 0;
        }

        pauseCount = totalPauseCount;
        blacklistCount = totalBlacklistCount;
        recoverCount = totalRecoverCount;
    }

    /**
     * @notice 특정 주소의 블랙리스트 여부 확인
     */
    function isBlacklisted(address account) external view returns (bool) {
        return blacklisted[account];
    }
}
