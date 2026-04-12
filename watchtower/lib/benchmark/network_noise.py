"""
NetworkNoiseInjector
멤풀(Mempool) 환경을 현실적으로 모사하는 네트워크 노이즈 주입기.

혼잡도별 처리:
  drop       : 해당 확률로 이벤트를 스트림에서 삭제 (탐지 엔진 미수신)
  reorder    : 해당 확률로 timestamp를 ±[0,3]초 교란 (순서 역전)
  duplicate  : 해당 확률로 동일 이벤트를 중복 삽입 (dedup 필요)

사용 예시:
    injector = NetworkNoiseInjector()
    stream   = injector.apply(scenarios)        # Scenario 리스트에 적용
    result   = injector.process_stream(stream)  # 노이즈 이벤트 처리 후 반환

단위 테스트:
    assert NetworkNoiseInjector._dedup(events) 중복 제거 동작
    assert drop_rate 비율만큼 스트림이 감소
"""

import random
import math
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

try:
    from .scenario import Scenario
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scenario import Scenario


# ── 혼잡도별 노이즈 설정 ───────────────────────────────────────────────────────
NETWORK_NOISE_CONFIG: Dict[str, Dict[str, float]] = {
    'normal':    {'drop_rate': 0.00, 'reorder_rate': 0.00, 'duplicate_rate': 0.00},
    'congested': {'drop_rate': 0.02, 'reorder_rate': 0.05, 'duplicate_rate': 0.01},
    'severe':    {'drop_rate': 0.08, 'reorder_rate': 0.20, 'duplicate_rate': 0.03},
}

# ── 혼잡도별 Log-Normal latency 승수 파라미터 ─────────────────────────────────
# base_latency * LogNormal(log(severity_factor), sigma) 로 최종 latency 결정
LATENCY_CONGESTION_PARAMS: Dict[str, Tuple[float, float]] = {
    # (severity_factor → mean of LogNormal, sigma → dispersion)
    'normal':    (1.00, 0.05),   # 거의 변동 없음
    'congested': (1.30, 0.15),   # 평균 1.3배, 분산 미미
    'severe':    (1.80, 0.35),   # 평균 1.8배, 분산 크게 증가
}


@dataclass
class StreamEvent:
    """
    시뮬레이션 이벤트 스트림의 단일 이벤트.
    Scenario를 래핑하고 타임스탬프와 노이즈 메타데이터를 추가.
    """
    scenario: Scenario
    timestamp: float          # 이벤트 발생 시각 (시뮬레이션 초)
    tx_hash: str              # dedup 키
    is_duplicate: bool = False
    is_reordered: bool = False
    timestamp_jitter: float = 0.0   # 교란된 시간 오프셋 (초)

    def dedup_key(self) -> str:
        """중복 제거 키 = tx_hash + 원본 타임스탬프 (소수점 하 2자리까지)"""
        base_ts = round(self.timestamp - self.timestamp_jitter, 2)
        return f"{self.tx_hash}@{base_ts}"


