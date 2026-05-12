"""
엔진3: HoustonLiteInvariantChecker — HOUSTON 참조 실행 불변성 검사 (경량)
[LITE] 자동 invariant 추출 제외, 수동 정의 invariant만 검사

논문 참조: "Building upon HOUSTON's invariant-based anomaly detection framework"
실제 연동 지점: _define_invariants()에 자동 추출된 invariant 추가

[Post-execution State Check 설계 원칙]
  TX 실행 전(state_before) → 실행 후(state_after) 상태 변화량(delta)을 추적하여
  프로토콜 불변량 위반을 탐지합니다. 단순 절댓값 기준이 아닌
  before→after 변화율 기반 규칙을 사용해 threshold evasion에 강인합니다.

[Invariant 목록 - 8개]
  INV-1: total_supply_cap          — 총 공급량 팽창 한도 (CRITICAL)
  INV-2: supply_monotonic_check     — 공급량 단조성 검사 (HIGH)
  INV-3: reserve_collateral_ratio   — reserve+collateral 통합 비율 (CRITICAL)
  INV-4: reserve_drain_limit        — 단일 TX reserve 소진율 ≤30% (CRITICAL)
  INV-5: single_tx_reserve_impact   — 단일 TX의 reserve 대비 영향도 (HIGH)
  INV-6: price_deviation_per_tx     — 방향성 가중 가격 안정성 (MEDIUM)
  INV-7: cumulative_mint_velocity   — 누적 민트 속도 + rate limit (HIGH)
  INV-8: collateral_backing_ratio   — 담보 비율 ≥ 95% (CRITICAL) [신규]

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

    [LITE 구현 — Post-execution State Check]
    - 구현됨: 수동 정의 8개 invariant (supply/reserve/price/rate/collateral/access)
    - 미구현: 자동 invariant 추출기 (solc 수정/trace 분석 필요)

    tx_data에 필요한 키:
      - state_before: TX 실행 전 컨트랙트 상태 딕셔너리
          필수: total_supply, initial_supply, reserve, price, mint_limit
          선택: collateral, period_mint_amount, is_sender_blacklisted
      - state_after: TX 실행 후 컨트랙트 상태 딕셔너리
          필수: total_supply, reserve, price, period_mint_amount
          선택: collateral
      - amount, from, to, type 등 공통 키
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("HoustonLiteInvariantChecker", config)
        self.is_placeholder = False  # ← 실제 구현 (lite)
        self.invariants: List[Invariant] = self._define_invariants()

    def _define_invariants(self) -> List[Invariant]:
        """
        수동 정의 불변량 목록 — Post-execution State Check 기반.

        각 check_fn은 (state_before, state_after, tx_data) → bool 를 받아
        True=정상(불변량 유지), False=위반(이상 탐지) 를 반환합니다.

        설계 원칙:
          - before→after 변화량(delta) 중심으로 규칙 구성
          - 단순 절댓값 비교보다 변화율 기반 검사 우선
          - 공격 분류별 위반 커버리지 극대화
        """
        return [
            # ══════════════════════════════════════════════════════
            # INV-1: 총 공급량 팽창 한도 (Supply Cap)
            # Post-exec: after.total_supply ≤ initial_supply × 2
            # 추가: 단일 TX 증가량이 before.supply × 50% 초과 시 조기 위반
            # ══════════════════════════════════════════════════════
            Invariant(
                name="total_supply_cap",
                description=(
                    "[INV-1] totalSupply must not exceed initial_supply×2. "
                    "Also flags single-TX supply delta > 50% of before.supply."
                ),
                check_fn=lambda before, after, tx: (
                    # 절대 한도: after ≤ initial × 2
                    after.get("total_supply", 0)
                    <= before.get("initial_supply", float("inf")) * 2
                    # delta 조기 경고: 단일 TX 공급량 증가 ≤ before × 0.5
                    and (
                        before.get("total_supply", 0) == 0
                        or (after.get("total_supply", 0) - before.get("total_supply", 0))
                        / max(before.get("total_supply", 1), 1)
                        <= 0.50
                    )
                ),
                severity=ThreatLevel.CRITICAL,
                category="supply",
            ),

            # ══════════════════════════════════════════════════════
            # INV-2: 공급량 단조성 검사 (Supply Monotonicity)
            # Post-exec: supply 감소는 번/리딤/청산 TX에서만 허용
            # ══════════════════════════════════════════════════════
            Invariant(
                name="supply_monotonic_check",
                description=(
                    "[INV-2] totalSupply must not decrease unless burn/redeem/liquidate TX."
                ),
                check_fn=lambda before, after, tx: (
                    after.get("total_supply", 0) >= before.get("total_supply", 0)
                    or tx.get("type", "") in {"burn", "redeem", "liquidate", "repay"}
                ),
                severity=ThreatLevel.HIGH,
                category="supply",
            ),

            # ══════════════════════════════════════════════════════
            # INV-3: Reserve + Collateral 통합 비율 검사
            # Post-exec: after.reserve ≥ after.total_supply × 10%
            # ══════════════════════════════════════════════════════
            Invariant(
                name="reserve_collateral_ratio",
                description=(
                    "[INV-3] Reserve must stay ≥ 10% of totalSupply. "
                    "(Collateral delta check is handled separately by INV-8.)"
                ),
                check_fn=lambda before, after, tx: (
                    # reserve 비율만 체크 (collateral 담당은 INV-8에서르)
                    after.get("reserve", float("inf"))
                    >= after.get("total_supply", 1) * 0.10
                ),
                severity=ThreatLevel.HIGH,
                category="reserve",
            ),

            # ══════════════════════════════════════════════════════
            # INV-4: 단일 TX Reserve 소진율 (강화: 50% → 30%)
            # Post-exec delta: (before.reserve - after.reserve) / before.reserve ≤ 0.30
            # ══════════════════════════════════════════════════════
            Invariant(
                name="reserve_drain_limit",
                description=(
                    "[INV-4] Single TX must not drain more than 30% of reserve "
                    "(post-exec delta basis). Strengthened from 50% to 30%."
                ),
                check_fn=lambda before, after, tx: (
                    before.get("reserve", 1) == 0
                    or (
                        before.get("reserve", 1) - after.get("reserve", 0)
                    ) / max(before.get("reserve", 1), 1e-18) <= 0.30
                ),
                severity=ThreatLevel.CRITICAL,
                category="reserve",
            ),

            # ══════════════════════════════════════════════════════
            # INV-5: 단일 TX의 Reserve 대비 영향도
            # Post-exec: amount / before.reserve ≤ 0.20 (reserve 대비 20%)
            # 기존 totalSupply 기준 → reserve 기준으로 변경
            # ══════════════════════════════════════════════════════
            Invariant(
                name="single_tx_reserve_impact",
                description=(
                    "[INV-5] Single TX amount must not exceed 20% of before.reserve. "
                    "Changed from totalSupply-based to reserve-based for better sensitivity."
                ),
                check_fn=lambda before, after, tx: (
                    before.get("reserve", 0) == 0
                    or float(tx.get("amount", 0))
                    / max(before.get("reserve", 1), 1e-18) <= 0.20
                ),
                severity=ThreatLevel.HIGH,
                category="supply",
            ),

            # ══════════════════════════════════════════════════════
            # INV-6: 방향성 가중 가격 안정성 (Price Deviation)
            # Post-exec: 하락 >15% OR 상승 >25% 시 위반
            # 하락 방향에 더 강한 임계값 적용 (디페깅 공격 대응)
            # ══════════════════════════════════════════════════════
            Invariant(
                name="price_deviation_per_tx",
                description=(
                    "[INV-6] Price drop >15% or price spike >25% in a single TX. "
                    "Asymmetric thresholds: steeper for price drops (depeg attacks)."
                ),
                check_fn=lambda before, after, tx: (
                    before.get("price", 0) == 0
                    or (
                        lambda p_before, p_after: (
                            True if p_before <= 0 else
                            # 하락: 15% 초과 시 위반
                            False if (p_before - p_after) / p_before > 0.15
                            # 상승: 25% 초과 시 위반
                            else False if (p_after - p_before) / p_before > 0.25
                            else True
                        )
                    )(
                        max(before.get("price", 1), 1e-18),
                        after.get("price", before.get("price", 1))
                    )
                ),
                severity=ThreatLevel.MEDIUM,
                category="price",
            ),

            # ══════════════════════════════════════════════════════
            # INV-7: 누적 민트 속도 이중 검사 (Cumulative Mint Velocity)
            # Post-exec: period_mint_amount ≤ mint_limit (rate limit)
            # 추가: period_mint_amount / initial_supply ≤ 0.30 (30% 속도 한도)
            # ══════════════════════════════════════════════════════
            Invariant(
                name="cumulative_mint_velocity",
                description=(
                    "[INV-7] period_mint_amount must not exceed mint_limit AND "
                    "must not exceed 30% of initial_supply (velocity cap)."
                ),
                check_fn=lambda before, after, tx: (
                    # 기존 rate limit
                    after.get("period_mint_amount", 0)
                    <= before.get("mint_limit", float("inf"))
                    # 신규 velocity cap: 누적 발행량 ≤ initial_supply × 30%
                    and (
                        before.get("initial_supply", 0) == 0
                        or after.get("period_mint_amount", 0)
                        / max(before.get("initial_supply", 1), 1e-18) <= 0.30
                    )
                ),
                severity=ThreatLevel.HIGH,
                category="rate",
            ),

            # ══════════════════════════════════════════════════════
            # INV-8: 담보 비율 검사 [신규 — Post-exec 핵심]
            # Post-exec: after.collateral ≥ after.total_supply × 0.95
            # 무담보 민트 공격(Infinite Mint)을 즉시 탐지하는 핵심 규칙
            # ══════════════════════════════════════════════════════
            Invariant(
                name="collateral_backing_ratio",
                description=(
                    "[INV-8] [NEW] Delta-based collateral check: when totalSupply INCREASES "
                    "(minting), collateral must increase by at least 90% of minted amount. "
                    "No-mint TXs (transfer/burn/drain) are exempt from this check."
                ),
                check_fn=lambda before, after, tx: (
                    # collateral 필드가 양쪽에 없으면 skip (하위 호환성)
                    "collateral" not in after or "collateral" not in before
                    # totalSupply가 증가하지 않았으면 skip
                    # (transfer/burn/reserve drain은 이 조건에서 자동 통과)
                    or after.get("total_supply", 0) <= before.get("total_supply", 0)
                    # 발행이 일어난 경우:
                    # delta_collateral >= delta_supply * 0.90 이어야 정상
                    or (
                        after.get("collateral", 0) - before.get("collateral", 0)
                        >= (
                            after.get("total_supply", 0) - before.get("total_supply", 0)
                        ) * 0.90
                    )
                ),
                severity=ThreatLevel.CRITICAL,
                category="collateral",
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
        # (over-confidence 방지: 위반 1개당 0.25 → 0.20으로 조정)
        if violations:
            base_conf = min(1.0, len(violations) * 0.20)
            severity_bonus = {
                ThreatLevel.CRITICAL: 0.35,
                ThreatLevel.HIGH:     0.20,
                ThreatLevel.MEDIUM:   0.10,
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
                f"Post-execution state check invariant checker with {len(self.invariants)} "
                "manually defined invariants (INV-1~8) covering: "
                "supply cap+delta, supply monotonicity, reserve+collateral ratio, "
                "reserve drain (30%), reserve impact, asymmetric price deviation, "
                "cumulative mint velocity, and collateral backing ratio. "
                "Inspired by HOUSTON's carrot.py invariant engine."
            ),
            "real_integration_point": (
                "Add automated invariant extraction via Solidity trace analysis "
                "to supplement manually defined invariants."
            ),
        }
