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
        FDS 2계층 탐지 — Macro/Micro 엔진 완전 분리

        [Macro 엔진] - 대형 공격 전담
          사전 서명 검증 포함: 80~160ms (평균 120ms)
          단일계층 Macro 대응과 유사한 속도 (250~450ms 대비 약간 빠름)

        [Micro 엔진] - 소규모 공격 전담, 독립 실행
          경량 처리, 과부하 면역: 40~80ms (평균 60ms)
          단일계층 Micro 대응(875~1575ms)보다 20배 이상 빠름

        → 엔진이 분리되어 있으므로 Micro 처리가 Macro 탐지에 영향 없음
        """
        cfg = self.config
        is_macro = self._is_macro_transaction(scenario)

        if is_macro:
            # Macro 엔진: 사전 서명 검증 포함 → 단일계층과 유사한 속도
            base_latency = cfg['macro_base_latency_ms']
            variance = cfg['macro_latency_variance_ms']
        else:
            # Micro 엔진: 경량 독립 처리 → 시빌·임계회피 공격 초고속 탐지
            base_latency = cfg['micro_base_latency_ms']
            variance = cfg['micro_latency_variance_ms']

        latency_ms = base_latency + random.uniform(-variance, variance)

        # 네트워크 혼잡에도 우선 처리로 영향 최소화 (과부하 면역)
        if scenario.network_condition == 'congested':
            latency_ms *= cfg['congestion_multiplier']
        elif scenario.network_condition == 'severe':
            latency_ms *= cfg['congestion_multiplier'] * 1.2

        # 탐지 알고리즘 실행
        prediction = self._run_two_layer_detection(scenario)

        self._record_detection(latency_ms)
        return (prediction, latency_ms)
    
    def detect_extended(self, scenario: Scenario) -> DetectionResponse:
        """
        확장된 탐지 결과 (피해금액 + 서비스 중단 시간 + Micro 2차 피해 포함)

        ★ FDS 2계층의 핵심 장점을 반영:
        - Macro만 선택적으로 정지 → 소액결제(Micro) 정상 운영 유지
        - 빠른 탐지(80~150ms) → 피해금액 최소화
        - Macro pause 이후에도 이미 발행된 위조 토큰이 Micro망으로 유입
          → micro_secondary_loss 로 2차 피해까지 추적

        [시뮬레이션 흐름]
        1. Macro 탐지 지연(latency_ms) 동안 위조 토큰 누출
        2. Macro pause 발동: Macro 채널 차단
        3. 이미 누출된 위조 토큰 → Micro 채널 유입 → 2차 피해 누적
        4. Micro 이상 탐지 → 지갑 blacklist → 추가 피해 차단
        """
        prediction, latency_ms = self.detect(scenario)
        detected_as_attack = (prediction == 'ATTACK')

        # Macro/Micro 구분
        is_macro = self._is_macro_transaction(scenario)

        # ─── 직접 피해금액 계산 ─────────────────────────────────────────────
        financial_loss = self._estimate_financial_loss(
            scenario, latency_ms, detected_as_attack
        )

        # ─── Micro 2차 피해 계산 ────────────────────────────────────────────
        micro_secondary_loss = 0.0
        leaked_tokens = 0.0

        if detected_as_attack and is_macro and scenario.is_attack():
            attack_amount = float(scenario.parameters.get(
                'amount', scenario.parameters.get(
                    'total_amount', scenario.parameters.get('loan_amount', 0))))

            is_catastrophic = (
                scenario.scenario_type in {
                    ScenarioType.INFINITE_MINT,
                    ScenarioType.RESERVE_DRAIN,
                } and attack_amount >= 5_000_000
            ) or scenario.parameters.get('is_catastrophic', False)

            # Step 1: 탐지 지연 동안 누출된 위조 토큰 양
            #   누출률 = 공격 속도 × 탐지 지연(초)
            latency_sec = latency_ms / 1000.0
            s_type = scenario.scenario_type.value
            velocity = self.ATTACK_VELOCITY.get(s_type, 0.05)
            leak_ratio = min(0.30, velocity * latency_sec)
            leaked_tokens = attack_amount * leak_ratio

            # Step 2: 누출된 위조 토큰 중 Micro망 유입 비율
            #   catastrophic: Micro망으로 30% 흘러듦 (대규모 → 차단 전 이미 유통)
            #   일반 Macro:   Micro망으로 10% 흘러듦
            micro_inflow_ratio = 0.30 if is_catastrophic else 0.10
            micro_inflow_tokens = leaked_tokens * micro_inflow_ratio

            # Step 3: Micro 이상 탐지 후 blacklist → 추가 10%만 최종 손실
            micro_detection_ratio = 0.10  # blacklist 이후 빠져나가는 비율
            token_price_usd = 1.0         # 토큰 단가 $1 가정

            micro_secondary_loss = (
                micro_inflow_tokens * micro_detection_ratio * token_price_usd
            )

        # ─── 서비스 중단 시간 ───────────────────────────────────────────────
        service_downtime_sec = 0.0
        micro_available = True
        freeze_scope = 'none'
        response_action = 'none'

        if detected_as_attack:
            amount = scenario.parameters.get('amount',
                     scenario.parameters.get('total_amount', 0))

            # ── Macro 공격 ─────────────────────────────────────────────────
            if is_macro:
                is_catastrophic_flag = (
                    scenario.scenario_type in {
                        ScenarioType.INFINITE_MINT,
                        ScenarioType.RESERVE_DRAIN,
                        ScenarioType.FLASH_LOAN_DEPEG,
                    } and amount >= 5_000_000
                ) or scenario.parameters.get('is_catastrophic', False)
                is_sybil_large = (
                    scenario.scenario_type == ScenarioType.SYBIL_ATTACK
                    and scenario.parameters.get('num_wallets', 0) >= 50
                )

                if is_catastrophic_flag or is_sybil_large:
                    # 대규모 → 전체 네트워크 중단 불가피 (5~15분)
                    service_downtime_sec = random.uniform(300, 900)
                    freeze_scope = 'full_network'
                    response_action = 'pause_all'
                    micro_available = False
                else:
                    # 일반 Macro → Macro 계층만 정지, Micro 유지 (2~10분)
                    service_downtime_sec = random.uniform(120, 600)
                    micro_available = True  # ★ 소액결제 계속 운영
                    freeze_scope = 'selective'
                    response_action = 'pause_macro'

            # ── Micro 공격 ─────────────────────────────────────────────────
            else:
                # 해당 지갑만 동결, 서비스 중단 최소화 (0.5~30초)
                service_downtime_sec = random.uniform(0.5, 30)
                micro_available = True
                freeze_scope = 'selective'
                response_action = 'freeze_wallet'

            # 네트워크 혼잡 시 추가 지연
            if scenario.network_condition == 'congested':
                service_downtime_sec *= 1.1
            elif scenario.network_condition == 'severe':
                service_downtime_sec *= 1.2

        # ─── 가스 소비량 (2계층 최적화) ────────────────────────────────────
        gas_details = {}
        if detected_as_attack:
            gas_details = {
                'signature_verification': 21000.0,  # Macro 전용 사전 서명 검증
                'pause': 18000.0,                   # 선택적 Pause (최적화)
                'blacklist_addition': 32000.0        # 효율적 매핑 관리
            }

        return DetectionResponse(
            prediction=prediction,
            latency_ms=latency_ms,
            financial_loss=financial_loss,
            micro_secondary_loss=micro_secondary_loss,
            leaked_tokens=leaked_tokens,
            service_downtime_sec=service_downtime_sec,
            downtime_opportunity_cost=0.0,  # 2계층은 선택적 pause → 기회비용 최소
            micro_available=micro_available,
            freeze_scope=freeze_scope,
            response_action=response_action,
            gas_details=gas_details
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
        
        # 현실적인 불확실성 반영 (멤풀 재조합, 오프체인 검증 지연 등)
        noise = random.uniform(-0.08, 0.08)
        final_score = weighted_score + noise
        
        # 100% 탐지는 비현실적이므로, 현실 세계의 오탐/미탐 한계 반영
        if scenario.is_attack() and random.random() < 0.008: 
            return 'NORMAL'  # 0.8% 확률로 미탐 (정교한 공격 통과)
        if not scenario.is_attack() and random.random() < 0.002: 
            return 'ATTACK'  # 0.2% 확률로 오탐 (특이한 정상 거래를 공격으로 오인)
        
        if final_score > 0.48:  # 민감도 약간 조정
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
                # 정교하게 분산된 회피 공격의 2.5%는 미탐 (현실적인 맹점 반영)
                if random.random() < 0.025:
                    return 'NORMAL'
                return 'ATTACK'
        
        if scenario.is_attack():
            # 다른 종류의 소액 공격은 약간의 확률적 탐지 실패 포함
            if random.random() > 0.03:  # 97% 탐지 (기존보다 높지만, 100%는 아님)
                return 'ATTACK'
        else:
            # 봇/플래시봇 트래픽 등 소규모의 특이 정상 거래 패턴에서 오탐 발생
            if random.random() < 0.003:  # 0.3% 확률로 오탐
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
