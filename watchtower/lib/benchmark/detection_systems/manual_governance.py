"""
ManualGovernanceSystem
기존 수동 거버넌스 방식 시뮬레이션 (Baseline)

특징:
- 인간이 모니터링하고 판단하는 방식
- 반응 시간: 3500~6000ms (평균 5000ms)
- 탐지 정확도: 약 70% (피로, 주의력 한계)
- 오탐율: 약 15%
- 공격 탐지 시: 전체 네트워크 긴급 정지 (전체 서비스 중단)
- 중단 시간: 30~120분 (조사 + 복구)
"""

import random
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


class ManualGovernanceSystem(DetectionSystem):
    """
    기존 수동 거버넌스 시스템 시뮬레이션
    
    가정:
    1. 담당자가 알림을 받고 확인하는 데 1-2초
    2. 상황을 판단하고 결정하는 데 2-3초
    3. 조치를 실행하는 데 0.5-1초
    총: 3.5-6초 (평균 ~5초)
    
    한계:
    - 인간 피로도로 인한 탐지 실패 (약 30%)
    - 주의력 분산으로 인한 오탐 (약 15%)
    - 복잡한 공격 패턴 인식 어려움
    - 공격 대응 시 전체 네트워크 중단 (30~120분)
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        default_config = DetectionConfig.get_manual_governance_config()
        if config:
            default_config.update(config)
        super().__init__("기존 수동 거버넌스", default_config)
        # 단일 계층과 동일한 엔진 로드를 위해 AnomalyScorer 초기화
        self._scorer = AnomalyScorer(method=default_config.get('anomaly_method', 'zscore'))
        
        # 공정 비교를 위해 FPR 변수 유지
        self._current_fpr = default_config['false_positive_rate']
    
    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        """
        수동 거버넌스 탐지 시뮬레이션 — 4단계 인간 워크플로우

        ① 알림 수신·확인 (30~120s): 담당자가 알림 인지
        ② 상황 판단·승인 (120~600s): 심각도 평가, 대응 결정
           → 복잡한 공격(시빌·플래시론)은 difficulty 배수로 추가 지연
        latency_ms = (①+②) × 1000
        """
        cfg = self.config

        # ① 알림 수신~확인
        alert_sec = random.uniform(
            cfg['alert_notice_min_sec'], cfg['alert_notice_max_sec']
        )

        # ② 상황 판단·승인 — 공격 유형 복잡도 반영
        # 단순(무한발행·준비금탈취): 1.0× / 복잡(시빌·플래시론): 1.5× / 위장형: 2.0×
        complexity_multiplier = {
            ScenarioType.INFINITE_MINT:    1.0,
            ScenarioType.RESERVE_DRAIN:    1.1,
            ScenarioType.FLASH_LOAN_DEPEG: 1.5,
            ScenarioType.SYBIL_ATTACK:     1.8,  # 분산 공격 → 판단 어려움
            ScenarioType.THRESHOLD_EVASION: 2.0,  # 소액 위장 → 탐지 가장 어려움
        }.get(scenario.scenario_type, 1.0)

        assess_sec = random.uniform(
            cfg['situation_assess_min_sec'], cfg['situation_assess_max_sec']
        ) * complexity_multiplier

        # 네트워크 혼잡도 적용 (Log-Normal 분포, v4)
        base_latency_ms = (alert_sec + assess_sec) * 1000.0
        latency_ms = self._apply_congestion_latency(base_latency_ms, scenario.network_condition)

        # 탐지 정확도 (단일 계층과 동일한 통계 피처 연산 알고리즘 사용)
        prediction, applied_fpr, applied_threshold = self._run_detection_algorithms(scenario)

        self._record_detection(latency_ms)
        self._last_applied_fpr = applied_fpr
        self._last_applied_threshold = applied_threshold
        return (prediction, latency_ms)
    
    def detect_extended(self, scenario: Scenario) -> DetectionResponse:
        """
        확장된 탐지 결과 (피해금액 + 서비스 중단 시간 포함)

        수동 거버넌스 전체 타임라인:
        ─────────────────────────────────────────────────────────────
        ① 알림 수신 (30~120s)   ┐
        ② 상황 판단 (2~12min)   ┘ → latency_ms (탐지까지)
        ③ 컨트랙트 pause (1~5min)  ┐
        ④ 조사·복구 (15~60min)     ┘ → service_downtime_sec
        ─────────────────────────────────────────────────────────────
        총 사고 대응 시간: latency/60 + downtime/60 = 약 30~80분
        """
        prediction, latency_ms = self.detect(scenario)
        detected_as_attack = (prediction == 'ATTACK')

        # 피해금액 (긴 latency → 지수 모델에서 피해 최대)
        financial_loss = self._estimate_financial_loss(
            scenario, latency_ms, detected_as_attack
        )

        service_downtime_sec = 0.0
        micro_available = True
        freeze_scope = 'none'
        response_action = 'none'

        if detected_as_attack:
            # 수동 거버넌스 한계: 인간 판단 후 전체 정지(pause_all) 발동
            micro_available = False
            freeze_scope = 'full_network'
            response_action = 'pause_all'
            
            # 수동 복구로 인해 매우 긴 Downtime 발생
            service_downtime_sec = random.uniform(600, 3600)
            if scenario.network_condition == 'congested':
                service_downtime_sec *= 1.5
            elif scenario.network_condition == 'severe':
                service_downtime_sec *= 2.0
        
        # 가스 소비량 (수동 대응 오버헤드 - Pause Call)
        gas_details = {}
        if detected_as_attack:
            gas_details = {
                'signature_verification': 0.0,
                'pause': 18000.0,
                'blacklist_addition': 65000.0
            }

        return DetectionResponse(
            prediction=prediction,
            latency_ms=latency_ms,
            financial_loss=financial_loss,
            micro_secondary_loss=0.0,   # 수동거버넌스: 전체 pause → Micro 2차 피해 없음
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
    
    def _run_detection_algorithms(self, scenario: Scenario) -> Tuple[str, float, float]:
        """
        단일 계층과 정확히 동일한 알고리즘을 수행합니다. 
        차이는 레이턴시(속도)에만 있습니다.
        """
        import numpy as np
        cfg = self.config

        # 1) 피처 추출 및 통계적 이상 점수 (60% 비중)
        features = extract_features(scenario)
        anomaly_score = self._scorer.score(features)

        # 2) 단일 토큰 검증 로직 점수 (40% 비중)
        threshold_score = self._check_simple_threshold(scenario)

        # 3) 앙상블
        avg_score = anomaly_score * 0.60 + threshold_score * 0.40

        # 4) FPR 연동 노이즈 (공격/정상 무관 균일 적용 — Data Leakage 제거)
        noise_sigma    = self._current_fpr * 0.5
        overload_noise = float(np.random.normal(loc=0.0, scale=noise_sigma))

        # 5) 시스템 기본 불확실성 노이즈
        base_noise  = float(np.random.normal(0.0, 0.03))
        final_score = float(np.clip(avg_score + base_noise + overload_noise, 0.0, 1.0))

        # 6) 동적 임계값: 단일 계층과 동일 (기본 FPR에 의존)
        effective_threshold = max(0.50 - (self._current_fpr * 0.3), 0.30)

        if final_score > effective_threshold:
            return ('ATTACK', self._current_fpr, effective_threshold)
        return ('NORMAL', self._current_fpr, effective_threshold)

    def _check_simple_threshold(self, scenario: Scenario) -> float:
        """
        단순 금액 임계값 검사 (단일 계층과 동일)
        """
        import numpy as np
        threshold = self.config.get('mint_threshold', 10000)  # 수동거버넌스에 없으면 기본값
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
            return float(np.clip(ratio * 0.15, 0.0, 0.15))

    def _simulate_human_detection(self, scenario: Scenario) -> str:
        """인간 탐지 능력 시뮬레이션"""
        actual_is_attack = scenario.is_attack()
        detection_accuracy = self.config['detection_accuracy']
        fpr = self.config['false_positive_rate']
        
        # 시나리오 유형별 탐지 난이도 조정
        difficulty_modifier = self._get_difficulty_modifier(scenario)
        adjusted_accuracy = detection_accuracy * difficulty_modifier
        
        if actual_is_attack:
            # 실제 공격인 경우
            if random.random() < adjusted_accuracy:
                return 'ATTACK'  # True Positive
            else:
                return 'NORMAL'  # False Negative (미탐)
        else:
            # 정상인 경우
            if random.random() < fpr:
                return 'ATTACK'  # False Positive (오탐)
            else:
                return 'NORMAL'  # True Negative
    
    def _get_difficulty_modifier(self, scenario: Scenario) -> float:
        """
        시나리오 유형별 탐지 난이도 계수 반환
        1.0 = 표준, < 1.0 = 탐지 어려움, > 1.0 = 탐지 쉬움
        """
        difficulty_map = {
            # 공격 - Flash Attack은 탐지 쉬움, 위장 공격은 어려움
            ScenarioType.INFINITE_MINT: 1.1,        # 명확한 패턴
            ScenarioType.RESERVE_DRAIN: 1.0,        # 표준
            ScenarioType.FLASH_LOAN_DEPEG: 0.9,     # 복잡한 메커니즘
            ScenarioType.THRESHOLD_EVASION: 0.6,    # 임계값 회피 - 어려움
            ScenarioType.SYBIL_ATTACK: 0.5,         # 분산 - 매우 어려움
            ScenarioType.GRADUAL_ESCALATION: 0.7,   # 점진적 - 어려움
            ScenarioType.CAMOUFLAGE: 0.4,           # 위장 - 매우 어려움
            
            # 정상 - 대량 거래는 오탐 가능성 약간 높음
            ScenarioType.NORMAL_TRANSFER: 1.0,
            ScenarioType.LARGE_TRANSFER: 0.9,       # 대량이라 의심
            ScenarioType.LIQUIDITY_ADD: 0.95,
            ScenarioType.BATCH_PAYMENT: 1.0,
            ScenarioType.NORMAL_MINT: 1.0,
        }
        return difficulty_map.get(scenario.scenario_type, 1.0)
