"""
ThreatAggregator — 3개 엔진 결과를 가중 앙상블하여 최종 ThreatSignal 생성

집계 전략:
  - 각 엔진의 ThreatLevel × confidence → 수치 점수
  - 엔진별 가중치 적용 (placeholder 엔진은 낮은 가중치)
  - 최종 점수 → 대응 액션 결정 (none / alert / blacklist / pause_macro / pause_all)
"""

import time
import uuid
from typing import Dict, Any, List, Optional
from .base import (
    EngineResult,
    ThreatSignal,
    ThreatLevel,
    THREAT_LEVEL_SCORES,
)


class ThreatAggregator:
    """
    3개 이종 탐지 엔진의 결과를 집계하여 최종 위협 시그널을 생성합니다.

    가중치 기본값:
      - SequenceAnomalyEngine: 0.20 (placeholder이므로 낮은 가중치)
      - FlashLoanRuleEngine:   0.45 (규칙 기반 실 구현)
      - HoustonLiteInvariantChecker: 0.35 (invariant 실 구현)
    """

    DEFAULT_WEIGHTS: Dict[str, float] = {
        "SequenceAnomalyEngine": 0.20,
        "FlashLoanRuleEngine": 0.45,
        "HoustonLiteInvariantChecker": 0.35,
    }

    # 최종 점수 → 대응 액션 임계값
    ACTION_THRESHOLDS = {
        "pause_all":          0.90,  # 전체 정지 (극단적 위협)
        "pause_macro":        0.65,  # Macro 계층 정지
        "blacklist_address":  0.45,  # 주소 블랙리스트
        "alert_only":         0.25,  # 경고만
        "none":               0.00,  # 대응 없음
    }

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        thresholds: Optional[Dict[str, float]] = None,
    ):
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)
        self.thresholds = thresholds or dict(self.ACTION_THRESHOLDS)
        self._aggregation_count = 0

    def aggregate(
        self,
        results: List[EngineResult],
        tx_data: Optional[Dict[str, Any]] = None,
    ) -> ThreatSignal:
        """
        엔진 결과 리스트를 집계하여 최종 ThreatSignal 반환.

        Args:
            results: 3개 엔진의 EngineResult 리스트
            tx_data: 원본 트랜잭션 데이터 (signal에 포함)

        Returns:
            ThreatSignal 인스턴스
        """
        start = time.time()
        self._aggregation_count += 1

        # ── 가중 점수 계산 ──
        weighted_score = 0.0
        total_weight = 0.0

        for result in results:
            w = self.weights.get(result.engine_name, 0.33)
            level_score = THREAT_LEVEL_SCORES.get(result.threat_level, 0.0)
            score = level_score * result.confidence
            weighted_score += score * w
            total_weight += w

        final_score = weighted_score / total_weight if total_weight > 0 else 0.0

        # ── CRITICAL 오버라이드 ──
        # 어느 엔진이든 CRITICAL + 높은 confidence → 즉시 pause
        critical_override = any(
            r.threat_level == ThreatLevel.CRITICAL and r.confidence >= 0.8
            for r in results
        )
        if critical_override:
            final_score = max(final_score, 0.80)

        # ── 대응 액션 결정 ──
        action = "none"
        for act in ["pause_all", "pause_macro", "blacklist_address", "alert_only"]:
            if final_score >= self.thresholds[act]:
                action = act
                break

        # ── 최종 ThreatLevel 결정 ──
        if final_score >= 0.75:
            level = ThreatLevel.CRITICAL
        elif final_score >= 0.55:
            level = ThreatLevel.HIGH
        elif final_score >= 0.35:
            level = ThreatLevel.MEDIUM
        elif final_score >= 0.15:
            level = ThreatLevel.LOW
        else:
            level = ThreatLevel.NONE

        # ── ThreatSignal 생성 ──
        signal = ThreatSignal(
            signal_id=f"sig-{uuid.uuid4().hex[:8]}",
            timestamp=int(time.time()),
            threat_level=level,
            final_score=round(final_score, 4),
            recommended_action=action,
            engine_results=results,
            target_tx=tx_data or {},
        )

        return signal

    def get_stats(self) -> Dict[str, Any]:
        return {
            "aggregation_count": self._aggregation_count,
            "weights": self.weights,
            "thresholds": self.thresholds,
        }

    def update_weights(self, new_weights: Dict[str, float]):
        """가중치 업데이트 (실험 튜닝용)"""
        self.weights.update(new_weights)

    def update_thresholds(self, new_thresholds: Dict[str, float]):
        """액션 임계값 업데이트"""
        self.thresholds.update(new_thresholds)
