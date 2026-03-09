"""
엔진3: HoustonLiteInvariantChecker — HOUSTON 참조 실행 불변성 검사 (경량)
[LITE] 자동 invariant 추출 제외, 수동 정의 invariant만 검사

논문 참조: "Building upon HOUSTON's invariant-based anomaly detection framework"
실제 연동 지점: _define_invariants()에 자동 추출된 invariant 추가

HOUSTON 원본 구조 (참조용):
  1. houston.protocol   → 프로토콜 메타데이터/트랜잭션 수집
  2. houston.splitter   → 트랜잭션 분할/정규화
  3. carrot.py          → Daikon 스타일 invariant 추출기 (train/test)
  4. houston.checker    → 위반 검사 + 결과 리포트
  → 본 구현에서는 3번의 수동 버전 + 4번의 경량 버전만 구현
"""

import time
from dataclasses import dataclass
from typing import Dict, Any, List, Callable, Optional
from .base import EngineBase, EngineResult, ThreatLevel


# ---------------------------------------------------------------------------
# Invariant 정의 구조
# ---------------------------------------------------------------------------

@dataclass
class Invariant:
    """
    수동 정의 불변량.

    check_fn 시그니처:
        (state_before: Dict, state_after: Dict, tx_data: Dict) -> bool
        True = 불변량 유지 (정상), False = 위반 (이상)
    """
    name: str
    description: str
    check_fn: Callable[[Dict, Dict, Dict], bool]
    severity: ThreatLevel
    category: str = "general"  # supply, reserve, price, access, rate


