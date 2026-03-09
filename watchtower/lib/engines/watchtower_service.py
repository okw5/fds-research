"""
WatchtowerService — 전체 탐지 파이프라인 오케스트레이터

파이프라인:
  1. 트랜잭션 이벤트 수신 (process_transaction)
  2. 3개 엔진 분석 (SequenceAnomaly + FlashLoanRule + HoustonLite)
  3. ThreatAggregator로 결과 집계
  4. 위협 수준에 따라 대응 액션 결정
  5. SignalSigner로 서명 생성
  6. On-chain Circuit Breaker TX 전송

사용법:
    service = WatchtowerService(web3, contracts, WATCHTOWER_PK)
    signal = service.process_transaction(tx_data)
"""

import time
import logging
from typing import Dict, Any, List, Optional, Callable
from web3 import Web3

from .base import ThreatSignal, ThreatLevel
from .sequence_anomaly import SequenceAnomalyEngine
from .flash_loan_rule import FlashLoanRuleEngine
from .houston_lite import HoustonLiteInvariantChecker
from .aggregator import ThreatAggregator
from .signal_signer import SignalSigner

logger = logging.getLogger(__name__)


class WatchtowerService:
    """
    Off-chain Watchtower 오케스트레이터.

    3개 이종 탐지 엔진의 결과를 집계하고,
    위협 수준에 따라 on-chain circuit breaker를 작동시킵니다.
    """

    def __init__(
        self,
        web3: Web3,
        contracts: Optional[Dict[str, Any]] = None,
        private_key: Optional[str] = None,
        engine_config: Optional[Dict[str, Any]] = None,
        aggregator_weights: Optional[Dict[str, float]] = None,
    ):
        """
        Args:
            web3: Web3 인스턴스
            contracts: 컨트랙트 딕셔너리 (load_contracts() 반환값)
            private_key: Watchtower private key
            engine_config: 엔진별 설정 오버라이드
            aggregator_weights: 집계기 가중치 오버라이드
        """
        self.w3 = web3
        self.contracts = contracts or {}
        engine_config = engine_config or {}

        # ── 엔진 초기화 ──
        self.engines = [
            SequenceAnomalyEngine(config=engine_config.get("sequence", None)),
            FlashLoanRuleEngine(config=engine_config.get("flash_loan", None)),
            HoustonLiteInvariantChecker(config=engine_config.get("houston", None)),
        ]

        # ── 집계기 ──
        self.aggregator = ThreatAggregator(weights=aggregator_weights)

        # ── 서명기 (private_key가 있을 때만) ──
        self.signer: Optional[SignalSigner] = None
        if private_key:
            self.signer = SignalSigner(private_key, web3)

        # ── 이벤트 로그 ──
        self.event_log: List[Dict[str, Any]] = []
        self._on_signal_callbacks: List[Callable[[ThreatSignal], None]] = []

    # ------------------------------------------------------------------
    # 메인 파이프라인
    # ------------------------------------------------------------------

    def process_transaction(self, tx_data: Dict[str, Any]) -> ThreatSignal:
        """
        메인 탐지 파이프라인.

        Args:
            tx_data: 트랜잭션 데이터 딕셔너리
                필수 키: from, to, amount, type
                선택 키: call_sequence, state_before, state_after

        Returns:
            ThreatSignal 인스턴스 (JSON 직렬화 가능)
        """
        pipeline_start = time.time()

        # 1) 3개 엔진 분석
        results = []
        for engine in self.engines:
            try:
                result = engine.analyze(tx_data)
                results.append(result)
            except Exception as e:
                logger.error(f"Engine {engine.name} failed: {e}")
                # 실패한 엔진은 NONE 결과로 대체
                from .base import EngineResult
                results.append(EngineResult(
                    engine_name=engine.name,
                    threat_level=ThreatLevel.NONE,
                    confidence=0.0,
                    details={"error": str(e)},
                    latency_ms=0.0,
                ))

        # 2) 결과 집계
        signal = self.aggregator.aggregate(results, tx_data)

        # 3) 대응 실행 (signer와 contracts가 있을 때만)
        if signal.recommended_action != "none" and self.signer and self.contracts:
            response = self._execute_response(signal, tx_data)
            signal.response = response

        # 4) 로그 기록
        pipeline_latency = (time.time() - pipeline_start) * 1000
        log_entry = signal.to_dict()
        log_entry["pipeline_latency_ms"] = round(pipeline_latency, 2)
        self.event_log.append(log_entry)

        # 5) 콜백 알림
        for cb in self._on_signal_callbacks:
            try:
                cb(signal)
            except Exception as e:
                logger.error(f"Callback error: {e}")

        logger.info(
            f"[Watchtower] TX processed: threat={signal.threat_level.value}, "
            f"score={signal.final_score:.3f}, action={signal.recommended_action}, "
            f"latency={pipeline_latency:.1f}ms"
        )

        return signal

    # ------------------------------------------------------------------
    # 대응 실행
    # ------------------------------------------------------------------

    def _execute_response(
        self, signal: ThreatSignal, tx_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """on-chain 대응 실행. 실패 시에도 signal은 반환됨."""
        response: Dict[str, Any] = {
            "action_taken": signal.recommended_action,
            "tx_hash": None,
            "gas_used": 0,
            "response_latency_ms": 0.0,
            "success": False,
        }

        start = time.time()

        try:
            if signal.recommended_action in ("pause_macro", "pause_all"):
                receipt = self._send_pause_tx()
                response["tx_hash"] = receipt.transactionHash.hex()
                response["gas_used"] = receipt.gasUsed
                response["success"] = receipt.status == 1

            elif signal.recommended_action == "blacklist_address":
                target = tx_data.get("from", "0x0")
                receipt = self._send_blacklist_tx(target)
                response["tx_hash"] = receipt.transactionHash.hex()
                response["gas_used"] = receipt.gasUsed
                response["success"] = receipt.status == 1

            elif signal.recommended_action == "alert_only":
                response["success"] = True  # 경고만 — TX 불필요

        except Exception as e:
            logger.error(f"Response execution failed: {e}")
            response["error"] = str(e)

        response["response_latency_ms"] = round(
            (time.time() - start) * 1000, 2
        )
        return response

    def _send_pause_tx(self):
        """ECDSA 서명 기반 pause TX 전송"""
        fds = self.contracts.get("FDS")
        if not fds or not self.signer:
            raise RuntimeError("FDS contract or signer not available")

        addrs = self.contracts.get("ADDRS", {})
        contract_addr = addrs.get("FDS", "0x0")

        nonce_val = fds.functions.nonces(self.signer.address).call()
        sig = self.signer.sign_pause_signal(contract_addr, nonce_val)

        tx = fds.functions.pauseByWatchtower(sig).build_transaction({
            "from": self.signer.address,
            "nonce": self.w3.eth.get_transaction_count(self.signer.address),
            "gas": 300_000,
            "gasPrice": int(self.w3.eth.gas_price * 1.5),
        })

        signed_tx = self.w3.eth.account.sign_transaction(
            tx, private_key=self.signer.private_key
        )
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def _send_blacklist_tx(self, target_address: str):
        """블랙리스트 TX 전송 (owner 권한)"""
        fds = self.contracts.get("FDS")
        if not fds or not self.signer:
            raise RuntimeError("FDS contract or signer not available")

        tx = fds.functions.blacklistAccount(target_address).build_transaction({
            "from": self.signer.address,
            "nonce": self.w3.eth.get_transaction_count(self.signer.address),
            "gas": 200_000,
            "gasPrice": int(self.w3.eth.gas_price * 1.2),
        })

        signed_tx = self.w3.eth.account.sign_transaction(
            tx, private_key=self.signer.private_key
        )
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    def on_signal(self, callback: Callable[[ThreatSignal], None]):
        """시그널 발생 시 콜백 등록 (UI 업데이트 등에 활용)"""
        self._on_signal_callbacks.append(callback)

    def get_event_log(self, last_n: Optional[int] = None) -> List[Dict]:
        """이벤트 로그 조회"""
        if last_n:
            return self.event_log[-last_n:]
        return list(self.event_log)

    def get_engine_summary(self) -> List[Dict[str, Any]]:
        """모든 엔진의 메타 정보 + 통계 반환"""
        return [
            {**engine.get_engine_info(), **engine.get_stats()}
            for engine in self.engines
        ]

    def reset(self):
        """모든 엔진 상태 및 로그 초기화"""
        for engine in self.engines:
            if hasattr(engine, 'reset_history'):
                engine.reset_history()
        self.event_log.clear()