class NetworkNoiseInjector:
    """
    시나리오 스트림에 혼잡도 기반 멤풀 노이즈를 삽입한다.

    [공개 API]
    apply(scenarios)               : Scenario 리스트 → StreamEvent 리스트 (노이즈 포함)
    process_stream(stream)         : dedup + reorder 정규화 후 최종 스트림 반환
    sample_latency_multiplier(net) : 혼잡도별 Log-Normal latency 승수 샘플링
    compute_window_confidence(gap_ratio) : 시퀀스 갭으로 인한 신뢰도 반환
    """

    def __init__(self, seed: Optional[int] = None):
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

    # ── 스트림 생성 ───────────────────────────────────────────────────────────

    def apply(self, scenarios: List[Scenario],
              base_interval_sec: float = 1.0) -> List[StreamEvent]:
        """
        Scenario 리스트를 StreamEvent 시계열로 변환하고
        혼잡도별 노이즈(drop / reorder / duplicate)를 삽입한다.

        Args:
            scenarios       : 원본 시나리오 목록 (순서대로 시계열)
            base_interval_sec : 이벤트 간 기본 시간 간격 (초)

        Returns:
            List[StreamEvent] — 노이즈 이벤트가 포함된 스트림
        """
        stream: List[StreamEvent] = []
        t = 0.0

        for i, scenario in enumerate(scenarios):
            cfg = NETWORK_NOISE_CONFIG.get(scenario.network_condition,
                                           NETWORK_NOISE_CONFIG['normal'])
            tx_hash = f"tx_{i:06d}_{scenario.id}"

            # ① DROP: 해당 확률로 이벤트 제거 → 탐지 엔진이 수신하지 못함
            if random.random() < cfg['drop_rate']:
                t += base_interval_sec
                continue   # 스트림에 추가하지 않음

            # ② REORDER: timestamp 교란
            jitter = 0.0
            is_reordered = False
            if random.random() < cfg['reorder_rate']:
                jitter = random.uniform(-3.0, 3.0)
                is_reordered = True

            event = StreamEvent(
                scenario=scenario,
                timestamp=t + jitter,
                tx_hash=tx_hash,
                is_reordered=is_reordered,
                timestamp_jitter=jitter,
            )
            stream.append(event)

            # ③ DUPLICATE: 동일 이벤트를 ±0.1초 이내에 중복 삽입
            if random.random() < cfg['duplicate_rate']:
                dup = StreamEvent(
                    scenario=scenario,
                    timestamp=t + jitter + random.uniform(0.01, 0.1),
                    tx_hash=tx_hash,
                    is_duplicate=True,
                    is_reordered=is_reordered,
                    timestamp_jitter=jitter,
                )
                stream.append(dup)

            t += base_interval_sec

        return stream

    # ── 스트림 정처리 ─────────────────────────────────────────────────────────

    def process_stream(self, stream: List[StreamEvent]) -> List[StreamEvent]:
        """
        raw 스트림을 받아:
        1) timestamp 기준 정렬 (reorder 정규화)
        2) dedup 키 기준 중복 제거

        Returns:
            정제된 StreamEvent 리스트 (시계열 순서)
        """
        # 정렬 (reordering 정규화): 정렬 비용은 탐지 latency에 반영됨
        sorted_stream = sorted(stream, key=lambda e: e.timestamp)

        # dedup
        seen: set = set()
        deduped: List[StreamEvent] = []
        for event in sorted_stream:
            key = event.dedup_key()
            if key not in seen:
                seen.add(key)
                deduped.append(event)

        return deduped

    # ── 재정렬 비용 계산 ──────────────────────────────────────────────────────

    @staticmethod
    def reorder_penalty_ms(stream: List[StreamEvent]) -> float:
        """
        timestamp 역전이 발견된 건수 비율로 윈도우 재정렬 추가 latency를 반환.
        reorder된 이벤트가 많을수록 최대 200ms까지 페널티가 증가.

        단위 테스트:
            assert reorder_penalty_ms([]) == 0.0
        """
        if not stream:
            return 0.0
        reordered = sum(1 for e in stream if e.is_reordered)
        ratio = reordered / len(stream)
        return ratio * 200.0   # 최대 +200ms

    # ── 신뢰도 계산 ───────────────────────────────────────────────────────────

    @staticmethod
    def compute_window_confidence(
        total_expected: int,
        total_received: int,
    ) -> float:
        """
        시퀀스 갭(drop)으로 인한 윈도우 신뢰도를 반환.

        adjusted_score = raw_score * confidence

        Args:
            total_expected: 윈도우 내 예상 이벤트 수
            total_received: 실제 수신된 이벤트 수

        Returns:
            confidence in [0.0, 1.0]

        단위 테스트:
            assert compute_window_confidence(10, 10) == 1.0
            assert compute_window_confidence(10, 8) == 0.8
        """
        if total_expected <= 0:
            return 1.0
        gap_ratio = max(0.0, (total_expected - total_received) / total_expected)
        return max(0.0, 1.0 - gap_ratio)

    # ── LogNormal latency 승수 ────────────────────────────────────────────────

    @staticmethod
    def sample_latency_multiplier(network_condition: str) -> float:
        """
        단순 상수 곱셈 대신 Log-Normal 분포에서 latency 승수를 샘플링.

            multiplier = LogNormal(log(severity_factor), sigma * severity_level)

        severity_level:  normal=0, congested=1, severe=2
        분산이 혼잡도에 비례하여 증가 → 불규칙한 멤풀 지연을 현실적으로 반영.

        Returns:
            float, 항상 > 0

        단위 테스트:
            mult = sample_latency_multiplier('normal')
            assert 0.9 < mult < 1.1  (≈1.0 중심)
        """
        severity_factor, sigma = LATENCY_CONGESTION_PARAMS.get(
            network_condition, LATENCY_CONGESTION_PARAMS['normal']
        )
        mu = math.log(severity_factor)
        return float(np.random.lognormal(mean=mu, sigma=sigma))

    # ── 스트림 통계 ───────────────────────────────────────────────────────────

    @staticmethod
    def stream_stats(
        original: List[Scenario],
        stream: List[StreamEvent],
    ) -> Dict[str, float]:
        """
        원본 대비 처리된 스트림 통계 반환.

        단위 테스트:
            stats = stream_stats(scenarios, processed)
            assert 0.0 <= stats['drop_rate'] <= 1.0
        """
        n_orig = len(original)
        n_stream = len(stream)
        n_dup = sum(1 for e in stream if e.is_duplicate)
        n_reordered = sum(1 for e in stream if e.is_reordered)

        return {
            'original_count': float(n_orig),
            'stream_count':   float(n_stream),
            'drop_rate':      max(0.0, (n_orig - n_stream) / max(1, n_orig)),
            'duplicate_rate': n_dup / max(1, n_stream),
            'reorder_rate':   n_reordered / max(1, n_stream),
        }
