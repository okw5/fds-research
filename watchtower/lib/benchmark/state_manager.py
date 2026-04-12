"""
DetectionStateManager
탐지 엔진 간 공유되는 시계열 상태 추적기.

기능:
  - tx_history       : 최근 1000건 트랜잭션 시계열 버퍼
  - wallet_freq_tracker : 지갑별 트랜잭션 빈도 추적 (60초 슬라이딩 윈도우)
  - anomaly_streak   : 연속 이상 감지 카운터
  - rolling_fpr      : 최근 100건 FP 여부 롤링 기록

빈도 이상 패널티:
  특정 지갑이 최근 60초 내 5회 이상 등장하면 score *= 1.3

사용 예시:
    manager = DetectionStateManager()

    # 탐지 시스템이 탐지 후 기록
    manager.record(scenario, prediction='ATTACK', score=0.72, is_fp=False)

    # 누적 기반 점수 보정 (Method B)
    corrected = manager.apply_frequency_penalty(score=0.5, wallet_id='0xABC', now_sec=100.0)

단위 테스트:
    manager = DetectionStateManager()
    for i in range(6):
        manager.record_wallet('0xABC', t=float(i))
    corrected = manager.apply_frequency_penalty(0.5, '0xABC', now_sec=10.0)
    assert corrected > 0.5   # 이상 패널티 적용됨
"""

from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import Deque, DefaultDict, List, Dict, Any, Optional
import time

try:
    from .scenario import Scenario
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scenario import Scenario


@dataclass
class TxRecord:
    """시계열 버퍼의 단일 트랜잭션 기록"""
    scenario_id:   str
    scenario_type: str
    network:       str
    prediction:    str      # 'ATTACK' or 'NORMAL'
    score:         float    # AnomalyScorer 출력 점수
    is_fp:         bool     # False Positive 여부
    timestamp_sec: float    # 시뮬레이션 시각 (초)
    wallet_id:     str = ''


