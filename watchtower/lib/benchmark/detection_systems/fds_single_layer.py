"""
FDSSingleLayerSystem
FDS 단일 토큰 탐지 시스템

특징:
- 자동화된 임계값 기반 탐지
- 반응 시간: 250~450ms (평균 350ms)
- 피처 기반 이상 점수 + 과부하 연동 동적 FPR 적용
- 네트워크 혼잡 시 지연 증가
- 공격 탐지 시: 전체 토큰 일시정지 (Pause)
- 중단 시간: 5~30분 (자동화된 조사 후 수동 복구)
"""

import random
import numpy as np
from typing import Tuple, Dict, Any, Optional
from .base import DetectionSystem, DetectionConfig, DetectionResponse

# 조건부 임포트: 패키지 모드와 직접 실행 모드 지원
try:
    from ..scenario import Scenario, ScenarioType, ScenarioLabel
    from ..feature_extractor import extract_features
    from ..anomaly_scorer import AnomalyScorer
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scenario import Scenario, ScenarioType, ScenarioLabel
    from feature_extractor import extract_features
    from anomaly_scorer import AnomalyScorer


class FDSSingleLayerSystem(DetectionSystem):
    """
    FDS 단일 토큰 탐지 시스템
    
    알고리즘:
    1. 단순 임계값 검사 (Method A)
    2. 누적 윈도우 검사 (Method B)
    3. 변화율 검사
    
    한계:
    - 전체 시스템 중단 (가용성 0%)
    - 네트워크 혼잡 시 서킷 브레이커 지연
    - 단일 토큰이므로 소액/거액 구분 없이 전체 정지
    """
    
    def __init__(self, config=None):
        default_config = DetectionConfig.get_fds_single_layer_config()
        if config:
            default_config.update(config)
        super().__init__("FDS 단일 토큰", default_config)
        # 엔진 과부하 상태 추적
        self._tx_count      = 0
        self._overload_level = 0
        self._current_fpr   = default_config.get('false_positive_rate', 0.05)
        # 피처 기반 이상 점수 산출기
        anomaly_method   = default_config.get('anomaly_method', 'zscore')
        self._scorer     = AnomalyScorer(method=anomaly_method)
        # 마지막 앙상블 적용값 (detect_extended 에서 참조)
        self._last_applied_fpr       = self._current_fpr
        self._last_applied_threshold = 0.5
    
    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        """
        FDS 단일계층 탐지 — 동일 엔진으로 Macro+Micro 모두 처리

        [Macro 공격] 250~450ms: 2계층 Macro 엔진과 동일 속도
        [Micro 공격] 875~1575ms: 임계값 미달 → 누적 패턴 탐지 필요 (3.5배 지연)
        [과부하 시]  +1.8배 추가: 단일 엔진 처리 한계 초과
        """
        cfg = self.config
        self._tx_count += 1

        # 과부하 단계 업데이트
        overload_threshold = cfg['overload_threshold_tx']
        self._overload_level = self._tx_count // overload_threshold
        # FPR 동적 상승 (과부하 단계당 +4%, 최대 18%)
        self._current_fpr = min(
            cfg['max_overload_fpr'],
            0.05 + self._overload_level * cfg['overload_fpr_increment']
        )

        # 기본 지연 시간
        base_latency = cfg['base_latency_ms']
        variance = cfg['latency_variance_ms']
        latency_ms = base_latency + random.uniform(-variance, variance)

        # Micro 공격(시빌·임계회피)은 개별 건이 임계값 미달
        # → 누적 패턴 감지를 위한 윈도우 분석 필요 → 3.5배 추가 지연
        is_micro_attack = scenario.scenario_type in {
            ScenarioType.SYBIL_ATTACK,
            ScenarioType.THRESHOLD_EVASION,
        } or scenario.parameters.get('is_micro_swarm', False)

        if is_micro_attack:
            latency_ms *= cfg['micro_detection_delay_multiplier']

        # 엔진 과부하 시 추가 지연
        if self._overload_level > 0:
            latency_ms *= cfg['overload_latency_multiplier']

        # 네트워크 혼잡도 적용 (Log-Normal 분포, v4)
        latency_ms = self._apply_congestion_latency(latency_ms, scenario.network_condition)

        # 탐지 알고리즘 실행 (FPR 정보 포함)
        prediction, applied_fpr, applied_threshold = self._run_detection_algorithms(scenario)

        self._record_detection(latency_ms)
        self._last_applied_fpr = applied_fpr
        self._last_applied_threshold = applied_threshold
        return (prediction, latency_ms)
    
    def detect_extended(self, scenario: Scenario) -> DetectionResponse:
        """
        확장된 탐지 결과 (피해금액 + 서비스 중단 시간 포함)

        단일계층 핵심 한계:
        - Macro+Micro 동일 엔진 → 과부하 시 latency 상승 + FPR 증가
        - Micro 공격 탐지 지연 → 피해 누적 후 탐지
        - 탐지 시 전체 pause → 소액결제 포함 모든 서비스 중단
        """
        prediction, latency_ms = self.detect(scenario)
        detected_as_attack = (prediction == 'ATTACK')

        # 피해금액: 과부하로 지연된 latency → 피해 증가
        financial_loss = self._estimate_financial_loss(
            scenario, latency_ms, detected_as_attack
        )

        service_downtime_sec = 0.0
        micro_available = True
        freeze_scope = 'none'
        response_action = 'none'

        if detected_as_attack:
            # 단일계층 한계: 탐지 시 전체 정지(pause_all) 발동 -> 서비스 완전 중단
            micro_available = False
            freeze_scope = 'full_network'
            response_action = 'pause_all'
            
            # 네트워크 혼잡별 복구(Downtime) 시간 부여 (수동 거버넌스보단 빠르지만 상당한 시간 소요)
            service_downtime_sec = random.uniform(60, 300)
            if scenario.network_condition == 'congested':
                service_downtime_sec *= 1.2
            elif scenario.network_condition == 'severe':
                service_downtime_sec *= 1.5

        # 가스 소비량 (표준 자동화) + 과부하 진단 정보
        gas_details: Dict[str, float] = {
            # 탐지 시점의 FPR 및 임계값 기록 (과부하 추적용)
            'applied_fpr': getattr(self, '_last_applied_fpr', self._current_fpr),
            'applied_threshold': getattr(self, '_last_applied_threshold', 0.5),
        }
        if detected_as_attack:
            gas_details.update({
                'signature_verification': 0.0,   # 사전 서명 검증 없음
                'pause': 35000.0,                # 표준 전체 Pause
                'blacklist_addition': 55000.0    # 표준 매핑 업데이트
            })

        return DetectionResponse(
            prediction=prediction,
            latency_ms=latency_ms,
            financial_loss=financial_loss,
            micro_secondary_loss=0.0,
            leaked_tokens=0.0,
            service_downtime_sec=service_downtime_sec,
            downtime_opportunity_cost=self._estimate_downtime_opportunity_cost(
                service_downtime_sec
            ),
            micro_available=micro_available,
            freeze_scope=freeze_scope,
            response_action=response_action,
            gas_details=gas_details
        )
    
    def _run_detection_algorithms(self, scenario: Scenario):
        """
        피처 기반 이상 점수 앙상블 (FPR 연동 동적 임계값 적용)

        [앙상블 구성]
        - AnomalyScorer (60%): 피처 분포 기반 이상 점수
          → 회피/위장 공격은 분포 겹침으로 score 자연 저하
        - 단순 임계값 보조 (40%): 금액 임계값 기반

        [FPR 연동]
        - 과부하 단계 증가 시 정상 트랜잭션에 가우시안 노이즈(σ∝FPR) 주입
        - 동적 임계값: 과부하 심화 시 하향 (민감도↑, FP 폭증)
        """
        # 1. 피처 추출 및 이상 점수
        features      = extract_features(scenario)
        anomaly_score = self._scorer.score(features)

        # 2. 금액 기반 보조 점수 (단일 계층 고유 도메인 지식)
        threshold_score = self._check_simple_threshold(scenario)

        # 3. 앙상블
        avg_score = anomaly_score * 0.60 + threshold_score * 0.40

        # 4. 시스템 불확실성 노이즈 (공격/정상 무관 균일 적용)
        #    FPR 기반 노이즈는 과부하 상태를 모사하되, 레이블 참조 없이 항상 적용
        noise_sigma    = self._current_fpr * 0.5
        overload_noise = float(np.random.normal(loc=0.0, scale=noise_sigma))

        # 5. 시스템 기본 불확실성 노이즈
        base_noise  = float(np.random.normal(0.0, 0.03))
        final_score = float(np.clip(avg_score + base_noise + overload_noise, 0.0, 1.0))

        # 6. 동적 임계값: 과부하 심화 시 하향 → 민감도↑, FP 폭증
        effective_threshold = max(0.50 - (self._current_fpr * 0.3), 0.30)

        self._last_applied_fpr       = self._current_fpr
        self._last_applied_threshold = effective_threshold

        if final_score > effective_threshold:
            return ('ATTACK', self._current_fpr, effective_threshold)
        return ('NORMAL', self._current_fpr, effective_threshold)

    def _check_simple_threshold(self, scenario: Scenario) -> float:
        """
        단순 금액 임계값 검사 (보조 점수)
        금액과 임계값의 비율로부터 연속 점수를 산출.
        임계값 초과 여부가 아닌 비율 기반 → 회피 공격의 소액 거래는 낮은 점수.
        """
        threshold = self.config['mint_threshold']
        amount    = scenario.parameters.get('amount_per_block',
                    scenario.parameters.get('amount_per_wallet',
                    scenario.parameters.get('amount_per_recipient',
                    scenario.parameters.get('start_amount',
                    scenario.parameters.get('amount',
                    scenario.parameters.get('loan_amount',
                    scenario.parameters.get('total_amount', 0)))))))

        ratio = amount / (threshold + 1e-8)
        if ratio > 1.0:
            return float(np.clip(0.5 + 0.4 * (1.0 - 1.0 / ratio), 0.0, 0.95))
        else:
            # 임계값 미만: 비율에 비례하는 낮은 점수
            return float(np.clip(ratio * 0.15, 0.0, 0.15))
