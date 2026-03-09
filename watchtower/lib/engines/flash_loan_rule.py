"""
엔진2: FlashLoanRuleEngine — FlashGuard 참조 공격 시퀀스 규칙 엔진
[LITE] 실제 CNN-LSTM 시계열 모델 제외, 규칙 기반 시퀀스 매칭 구현

논문 참조: "Adapted from FlashGuard's attack signature methodology"
실제 연동 지점: _check_time_series_anomaly()에 CNN-LSTM 모델 추가

FlashGuard 핵심 메커니즘 (참조용):
  1. 멤풀 모니터링 → pending TX의 internal call 시퀀스 추출
  2. 함수 시그니처 패턴 매칭 (borrow→swap→exploit→repay)
  3. 공격 탐지 시 dusting counter-transaction 발송
  → 본 구현에서는 1·3을 제외하고 2번의 패턴 매칭만 수행
"""

import time
from typing import Dict, Any, List, Optional, Tuple
from .base import EngineBase, EngineResult, ThreatLevel


# ---------------------------------------------------------------------------
# 알려진 공격 패턴 사전 (FlashGuard 참조)
# ---------------------------------------------------------------------------
ATTACK_PATTERNS: Dict[str, Dict[str, Any]] = {
    "flash_loan_standard": {
        "sequence": ["flashloan", "swap", "manipulate", "repay"],
        "description": "Standard flash loan attack: borrow → swap → manipulate → repay",
        "severity": ThreatLevel.CRITICAL,
        "min_amount": 100_000,
    },
    "flash_loan_simple": {
        "sequence": ["flashloan", "repay"],
        "description": "Simple flash loan with suspicious repay pattern",
        "severity": ThreatLevel.MEDIUM,
        "min_amount": 50_000,
    },
    "reentrancy": {
        "sequence": ["withdraw", "fallback", "withdraw"],
        "description": "Reentrancy attack: recursive withdraw via fallback",
        "severity": ThreatLevel.CRITICAL,
        "min_amount": 0,
    },
    "infinite_mint": {
        "sequence": ["mint", "mint", "transfer"],
        "description": "Repeated unauthorized minting followed by transfer",
        "severity": ThreatLevel.CRITICAL,
        "min_amount": 10_000,
    },
    "infinite_mint_single": {
        "sequence": ["mint", "transfer"],
        "description": "Single large unauthorized mint + transfer",
        "severity": ThreatLevel.HIGH,
        "min_amount": 100_000,
    },
    "reserve_drain": {
        "sequence": ["approve", "transferfrom"],
        "description": "Approval exploit to drain reserves",
        "severity": ThreatLevel.HIGH,
        "min_amount": 50_000,
    },
    "price_manipulation": {
        "sequence": ["swap", "swap", "swap"],
        "description": "Repeated swaps to manipulate price oracle",
        "severity": ThreatLevel.HIGH,
        "min_amount": 10_000,
    },
    "governance_attack": {
        "sequence": ["flashloan", "delegate", "vote", "repay"],
        "description": "Flash loan governance attack",
        "severity": ThreatLevel.CRITICAL,
        "min_amount": 1_000_000,
    },
}


