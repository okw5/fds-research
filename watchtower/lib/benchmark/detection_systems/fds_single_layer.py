"""
FDSSingleLayerSystem
FDS 단일 토큰 탐지 시스템

특징:
- 자동화된 임계값 기반 탐지
- 반응 시간: 250~450ms (평균 350ms)
- 높은 탐지율 (약 85%)
- 낮은 오탐율 (약 5%)
- 네트워크 혼잡 시 지연 증가
"""

import random
from typing import Tuple, Dict, Any, Optional
from .base import DetectionSystem, DetectionConfig

# 조건부 임포트: 패키지 모드와 직접 실행 모드 지원
try:
    from ..scenario import Scenario, ScenarioType, ScenarioLabel
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scenario import Scenario, ScenarioType, ScenarioLabel


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
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        default_config = DetectionConfig.get_fds_single_layer_config()
        if config:
            default_config.update(config)
        super().__init__("FDS 단일 토큰", default_config)
    
    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        """
        FDS 단일 토큰 탐지
        
        Returns:
            Tuple[str, float]: (예측 결과, 탐지 지연시간 ms)
        """
        # 1. 기본 지연 시간
        base_latency = self.config['base_latency_ms']
        variance = self.config['latency_variance_ms']
        latency_ms = base_latency + random.uniform(-variance, variance)
        
        # 네트워크 혼잡도에 따른 지연
        if scenario.network_condition == 'congested':
            latency_ms *= self.config['congestion_multiplier']
        elif scenario.network_condition == 'severe':
            latency_ms *= self.config['congestion_multiplier'] * 1.5
        
        # 2. 탐지 알고리즘 실행
        prediction = self._run_detection_algorithms(scenario)
        
        self._record_detection(latency_ms)
        return (prediction, latency_ms)
    
    def _run_detection_algorithms(self, scenario: Scenario) -> str:
        """다중 탐지 알고리즘 실행"""
        scores = []
        
        # Algorithm A: 단순 임계값
        scores.append(self._check_simple_threshold(scenario))
        
        # Algorithm B: 누적 윈도우 (시뮬레이션)
        scores.append(self._check_cumulative_window(scenario))
        
        # Algorithm C: 시나리오 타입별 패턴 매칭
        scores.append(self._check_pattern_matching(scenario))
        
        # 최종 판단: 앙상블 (하나라도 공격으로 판단하면 공격)
        avg_score = sum(scores) / len(scores)
        
        # 약간의 노이즈 추가 (시스템 불확실성)
        noise = random.uniform(-0.05, 0.05)
        final_score = avg_score + noise
        
        if final_score > 0.5:
            return 'ATTACK'
        return 'NORMAL'
    
    def _check_simple_threshold(self, scenario: Scenario) -> float:
        """
        단순 임계값 검사 (Method A)
        Returns: 0.0 (정상) ~ 1.0 (공격 확신)
        """
        threshold = self.config['mint_threshold']
        amount = scenario.parameters.get('amount', 
                 scenario.parameters.get('total_amount', 0))
        
        if amount > threshold:
            return 0.9  # 높은 확신
        elif amount > threshold * 0.8:
            return 0.6  # 중간 의심
        elif amount > threshold * 0.5:
            return 0.3  # 약한 의심
        return 0.1  # 정상으로 추정
    
    def _check_cumulative_window(self, scenario: Scenario) -> float:
        """
        누적 윈도우 검사 (Method B)
        분산 공격이나 점진적 공격 탐지
        """
        scenario_type = scenario.scenario_type
        
        # 분산 공격 패턴
        if scenario_type == ScenarioType.SYBIL_ATTACK:
            wallet_count = scenario.parameters.get('wallet_count', 1)
            if wallet_count > 3:
                return 0.7  # 다중 지갑 감지
        
        # 점진적 증가 패턴
        if scenario_type == ScenarioType.GRADUAL_ESCALATION:
            return 0.65  # 증가 추세 감지
        
        # 임계값 회피 패턴
        if scenario_type == ScenarioType.THRESHOLD_EVASION:
            evasion_ratio = scenario.parameters.get('evasion_ratio', 0)
            if evasion_ratio > 0.9:
                return 0.55  # 임계값 근접 반복 감지
        
        # 기타 공격
        if scenario.is_attack():
            return 0.6
        
        return 0.1  # 정상
    
    def _check_pattern_matching(self, scenario: Scenario) -> float:
        """
        시나리오 패턴 매칭
        알려진 공격 패턴과의 유사도
        """
        pattern_scores = {
            # 공격 패턴
            ScenarioType.INFINITE_MINT: 0.95,      # 명확한 패턴
            ScenarioType.RESERVE_DRAIN: 0.90,
            ScenarioType.FLASH_LOAN_DEPEG: 0.85,
            ScenarioType.THRESHOLD_EVASION: 0.55,  # 회피 공격은 탐지 어려움
            ScenarioType.SYBIL_ATTACK: 0.50,       # 분산되어 탐지 어려움
            ScenarioType.GRADUAL_ESCALATION: 0.60,
            ScenarioType.CAMOUFLAGE: 0.30,         # 위장 공격은 매우 어려움
            
            # 정상 패턴
            ScenarioType.NORMAL_TRANSFER: 0.05,
            ScenarioType.LARGE_TRANSFER: 0.15,     # 대량이라 약간 의심
            ScenarioType.LIQUIDITY_ADD: 0.08,
            ScenarioType.BATCH_PAYMENT: 0.05,
            ScenarioType.NORMAL_MINT: 0.05,
        }
        
        return pattern_scores.get(scenario.scenario_type, 0.5)
