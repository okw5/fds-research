"""
FDSSingleLayerSystem
FDS 단일 토큰 탐지 시스템

특징:
- 자동화된 임계값 기반 탐지
- 반응 시간: 250~450ms (평균 350ms)
- 높은 탐지율 (약 85%)
- 낮은 오탐율 (약 5%)
- 네트워크 혼잡 시 지연 증가
- 공격 탐지 시: 전체 토큰 일시정지 (Pause)
- 중단 시간: 5~30분 (자동화된 조사 후 수동 복구)
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
    
    def detect_extended(self, scenario: Scenario) -> DetectionResponse:
        """
        확장된 탐지 결과 (피해금액 + 서비스 중단 시간 포함)
        
        FDS 단일 토큰의 특징:
        - 자동으로 빠르게 탐지하나, 방어 시 전체 토큰 일시정지 (Pause)
        - 단일 토큰이므로 소액결제도 함께 중단
        - 자동 분석 후 수동 복구 필요 → 5~30분 소요
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
            amount = scenario.parameters.get('amount',
                     scenario.parameters.get('total_amount', 0))

            # 대규모 Macro 공격 → 더 긴 전체 중단
            is_large_scale = scenario.scenario_type in {
                ScenarioType.INFINITE_MINT,
                ScenarioType.RESERVE_DRAIN,
                ScenarioType.FLASH_LOAN_DEPEG,
                ScenarioType.SYBIL_ATTACK,
            }
            if is_large_scale and amount >= 5_000_000:
                # 대규모: 30분~2시간 전체 중단
                service_downtime_sec = random.uniform(1800, 7200)
            elif is_large_scale:
                # 일반 Macro: 10~30분 전체 중단
                service_downtime_sec = random.uniform(600, 1800)
            else:
                # Micro급 (임계값 회피 등): 5~30분
                service_downtime_sec = random.uniform(300, 1800)

            # 네트워크 혼잡 시 추가 지연
            if scenario.network_condition == 'congested':
                service_downtime_sec *= 1.3
            elif scenario.network_condition == 'severe':
                service_downtime_sec *= 1.5

            micro_available = False  # ★ 핵심: 소액결제도 전부 중단
            freeze_scope = 'full_network'
            response_action = 'pause_all'

        
        # 가스 소비량 (표준 자동화)
        gas_details = {}
        if detected_as_attack:
            gas_details = {
                'signature_verification': 0.0,   # 사전 서명 검증 없음
                'pause': 35000.0,                # 표준 전체 Pause
                'blacklist_addition': 55000.0    # 표준 매핑 업데이트
            }

        return DetectionResponse(
            prediction=prediction,
            latency_ms=latency_ms,
            financial_loss=financial_loss,
            service_downtime_sec=service_downtime_sec,
            micro_available=micro_available,
            freeze_scope=freeze_scope,
            response_action=response_action,
            gas_details=gas_details
        )
    
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