class FlashLoanRuleEngine(EngineBase):
    """
    FlashGuard식 공격 시퀀스 패턴 매칭 + 금액 이상 탐지 규칙 엔진.

    [LITE 구현]
    - 구현됨: 함수 호출 시퀀스 서브시퀀스 매칭 + 금액 임계값 + TX 유형 분석
    - 미구현: CNN-LSTM 시계열 이상 탐지, 멤풀 모니터링
    """

    DEFAULT_CONFIG = {
        "amount_thresholds": {
            "flash_loan": 100_000,
            "mint": 10_000,
            "drain_ratio": 0.10,
            "large_transfer": 1_000_000,
        },
        "enable_sequence_matching": True,
        "enable_amount_check": True,
        "enable_type_check": True,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        merged = {**self.DEFAULT_CONFIG, **(config or {})}
        super().__init__("FlashLoanRuleEngine", merged)
        self.is_placeholder = False  # ← 실제 구현 (lite)
        self.patterns = ATTACK_PATTERNS

    def analyze(self, tx_data: Dict[str, Any]) -> EngineResult:
        start = time.time()

        call_sequence = tx_data.get("call_sequence", [])
        amount = float(tx_data.get("amount", 0))
        tx_type = tx_data.get("type", "unknown").lower()

        scores: List[Tuple[ThreatLevel, float, str]] = []

        # ── 1) 함수 호출 시퀀스 패턴 매칭 ──
        if self.config["enable_sequence_matching"] and call_sequence:
            match_result = self._match_attack_patterns(call_sequence, amount)
            if match_result:
                scores.append(match_result)

        # ── 2) 금액 기반 이상 탐지 ──
        if self.config["enable_amount_check"]:
            amount_result = self._check_amount_anomaly(tx_data)
            if amount_result:
                scores.append(amount_result)

        # ── 3) TX 유형 기반 규칙 ──
        if self.config["enable_type_check"]:
            type_result = self._check_type_rules(tx_type, amount)
            if type_result:
                scores.append(type_result)

        # ── 4) [STUB] CNN-LSTM 시계열 이상 탐지 ──
        # ts_result = self._check_time_series_anomaly(tx_data)
        # if ts_result: scores.append(ts_result)

        # ── 최종 판정: 가장 높은 위협 수준 선택 ──
        if scores:
            best = max(scores, key=lambda x: (list(ThreatLevel).index(x[0]), x[1]))
            threat, confidence, reason = best
        else:
            threat = ThreatLevel.NONE
            confidence = 0.05
            reason = "no_match"

        latency = (time.time() - start) * 1000
        self.record_call(latency)

        return EngineResult(
            engine_name=self.name,
            threat_level=threat,
            confidence=round(confidence, 4),
            details={
                "matched_pattern": reason if reason != "no_match" else None,
                "call_sequence": call_sequence,
                "amount": amount,
                "tx_type": tx_type,
                "all_scores": [
                    {"level": s[0].value, "conf": round(s[1], 3), "reason": s[2]}
                    for s in scores
                ],
            },
            latency_ms=latency,
        )

    # ------------------------------------------------------------------
    # 내부 분석 메서드
    # ------------------------------------------------------------------

    def _match_attack_patterns(
        self, sequence: List[str], amount: float
    ) -> Optional[Tuple[ThreatLevel, float, str]]:
        """
        알려진 공격 패턴과 서브시퀀스 매칭.
        FlashGuard의 attack signature 방법론 참조.
        """
        best: Optional[Tuple[ThreatLevel, float, str]] = None

        for name, pattern in self.patterns.items():
            if self._is_subsequence(sequence, pattern["sequence"]):
                # 금액 최소 기준 확인
                if amount >= pattern["min_amount"]:
                    severity = pattern["severity"]
                    # 매칭 길이 비율로 confidence 조정
                    match_ratio = len(pattern["sequence"]) / max(len(sequence), 1)
                    confidence = min(0.95, 0.7 + match_ratio * 0.2)

                    if best is None or severity > best[0]:
                        best = (severity, confidence, name)

        return best

    def _is_subsequence(self, sequence: List[str], pattern: List[str]) -> bool:
        """sequence 내에 pattern이 서브시퀀스로 존재하는지 확인"""
        if not pattern:
            return True
        if not sequence:
            return False
        pi = 0
        for item in sequence:
            if pattern[pi].lower() in item.lower():
                pi += 1
                if pi == len(pattern):
                    return True
        return False

    def _check_amount_anomaly(
        self, tx_data: Dict[str, Any]
    ) -> Optional[Tuple[ThreatLevel, float, str]]:
        """금액 기반 이상치 점수"""
        amount = float(tx_data.get("amount", 0))
        tx_type = tx_data.get("type", "").lower()
        thresholds = self.config["amount_thresholds"]

        if "mint" in tx_type:
            threshold = thresholds["mint"]
            if amount > threshold * 50:
                return (ThreatLevel.CRITICAL, 0.90, "extreme_mint_amount")
            elif amount > threshold * 10:
                return (ThreatLevel.HIGH, 0.75, "high_mint_amount")
            elif amount > threshold:
                return (ThreatLevel.MEDIUM, 0.55, "elevated_mint_amount")

        if "flash" in tx_type:
            threshold = thresholds["flash_loan"]
            if amount > threshold * 100:
                return (ThreatLevel.CRITICAL, 0.85, "extreme_flash_loan")
            elif amount > threshold * 10:
                return (ThreatLevel.HIGH, 0.70, "high_flash_loan")
            elif amount > threshold:
                return (ThreatLevel.MEDIUM, 0.50, "elevated_flash_loan")

        if amount > thresholds["large_transfer"]:
            return (ThreatLevel.LOW, 0.30, "large_transfer")

        return None

    def _check_type_rules(
        self, tx_type: str, amount: float
    ) -> Optional[Tuple[ThreatLevel, float, str]]:
        """TX 유형 기반 정적 규칙"""
        suspicious_types = {
            "selfdestruct": (ThreatLevel.CRITICAL, 0.90),
            "delegatecall": (ThreatLevel.HIGH, 0.70),
            "exploit": (ThreatLevel.CRITICAL, 0.95),
            "exploit_mint": (ThreatLevel.CRITICAL, 0.95),
        }
        for keyword, (level, conf) in suspicious_types.items():
            if keyword in tx_type:
                return (level, conf, f"suspicious_type_{keyword}")
        return None

    def _check_time_series_anomaly(
        self, tx_data: Dict[str, Any]
    ) -> Optional[Tuple[ThreatLevel, float, str]]:
        """
        [STUB] CNN-LSTM 시계열 이상 탐지.
        향후 구현 시 이 메서드에 모델 추론 코드 추가.

        교체 코드:
          features = self._extract_ts_features(tx_data)
          prediction = self.cnn_lstm_model.predict(features)
          if prediction > 0.8:
              return (ThreatLevel.HIGH, prediction, "cnn_lstm_anomaly")
        """
        return None

    def get_engine_info(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "reference": "FlashGuard (attack signature methodology)",
            "status": "lite",
            "description": (
                "Rule-based attack sequence pattern matching adapted from "
                "FlashGuard. Covers flash loan, reentrancy, infinite mint, "
                "reserve drain, price manipulation, and governance attack patterns."
            ),
            "real_integration_point": (
                "Add CNN-LSTM model in _check_time_series_anomaly() for "
                "learned time-series anomaly detection."
            ),
        }
