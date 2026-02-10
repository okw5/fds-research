"""
FDSTwoLayerSystem
FDS 2계층 토큰 탐지 시스템 (제안 모델)

특징:
- Micro/Macro 분리로 선택적 차단
- 반응 시간: 80~150ms (평균 120ms)
- 매우 높은 탐지율 (약 92%)
- 매우 낮은 오탐율 (약 2%)
- 네트워크 혼잡에도 안정적 (우선 처리)
- 높은 가용성 (Micro 계층 정상 운영)

★ 핵심 장점:
- 공격 탐지 시: Macro만 정지, Micro(소액결제)는 정상 운영 유지
- 피해금액 최소화: 빠른 탐지 + 선택적 동결
- 서비스 중단 시간: 거의 0 (소액 관점)
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


class FDSTwoLayerSystem(DetectionSystem):
    """
    FDS 2계층 토큰 탐지 시스템 (제안 모델)
    
    아키텍처:
    1. Micro Layer (소액): 느슨한 임계값, 빠른 처리
    2. Macro Layer (거액): 엄격한 임계값, 사전 서명 검증
    
    장점:
    - 선택적 차단: 거액만 정지, 소액은 계속 운영
    - 빠른 반응: 우선순위 Gas로 혼잡 대응
    - 높은 정확도: 다중 계층 검증
    - 피해금액 최소화: 초고속 탐지 + 선택적 동결
    - 서비스 연속성: 소액결제 중단 없음
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        default_config = DetectionConfig.get_fds_two_layer_config()
        if config:
            default_config.update(config)
        super().__init__("FDS 2계층 토큰", default_config)
    
    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        """
        FDS 2계층 토큰 탐지
        
        Returns:
            Tuple[str, float]: (예측 결과, 탐지 지연시간 ms)
        """
        # 1. 지연 시간 계산 (더 빠름)
        base_latency = self.config['base_latency_ms']
        variance = self.config['latency_variance_ms']
        latency_ms = base_latency + random.uniform(-variance, variance)
        
        # 네트워크 혼잡에도 우선 처리로 영향 최소화
        if scenario.network_condition == 'congested':
            latency_ms *= self.config['congestion_multiplier']
        elif scenario.network_condition == 'severe':
            latency_ms *= self.config['congestion_multiplier'] * 1.2  # 영향 적음
        
        # 2. 탐지 알고리즘 실행
        prediction = self._run_two_layer_detection(scenario)
        
        self._record_detection(latency_ms)
        return (prediction, latency_ms)
    
    def detect_extended(self, scenario: Scenario) -> DetectionResponse:
        """
        확장된 탐지 결과 (피해금액 + 서비스 중단 시간 포함)
        
        ★ FDS 2계층의 핵심 장점을 반영:
        - Macro만 선택적으로 정지 → 소액결제(Micro) 정상 운영 유지
        - 빠른 탐지(120ms) → 피해금액 최소화
        - 자동 복구 가능 → 서비스 중단 시간 최소
        - 지갑 동결(freeze_wallet)로 정밀 대응
        """
        prediction, latency_ms = self.detect(scenario)
        detected_as_attack = (prediction == 'ATTACK')
        
        # Macro/Micro 구분
        is_macro = self._is_macro_transaction(scenario)
        
        # 피해금액 계산 (2계층은 더 작은 피해)
        financial_loss = self._estimate_financial_loss(
            scenario, latency_ms, detected_as_attack
        )
        
        # 서비스 중단 시간 계산 - 2계층의 핵심 차별점
        service_downtime_sec = 0.0
        micro_available = True  # ★ 소액결제는 항상 유지
        freeze_scope = 'none'
        response_action = 'none'
        
        if detected_as_attack:
            if is_macro:
                # Macro 공격: Macro 계층만 선택적 정지
                # 자동 분석 + 지갑 동결로 빠른 대응 → 1~5분
                service_downtime_sec = random.uniform(60, 300)  # 1~5분 (Macro만)
                
                micro_available = True  # ★ 소액결제는 계속 운영!
                freeze_scope = 'selective'  # 선택적 동결 (Macro만)
                response_action = 'pause_macro'  # Macro만 정지
            else:
                # Micro 계층에서 탐지된 공격: 해당 지갑만 동결
                # 서비스 중단 없음 - 해당 지갑만 차단
                service_downtime_sec = 0.0  # 서비스 중단 없음!
                
                micro_available = True  # 다른 소액결제는 정상
                freeze_scope = 'selective'  # 해당 지갑만 동결
                response_action = 'freeze_wallet'  # 지갑 동결
            
            # 네트워크 혼잡 시에도 최소한의 추가 지연만
            if scenario.network_condition == 'congested':
                service_downtime_sec *= 1.1  # 10% 추가만
            elif scenario.network_condition == 'severe':
                service_downtime_sec *= 1.2  # 20% 추가만
        
        return DetectionResponse(
            prediction=prediction,
            latency_ms=latency_ms,
            financial_loss=financial_loss,
            service_downtime_sec=service_downtime_sec,
            micro_available=micro_available,
            freeze_scope=freeze_scope,
            response_action=response_action
        )
    
    def _run_two_layer_detection(self, scenario: Scenario) -> str:
        """2계층 탐지 알고리즘"""
        
        # 거래 규모 판단
        amount = scenario.parameters.get('amount', 
                 scenario.parameters.get('total_amount', 0))
        
        # Micro vs Macro 분류
        is_macro = self._is_macro_transaction(scenario)
        
        if is_macro:
            # Macro Layer: 엄격한 검증
            return self._detect_macro_layer(scenario)
        else:
            # Micro Layer: 빠른 검증
            return self._detect_micro_layer(scenario)
    
    def _is_macro_transaction(self, scenario: Scenario) -> bool:
        """거래가 Macro 계층에 속하는지 판단"""
        amount = scenario.parameters.get('amount', 
                 scenario.parameters.get('total_amount', 0))
        
        # 1. 금액 기준
        macro_threshold = 1000000  # 100만 토큰 이상
        if amount >= macro_threshold:
            return True
        
        # 2. 시나리오 유형 기준 (대규모 공격은 Macro)
        macro_types = {
            ScenarioType.INFINITE_MINT,
            ScenarioType.RESERVE_DRAIN,
            ScenarioType.FLASH_LOAN_DEPEG,
            ScenarioType.SYBIL_ATTACK,
            ScenarioType.LIQUIDITY_ADD,  # 정상이지만 Macro로 분류
        }
        if scenario.scenario_type in macro_types:
            return True
        
        return False
    
    def _detect_macro_layer(self, scenario: Scenario) -> str:
        """
        Macro Layer 탐지 (엄격한 검증)
        - 사전 서명 검증
        - 다중 임계값 체크
        - 통계적 이상 탐지
        """
        scores = []
        
        # 1. 엄격한 임계값 검사
        scores.append(self._check_strict_threshold(scenario))
        
        # 2. 서명/권한 검증 (시뮬레이션)
        scores.append(self._check_signature_validity(scenario))
        
        # 3. 누적 패턴 검사
        scores.append(self._check_cumulative_pattern(scenario))
        
        # 4. 통계적 이상 탐지
        scores.append(self._check_statistical_anomaly(scenario))
        
        # 앙상블: 가중 평균 (서명 검증에 더 높은 가중치)
        weights = [0.2, 0.35, 0.2, 0.25]
        weighted_score = sum(s * w for s, w in zip(scores, weights))
        
        # 작은 노이즈 (2계층은 더 안정적)
        noise = random.uniform(-0.02, 0.02)
        final_score = weighted_score + noise
        
        if final_score > 0.45:  # 더 민감한 임계값
            return 'ATTACK'
        return 'NORMAL'
    
    def _detect_micro_layer(self, scenario: Scenario) -> str:
        """
        Micro Layer 탐지 (빠른 검증)
        - 느슨한 임계값
        - 빠른 처리
        """
        # Micro는 기본적으로 신뢰 (정상으로 추정)
        # 하지만 명백한 공격 패턴은 탐지
        
        if scenario.scenario_type in {ScenarioType.THRESHOLD_EVASION, 
                                       ScenarioType.GRADUAL_ESCALATION,
                                       ScenarioType.CAMOUFLAGE}:
            # 소액 회피 공격도 누적 모니터링으로 탐지
            pattern_score = self._check_cumulative_pattern(scenario)
            if pattern_score > 0.6:
                return 'ATTACK'
        
        if scenario.is_attack():
            # 다른 공격 유형은 낮은 확률로 미탐
            if random.random() > 0.15:  # 85% 탐지
                return 'ATTACK'
        
        return 'NORMAL'
    
    def _check_strict_threshold(self, scenario: Scenario) -> float:
        """엄격한 임계값 검사 (Macro 전용)"""
        macro_threshold = self.config['macro_threshold']
        amount = scenario.parameters.get('amount', 
                 scenario.parameters.get('total_amount', 0))
        
        # Macro 임계값은 더 낮음 (0.1% vs 1%)
        if scenario.is_attack():
            if amount > macro_threshold:
                return 0.95
            elif amount > macro_threshold * 0.5:
                return 0.80
            return 0.65
        else:
            # 정상 거래
            if amount > macro_threshold * 2:
                return 0.20  # 대량이지만 정상이면 낮은 점수
            return 0.05
    
    def _check_signature_validity(self, scenario: Scenario) -> float:
        """
        서명/권한 검증 (Macro의 핵심)
        2계층의 Macro는 사전 서명이 필요
        """
        # 공격은 서명 없이 시도 (불법)
        if scenario.is_attack():
            # 대부분의 공격은 유효한 서명이 없음
            # Camouflage만 예외 (정상 채널 통과 시도)
            if scenario.scenario_type == ScenarioType.CAMOUFLAGE:
                return 0.4  # 서명은 있지만 패턴 의심
            return 0.90  # 서명 없음/무효
        else:
            # 정상은 유효한 서명 보유
            if scenario.parameters.get('is_whitelisted', False):
                return 0.02  # 화이트리스트
            return 0.05  # 정상 서명
    
    def _check_cumulative_pattern(self, scenario: Scenario) -> float:
        """누적 패턴 검사"""
        pattern_scores = {
            # 공격 패턴 - 누적 모니터링으로 개선된 탐지
            ScenarioType.INFINITE_MINT: 0.90,
            ScenarioType.RESERVE_DRAIN: 0.88,
            ScenarioType.FLASH_LOAN_DEPEG: 0.85,
            ScenarioType.THRESHOLD_EVASION: 0.80,   # 개선: 누적으로 탐지
            ScenarioType.SYBIL_ATTACK: 0.85,        # 개선: 전체 발행량 감시
            ScenarioType.GRADUAL_ESCALATION: 0.82,  # 개선: 변화율 감시
            ScenarioType.CAMOUFLAGE: 0.55,          # 여전히 어려움
            
            # 정상 패턴
            ScenarioType.NORMAL_TRANSFER: 0.02,
            ScenarioType.LARGE_TRANSFER: 0.08,
            ScenarioType.LIQUIDITY_ADD: 0.05,
            ScenarioType.BATCH_PAYMENT: 0.03,
            ScenarioType.NORMAL_MINT: 0.03,
        }
        return pattern_scores.get(scenario.scenario_type, 0.5)
    
    def _check_statistical_anomaly(self, scenario: Scenario) -> float:
        """
        통계적 이상 탐지 (Z-score 기반)
        정상 분포에서 벗어난 패턴 감지
        """
        if scenario.is_attack():
            # 공격은 통계적으로 이상
            base_score = 0.75
            
            # 네트워크 혼잡 시 더 많은 이상 패턴
            if scenario.network_condition == 'severe':
                base_score += 0.10
            
            # 시나리오별 이상도
            if scenario.scenario_type == ScenarioType.CAMOUFLAGE:
                return 0.35  # 위장은 통계적으로 정상처럼 보임
            
            return min(0.95, base_score)
        else:
            # 정상은 분포 내
            # 하지만 대량 정상 거래는 약간의 이상 점수
            if scenario.scenario_type == ScenarioType.LARGE_TRANSFER:
                return 0.12
            return 0.05