class DetectionStateManager:
    """
    모든 탐지 엔진에서 공유하는 시계열 상태 추적기.

    [설계 원칙]
    - 싱글턴 패턴 사용 권장 (실험 반복마다 reset() 호출)
    - Microservice 아키텍처 고려: 경량 deque 기반으로 메모리 보호
    - 지갑 빈도 추적: sliding window (60초 내 기록만 유지)
    """

    WALLET_WINDOW_SEC:   float = 60.0   # 빈도 추적 슬라이딩 윈도우 (초)
    FREQ_THRESHOLD:      int   = 5      # 이 횟수 이상이면 이상 패널티 적용
    FREQ_PENALTY_FACTOR: float = 1.3    # 빈도 이상 시 score 승수
    FREQ_MAX_SCORE:      float = 1.0    # 패널티 적용 후 score 상한
    STREAK_BOOST:        float = 0.05   # 연속 이상 감지 시 score 보너스

    def __init__(self):
        # 최근 1000건 트랜잭션 시계열 이력
        self.tx_history: Deque[TxRecord] = deque(maxlen=1000)

        # 지갑별 트랜잭션 타임스탬프 이력 (sliding window 관리용)
        self.wallet_freq_tracker: DefaultDict[str, List[float]] = defaultdict(list)

        # 연속 이상 감지 카운터
        self.anomaly_streak: int = 0

        # 최근 100건 FP 여부 롤링 기록 (True = FP 발생)
        self.rolling_fpr: Deque[bool] = deque(maxlen=100)

        # 시뮬레이션 시각 커서 (record 호출마다 +1)
        self._sim_clock: float = 0.0

    # ── 기록 API ──────────────────────────────────────────────────────────────

    def record(
        self,
        scenario: Scenario,
        prediction: str,
        score: float,
        is_fp: bool,
        wallet_id: str = '',
        sim_time_sec: Optional[float] = None,
    ) -> None:
        """
        탐지 결과를 시계열 버퍼와 롤링 통계에 기록한다.

        Args:
            scenario     : 처리된 시나리오
            prediction   : 탐지 결과 ('ATTACK' / 'NORMAL')
            score        : AnomalyScorer 출력 점수 [0, 1]
            is_fp        : False Positive 여부
            wallet_id    : 연관 지갑 주소 (빈도 추적용)
            sim_time_sec : 지정 시뮬레이션 시각 (미지정 시 내부 클럭 사용)
        """
        t = sim_time_sec if sim_time_sec is not None else self._sim_clock
        self._sim_clock += 1.0

        rec = TxRecord(
            scenario_id=scenario.id,
            scenario_type=scenario.scenario_type.value,
            network=scenario.network_condition,
            prediction=prediction,
            score=score,
            is_fp=is_fp,
            timestamp_sec=t,
            wallet_id=wallet_id,
        )
        self.tx_history.append(rec)
        self.rolling_fpr.append(is_fp)

        # 연속 이상 감지 카운터 갱신
        if prediction == 'ATTACK':
            self.anomaly_streak += 1
        else:
            self.anomaly_streak = 0

        # 지갑 빈도 추적
        if wallet_id:
            self.record_wallet(wallet_id, t)

    def record_wallet(self, wallet_id: str, t: float) -> None:
        """지갑 타임스탬프를 슬라이딩 윈도우 버퍼에 기록한다."""
        self.wallet_freq_tracker[wallet_id].append(t)

    # ── 보정 API ──────────────────────────────────────────────────────────────

    def apply_frequency_penalty(
        self,
        score: float,
        wallet_id: str,
        now_sec: float,
    ) -> float:
        """
        Method B 누적 기반 점수 보정:
        특정 지갑이 최근 WALLET_WINDOW_SEC 내 FREQ_THRESHOLD 이상 등장 시
        score *= FREQ_PENALTY_FACTOR.

        단위 테스트:
            for i in range(6): manager.record_wallet('0xA', float(i))
            assert manager.apply_frequency_penalty(0.5, '0xA', 10.0) > 0.5

        Args:
            score     : 기본 이상 점수
            wallet_id : 확인할 지갑 주소
            now_sec   : 현재 시뮬레이션 시각

        Returns:
            보정된 score (상한 FREQ_MAX_SCORE)
        """
        if not wallet_id:
            return score

        window_start = now_sec - self.WALLET_WINDOW_SEC

        # 만료된 기록 제거 (sliding window 유지)
        history = self.wallet_freq_tracker[wallet_id]
        self.wallet_freq_tracker[wallet_id] = [
            ts for ts in history if ts >= window_start
        ]
        recent_count = len(self.wallet_freq_tracker[wallet_id])

        if recent_count >= self.FREQ_THRESHOLD:
            score = min(self.FREQ_MAX_SCORE, score * self.FREQ_PENALTY_FACTOR)

        return score

    def apply_streak_boost(self, score: float) -> float:
        """
        연속 이상 감지 카운터가 클수록 score를 소량 상향 보정.
        (공격 패턴이 연속으로 감지되면 더 높은 확신으로 처리)
        """
        boost = min(0.10, self.anomaly_streak * self.STREAK_BOOST)
        return min(1.0, score + boost)

    # ── 통계 API ──────────────────────────────────────────────────────────────

    def get_rolling_fpr(self) -> float:
        """최근 100건 기준 롤링 FPR 반환"""
        if not self.rolling_fpr:
            return 0.0
        return sum(self.rolling_fpr) / len(self.rolling_fpr)

    def get_anomaly_density(self, window: int = 20) -> float:
        """
        최근 window건 내 이상 탐지 비율.
        높을수록 공격이 집중된 구간.
        """
        recent = list(self.tx_history)[-window:]
        if not recent:
            return 0.0
        return sum(1 for r in recent if r.prediction == 'ATTACK') / len(recent)

    def get_network_degradation(self) -> Dict[str, float]:
        """
        최근 100건의 네트워크 상태 분포.
        Returns: {'normal': ratio, 'congested': ratio, 'severe': ratio}
        """
        recent = list(self.tx_history)[-100:]
        if not recent:
            return {'normal': 1.0, 'congested': 0.0, 'severe': 0.0}
        total = len(recent)
        dist: Dict[str, float] = {'normal': 0.0, 'congested': 0.0, 'severe': 0.0}
        for rec in recent:
            if rec.network in dist:
                dist[rec.network] += 1.0 / total
        return dist

    def snapshot(self) -> Dict[str, Any]:
        """현재 상태 스냅샷 반환 (시각화 / 로깅 용도)"""
        return {
            'tx_history_len':  len(self.tx_history),
            'anomaly_streak':  self.anomaly_streak,
            'rolling_fpr':     round(self.get_rolling_fpr(), 4),
            'anomaly_density': round(self.get_anomaly_density(), 4),
            'network_dist':    self.get_network_degradation(),
            'tracked_wallets': len(self.wallet_freq_tracker),
        }

    def reset(self) -> None:
        """상태 완전 초기화 (실험 반복 사이에 호출)"""
        self.tx_history.clear()
        self.wallet_freq_tracker.clear()
        self.anomaly_streak = 0
        self.rolling_fpr.clear()
        self._sim_clock = 0.0
