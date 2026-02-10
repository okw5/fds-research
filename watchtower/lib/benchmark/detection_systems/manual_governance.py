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
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scenario import Scenario, ScenarioType, ScenarioLabel


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
    
    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        """
        수동 거버넌스 탐지 시뮬레이션
        
        Returns:
            Tuple[str, float]: (예측 결과, 탐지 지연시간 ms)
        """
        # 1. 반응 시간 시뮬레이션
        latency_ms = random.uniform(
            self.config['response_delay_min_ms'],
            self.config['response_delay_max_ms']
        )
        
        # 네트워크 혼잡 시 추가 지연 (담당자가 상황 파악하는 데 시간 소요)
        if scenario.network_condition == 'congested':
            latency_ms *= 1.3
        elif scenario.network_condition == 'severe':
            latency_ms *= 1.8
        
        # 2. 탐지 정확도 시뮬레이션
        prediction = self._simulate_human_detection(scenario)
        
        self._record_detection(latency_ms)
        return (prediction, latency_ms)
    
    def detect_extended(self, scenario: Scenario) -> DetectionResponse:
        """
        확장된 탐지 결과 (피해금액 + 서비스 중단 시간 포함)
        
        수동 거버넌스의 특징:
        - 탐지 시 전체 네트워크 긴급 정지 (Emergency Pause)
        - 조사 + 복구에 30~120분 소요
        - 소액결제도 전부 중단
        - 느린 반응으로 피해금액 큼
        """
        prediction, latency_ms = self.detect(scenario)
        detected_as_attack = (prediction == 'ATTACK')
        
        # 피해금액 계산
        financial_loss = self._estimate_financial_loss(
            scenario, latency_ms, detected_as_attack
        )
        
        # 서비스 중단 시간 계산
        service_downtime_sec = 0.0
        micro_available = True
        freeze_scope = 'none'
        response_action = 'none'
        
        if detected_as_attack:
            # 수동 거버넌스: 공격 탐지 시 전체 네트워크 긴급 정지
            # 조사에 30~120분(1800~7200초) 소요
            service_downtime_sec = random.uniform(1800, 7200)  # 30분~2시간
            
            # 네트워크 혼잡 시 복구 시간 추가
            if scenario.network_condition == 'congested':
                service_downtime_sec *= 1.3
            elif scenario.network_condition == 'severe':
                service_downtime_sec *= 1.8
            
            micro_available = False  # 소액결제도 전부 중단
            freeze_scope = 'full_network'  # 전체 네트워크 동결
            response_action = 'pause_all'  # 전체 정지
        
        return DetectionResponse(
            prediction=prediction,
            latency_ms=latency_ms,
            financial_loss=financial_loss,
            service_downtime_sec=service_downtime_sec,
            micro_available=micro_available,
            freeze_scope=freeze_scope,
            response_action=response_action
        )
    
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