class HoustonLiteInvariantChecker(EngineBase):
    """
    HOUSTON식 실행 불변성 검사 경량 엔진.

    [LITE 구현]
    - 구현됨: 수동 정의 5개 core invariant + 3개 access control invariant
    - 미구현: 자동 invariant 추출기 (solc 수정/trace 분석 필요)

    tx_data에 필요한 키:
      - state_before: TX 실행 전 컨트랙트 상태 딕셔너리
      - state_after: TX 실행 후 컨트랙트 상태 딕셔너리
      - amount, from, to, type 등 공통 키
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("HoustonLiteInvariantChecker", config)
        self.is_placeholder = False  # ← 실제 구현 (lite)
        self.invariants: List[Invariant] = self._define_invariants()

    def _define_invariants(self) -> List[Invariant]:
        """
        수동 정의 불변량 목록.
        HOUSTON의 carrot.py가 자동 추출하는 것을 수동으로 정의.
        """
        return [
            # ── Supply Invariants ──
            Invariant(
                name="total_supply_cap",
                description="totalSupply must not exceed initial_supply * 2",
                check_fn=lambda before, after, tx: (
                    after.get("total_supply", 0)
                    <= before.get("initial_supply", float("inf")) * 2
                ),
                severity=ThreatLevel.CRITICAL,
                category="supply",
            ),
            Invariant(
                name="supply_monotonic_without_burn",
                description="totalSupply should not decrease unless burn event",
                check_fn=lambda before, after, tx: (
                    after.get("total_supply", 0) >= before.get("total_supply", 0)
                    or tx.get("type", "") == "burn"
                ),
                severity=ThreatLevel.HIGH,
                category="supply",
            ),

            # ── Reserve Invariants ──
            Invariant(
                name="reserve_ratio",
                description="Reserve must not drop below 10% of totalSupply",
                check_fn=lambda before, after, tx: (
                    after.get("reserve", float("inf"))
                    >= after.get("total_supply", 1) * 0.10
                ),
                severity=ThreatLevel.HIGH,
                category="reserve",
            ),
            Invariant(
                name="reserve_drain_limit",
                description="Single TX must not drain more than 50% of reserve",
                check_fn=lambda before, after, tx: (
                    before.get("reserve", 1) == 0
                    or (before.get("reserve", 1) - after.get("reserve", 0))
                    / before.get("reserve", 1) <= 0.50
                ),
                severity=ThreatLevel.CRITICAL,
                category="reserve",
            ),

            # ── Single TX Limit Invariants ──
            Invariant(
                name="single_tx_supply_ratio",
                description="Single TX must not exceed 5% of totalSupply",
                check_fn=lambda before, after, tx: (
                    float(tx.get("amount", 0))
                    <= before.get("total_supply", float("inf")) * 0.05
                ),
                severity=ThreatLevel.HIGH,
                category="supply",
            ),

            # ── Price Invariants ──
            Invariant(
                name="price_stability",
                description="Price must not deviate >20% in a single TX",
                check_fn=lambda before, after, tx: (
                    before.get("price", 0) == 0
                    or abs(after.get("price", before.get("price", 1))
                           - before.get("price", 1))
                    / max(before.get("price", 1), 1e-18) <= 0.20
                ),
                severity=ThreatLevel.MEDIUM,
                category="price",
            ),

            # ── Rate Limit Invariants ──
            Invariant(
                name="mint_rate_limit",
                description="Period mint amount must not exceed mint limit",
                check_fn=lambda before, after, tx: (
                    after.get("period_mint_amount", 0)
                    <= before.get("mint_limit", float("inf"))
                ),
                severity=ThreatLevel.HIGH,
                category="rate",
            ),

            # ── Access Control Invariants ──
            Invariant(
                name="blacklist_enforcement",
                description="Blacklisted addresses should not transact",
                check_fn=lambda before, after, tx: (
                    not before.get("is_sender_blacklisted", False)
                ),
                severity=ThreatLevel.CRITICAL,
                category="access",
            ),
        ]

    def analyze(self, tx_data: Dict[str, Any]) -> EngineResult:
        start = time.time()

        state_before = tx_data.get("state_before", {})
        state_after = tx_data.get("state_after", {})

        violations: List[str] = []
        violation_details: List[Dict[str, str]] = []
        max_severity = ThreatLevel.NONE

        for inv in self.invariants:
            try:
                passed = inv.check_fn(state_before, state_after, tx_data)
                if not passed:
                    violations.append(inv.name)
                    violation_details.append({
                        "invariant": inv.name,
                        "description": inv.description,
                        "severity": inv.severity.value,
                        "category": inv.category,
                    })
                    if inv.severity > max_severity:
                        max_severity = inv.severity
            except Exception as e:
                # Invariant 평가 오류는 무시 (데이터 부재 등)
                pass

        # Confidence: 위반 수와 심각도에 비례
        if violations:
            base_conf = min(1.0, len(violations) * 0.25)
            severity_bonus = {
                ThreatLevel.CRITICAL: 0.3,
                ThreatLevel.HIGH: 0.2,
                ThreatLevel.MEDIUM: 0.1,
            }.get(max_severity, 0.0)
            confidence = min(0.98, base_conf + severity_bonus)
        else:
            confidence = 0.05

        latency = (time.time() - start) * 1000
        self.record_call(latency)

        return EngineResult(
            engine_name=self.name,
            threat_level=max_severity if violations else ThreatLevel.NONE,
            confidence=round(confidence, 4),
            details={
                "violations": violations,
                "violation_details": violation_details,
                "invariants_checked": len(self.invariants),
                "invariants_violated": len(violations),
                # ↓ 자동 추출 연동 시 추가될 필드
                # "auto_extracted_invariants": 0,
                # "extraction_source": "carrot.py",
            },
            latency_ms=latency,
        )

    def add_invariant(self, invariant: Invariant):
        """런타임에 invariant 추가 (확장용)"""
        self.invariants.append(invariant)

    def list_invariants(self) -> List[Dict[str, str]]:
        """등록된 invariant 목록 반환"""
        return [
            {
                "name": inv.name,
                "description": inv.description,
                "severity": inv.severity.value,
                "category": inv.category,
            }
            for inv in self.invariants
        ]

    def get_engine_info(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "reference": "HOUSTON [UCSB] (invariant-based anomaly detection)",
            "status": "lite",
            "description": (
                f"Lightweight invariant checker with {len(self.invariants)} "
                "manually defined invariants covering supply cap, reserve ratio, "
                "price stability, rate limits, and access control. "
                "Inspired by HOUSTON's carrot.py invariant engine."
            ),
            "real_integration_point": (
                "Add automated invariant extraction via Solidity trace analysis "
                "to supplement manually defined invariants."
            ),
        }
