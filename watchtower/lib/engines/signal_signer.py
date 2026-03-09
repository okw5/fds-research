"""
SignalSigner — ThreatSignal → ECDSA 서명 생성

기존 utils.py의 sign_macro_transfer(), send_defense_tx()를 범용화한 모듈.
Watchtower의 private key로 on-chain circuit breaker 호출에 필요한 서명을 생성합니다.

지원 서명 유형:
  - EMERGENCY_PAUSE: 전체/선택적 정지
  - BLACKLIST: 주소 블랙리스트
  - MACRO_TRANSFER: Macro 토큰 이체 승인
"""

from typing import Optional
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct


class SignalSigner:
    """
    ECDSA 서명 생성기.

    기존 utils.py와의 관계:
      - sign_macro_transfer() → sign_macro_transfer() 메서드로 통합
      - send_defense_tx()의 서명 부분 → sign_pause_signal() 으로 분리
      - TX 전송 부분은 WatchtowerService에서 담당
    """

    def __init__(self, private_key: str, web3: Web3):
        """
        Args:
            private_key: Watchtower 계정의 private key (hex string)
            web3: Web3 인스턴스
        """
        self.private_key = private_key
        self.w3 = web3
        self.account = Account.from_key(private_key)

    @property
    def address(self) -> str:
        """Watchtower 주소"""
        return self.account.address

    def sign_pause_signal(
        self,
        contract_address: str,
        nonce: int,
    ) -> bytes:
        """
        EMERGENCY_PAUSE 서명 생성.
        FDSStablecoin.pauseByWatchtower() / CircuitBreaker.emergencyPause() 호출용.

        Solidity 측 검증:
            keccak256(abi.encodePacked("EMERGENCY_PAUSE", chainId, contractAddr, nonce))

        Args:
            contract_address: 대상 컨트랙트 주소
            nonce: Watchtower의 현재 nonce

        Returns:
            65-byte ECDSA signature (r + s + v)
        """
        msg_hash = self.w3.solidity_keccak(
            ['string', 'uint256', 'address', 'uint256'],
            ["EMERGENCY_PAUSE", self.w3.eth.chain_id, contract_address, nonce],
        )
        message = encode_defunct(hexstr=msg_hash.hex())
        signed = self.w3.eth.account.sign_message(
            message, private_key=self.private_key
        )
        return signed.signature

    def sign_blacklist_signal(
        self,
        contract_address: str,
        target_address: str,
        nonce: int,
    ) -> bytes:
        """
        BLACKLIST 서명 생성.
        CircuitBreaker.blacklistByWatchtower() 호출용 (서명 기반 블랙리스트).

        Args:
            contract_address: 대상 컨트랙트 주소
            target_address: 블랙리스트할 주소
            nonce: Watchtower의 현재 nonce

        Returns:
            65-byte ECDSA signature
        """
        msg_hash = self.w3.solidity_keccak(
            ['string', 'uint256', 'address', 'address', 'uint256'],
            [
                "BLACKLIST",
                self.w3.eth.chain_id,
                contract_address,
                target_address,
                nonce,
            ],
        )
        message = encode_defunct(hexstr=msg_hash.hex())
        signed = self.w3.eth.account.sign_message(
            message, private_key=self.private_key
        )
        return signed.signature

    def sign_macro_transfer(
        self,
        contract_address: str,
        from_address: str,
        to_address: str,
        amount: int,
        nonce: int,
    ) -> bytes:
        """
        MACRO_TRANSFER 서명 생성.
        FDSMacroToken.transferWithSignal() 호출용.

        기존 utils.py sign_macro_transfer()와 동일한 로직.

        Args:
            contract_address: FDSMacroToken 컨트랙트 주소
            from_address: 발신자
            to_address: 수신자
            amount: 이체 금액 (wei)
            nonce: 발신자의 현재 nonce

        Returns:
            65-byte ECDSA signature
        """
        msg_hash = self.w3.solidity_keccak(
            ['string', 'uint256', 'address', 'address', 'address', 'uint256', 'uint256'],
            [
                "MACRO_TRANSFER",
                self.w3.eth.chain_id,
                contract_address,
                from_address,
                to_address,
                amount,
                nonce,
            ],
        )
        message = encode_defunct(hexstr=msg_hash.hex())
        signed = self.w3.eth.account.sign_message(
            message, private_key=self.private_key
        )
        return signed.signature
