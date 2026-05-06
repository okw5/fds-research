"""
FDSTwoLayerSystem
FDS 2계층 토큰 탐지 시스템 (제안 모델)

특징:
- Micro/Macro 분리로 선택적 차단
- 반응 시간: 80~150ms (평균 120ms)
- 하드코딩 확률 상수 제거, 피처 기반 통계 이상 점수 사용
- 회피/위장 공격의 미탐은 분포 겹침으로 데이터에 의해 자연 발생
- 네트워크 혼잡에도 안정적 (우선 처리)
- 높은 가용성 (Micro 계층 정상 운영)

★ 핵심 장점:
- 공격 탐지 시: Macro만 정지, Micro(소액결제)는 정상 운영 유지
- 피해금액 최소화: 빠른 탐지 + 선택적 동결
- 서비스 중단 시간: 거의 0 (소액 관점)
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


class FDSTwoLayerSystem(DetectionSystem):
    """
    FDS 2계층 토큰 탐지 시스템 (제안 모델)

    아키텍처:
    1. Macro Layer (거액): 엄격한 다중 검증, 피처 기반 이상 점수
    2. Micro Layer (소액): 경량 독립 처리, 별도 이상 점수 임계값

    하드코딩 제거 내역:
    - 기존: random.random() < 0.008 (0.8% 미탐 강제), < 0.002 (0.2% 오탐 강제) 등
    - 변경: AnomalyScorer가 피처 분포에 따라 미탐/오탐 확률을 데이터로 결정
    - 기존: _check_cumulative_pattern의 고정 점수 딕셔너리 (0.55, 0.85 등)
    - 변경: extract_features + AnomalyScorer.score() 로 대체
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        default_config = DetectionConfig.get_fds_two_layer_config()
        if config:
            default_config.update(config)
        super().__init__("FDS 2계층 토큰", default_config)

        # 이상 점수 산출기 — config에서 방식 선택: 'zscore'(기본) or 'gmm'
        anomaly_method = default_config.get('anomaly_method', 'zscore')
        self._scorer = AnomalyScorer(method=anomaly_method)

    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        """
        FDS 2계층 탐지 — Macro/Micro 엔진 완전 분리

        [Macro 엔진] - 대형 공격 전담
          사전 서명 검증 포함: 80~160ms (평균 120ms)

        [Micro 엔진] - 소규모 공격 전담, 독립 실행
          경량 처리, 과부하 면역: 40~80ms (평균 60ms)
        """
        cfg = self.config
        is_macro = self._is_macro_transaction(scenario)

        if is_macro:
            base_latency = cfg['macro_base_latency_ms']
            variance     = cfg['macro_latency_variance_ms']
        else:
            base_latency = cfg['micro_base_latency_ms']
            variance     = cfg['micro_latency_variance_ms']

        latency_ms = base_latency + random.uniform(-variance, variance)

        # 네트워크 혼잡도 적용 (Log-Normal 분포, v4)
        latency_ms = self._apply_congestion_latency(latency_ms, scenario.network_condition)

        prediction = self._run_two_layer_detection(scenario)

        self._record_detection(latency_ms)
        return (prediction, latency_ms)

    def detect_extended(self, scenario: Scenario) -> DetectionResponse:
        """
        확장된 탐지 결과 (피해금액 + 서비스 중단 시간 + Micro 2차 피해 포함)

        ★ FDS 2계층의 핵심 장점을 반영:
        - Macro만 선택적으로 정지 → 소액결제(Micro) 정상 운영 유지
        - 빠른 탐지(80~150ms) → 피해금액 최소화
        """
        prediction, latency_ms = self.detect(scenario)
        detected_as_attack = (prediction == 'ATTACK')

        is_macro = self._is_macro_transaction(scenario)

        financial_loss = self._estimate_financial_loss(
            scenario, latency_ms, detected_as_attack
        )

        # Micro 2차 피해 계산
        micro_secondary_loss = 0.0
        leaked_tokens = 0.0

        if detected_as_attack and is_macro and scenario.is_attack():
            attack_amount = float(scenario.parameters.get('amount_per_block',
                                  scenario.parameters.get('amount_per_wallet',
                                  scenario.parameters.get('amount_per_recipient',
                                  scenario.parameters.get('start_amount',
                                  scenario.parameters.get('amount',
                                  scenario.parameters.get('loan_amount',
                                  scenario.parameters.get('total_amount', 0))))))))

            is_catastrophic = (
                scenario.scenario_type in {
                    ScenarioType.INFINITE_MINT,
                    ScenarioType.RESERVE_DRAIN,
                } and attack_amount >= 5_000_000
            ) or scenario.parameters.get('is_catastrophic', False)

            latency_sec = latency_ms / 1000.0
            s_type   = scenario.scenario_type.value
            velocity = self.ATTACK_VELOCITY.get(s_type, 0.05)
            leak_ratio    = min(0.30, velocity * latency_sec)
            leaked_tokens = attack_amount * leak_ratio

            micro_inflow_ratio = 0.30 if is_catastrophic else 0.10
            micro_inflow_tokens   = leaked_tokens * micro_inflow_ratio
            micro_detection_ratio = 0.10
            token_price_usd       = 1.0

            micro_secondary_loss = (
                micro_inflow_tokens * micro_detection_ratio * token_price_usd
            )

        # 서비스 중단 시간
        service_downtime_sec = 0.0
        micro_available  = True
        freeze_scope     = 'none'
        response_action  = 'none'

        if detected_as_attack:
            amount = float(scenario.parameters.get('amount_per_block',
                           scenario.parameters.get('amount_per_wallet',
                           scenario.parameters.get('amount_per_recipient',
                           scenario.parameters.get('start_amount',
                           scenario.parameters.get('amount',
                           scenario.parameters.get('loan_amount',
                           scenario.parameters.get('total_amount', 0))))))))

            if is_macro:
                is_catastrophic_flag = (
                    amount >= 50_000_000  # 매우 큰 재앙적 규모로 상향
                    or scenario.parameters.get('is_catastrophic', False)
                    or scenario.parameters.get('is_burst', False)  # 연쇄 공격 발생 시
                )

                if is_catastrophic_flag:
                    service_downtime_sec = random.uniform(300, 900)
                    freeze_scope    = 'full_network'
                    response_action = 'pause_all'
                    micro_available = False
                else:
                    service_downtime_sec = 0.0
                    micro_available  = True
                    freeze_scope     = 'selective'
                    response_action  = 'freeze_wallet'
            else:
                service_downtime_sec = 0.0
                micro_available  = True
                freeze_scope     = 'selective'
                response_action  = 'freeze_wallet'

            if scenario.network_condition == 'congested':
                service_downtime_sec *= 1.1
            elif scenario.network_condition == 'severe':
                service_downtime_sec *= 1.2

        gas_details: Dict[str, float] = {}
        if detected_as_attack:
            gas_details = {
                'signature_verification': 21000.0,
                'pause': 18000.0,
                'blacklist_addition': 32000.0,
            }

        return DetectionResponse(
            prediction=prediction,
            latency_ms=latency_ms,
            financial_loss=financial_loss,
            micro_secondary_loss=micro_secondary_loss,
            leaked_tokens=leaked_tokens,
            service_downtime_sec=service_downtime_sec,
            downtime_opportunity_cost=0.0,
            micro_available=micro_available,
            freeze_scope=freeze_scope,
            response_action=response_action,
            gas_details=gas_details,
        )

    # ── 탐지 흐름 ──────────────────────────────────────────────────────────────

    def _run_two_layer_detection(self, scenario: Scenario) -> str:
        """
        피처 벡터를 추출하고 Macro/Micro 엔진으로 분기한다.

        피처는 공격/정상 분포에서 확률적으로 샘플링되므로
        회피 공격은 score가 자연스럽게 낮아져 미탐이 데이터로 발생.
        """
        features = extract_features(scenario)
        is_macro = self._is_macro_transaction(scenario)

        if is_macro:
            return self._detect_macro_layer(scenario, features)
        return self._detect_micro_layer(scenario, features)

    def _is_macro_transaction(self, scenario: Scenario) -> bool:
        """거래가 Macro 계층에 속하는지 판단"""
        amount = float(scenario.parameters.get('amount_per_block',
                       scenario.parameters.get('amount_per_wallet',
                       scenario.parameters.get('amount_per_recipient',
                       scenario.parameters.get('start_amount',
                       scenario.parameters.get('amount',
                       scenario.parameters.get('loan_amount',
                       scenario.parameters.get('total_amount', 0))))))))

        if amount >= 1_000_000:
            return True

        macro_types = {
            ScenarioType.INFINITE_MINT,
            ScenarioType.RESERVE_DRAIN,
            ScenarioType.FLASH_LOAN_DEPEG,   # 공격 플래시론만 Macro
            # NORMAL_FLASH_LOAN은 Macro 제외 — 화이트리스트 정상 거래이므로 Micro 경로 처리
            ScenarioType.LIQUIDITY_ADD,
        }
        return scenario.scenario_type in macro_types

    def _detect_macro_layer(self, scenario: Scenario,
                            features: Dict[str, float]) -> str:
        """
        Macro Layer 탐지 (엄격한 다중 검증)

        [점수 구성]
        1. 이상 점수 (AnomalyScorer, 50%) — 피처 분포 기반
        2. 서명 검증 점수 (30%)            — 사전 서명 유효성
        3. 임계값 보조 점수 (20%)          — 거래 금액 기반

        [설계 의도]
        - 모든 random.random() < 상수 패턴 제거
        - 회피/위장 공격은 피처 분포가 정상과 겹침 → 이상 점수↓ → 미탐 자연 발생
        - 현실 노이즈(멤풀 재조합 등)는 gaussian noise σ=0.03으로 모사
        """
        # 1. 통계 기반 이상 점수
        anomaly_score = self._scorer.score(features)

        # 2. 서명/권한 검증 점수 (도메인 지식 기반, 확률 상수 아님)
        sig_score = self._check_signature_validity(scenario)

        # 3. 금액 임계값 보조 점수
        threshold_score = self._check_strict_threshold(scenario)

        # 4. 가중 앙상블
        final_score = (
            anomaly_score   * 0.50 +
            sig_score       * 0.30 +
            threshold_score * 0.20
        )

        # 5. 소량 현실 노이즈 (오프체인 검증 지연, 멤풀 재조합 등)
        noise = float(np.random.normal(0.0, 0.03))
        final_score = float(np.clip(final_score + noise, 0.0, 1.0))

        return 'ATTACK' if final_score > 0.48 else 'NORMAL'

    def _detect_micro_layer(self, scenario: Scenario,
                            features: Dict[str, float]) -> str:
        """
        Micro Layer 탐지 (경량 독립 처리)

        임계값 0.52 (Macro보다 보수적):
        - 소액 결제에 오탐이 생기면 서비스 연속성에 영향이 크므로
          FPR 억제를 위해 임계값을 약간 높게 설정
        - 단, 회피 공격(Threshold Evasion 등)은 피처 분포가
          정상과 겹치도록 feature_extractor에서 설계되어 있어
          score가 임계값 미만으로 자연스럽게 결정됨 (미탐 자연 발생)
        """
        anomaly_score = self._scorer.score(features)

        # 경량 엔진 특성상 불확실성 σ=0.04 (Macro보다 약간 높음)
        noise = float(np.random.normal(0.0, 0.04))
        final_score = float(np.clip(anomaly_score + noise, 0.0, 1.0))

        return 'ATTACK' if final_score > 0.52 else 'NORMAL'

    # ── 보조 점수 메서드 (도메인 지식 기반, 확률 상수 미사용) ─────────────────

    def _check_strict_threshold(self, scenario: Scenario) -> float:
        """
        엄격한 임계값 검사 (Macro 전용 보조 점수)
        거래 금액과 임계값의 비율로부터 점수를 산출.
        Ground Truth 레이블 참조 없이 금액 비율에만 의존하는 연속 점수.

        ▶ 임계값 초과 시: sigmoid로 연속적으로 상승 (거액 거래도 높은 점수)
        ▶ 임계값 미만 시: 비율 × 0.15 (proportional, 최대 0.15)

        주의: 정상 고액 거래도 이 점수는 높게 나올 수 있으나,
              anomaly_score (50%) 및 sig_score (30%)가 낮으면 최종 판정 NORMAL.
        """
        import math
        macro_threshold = self.config['macro_threshold']
        amount = float(scenario.parameters.get('amount_per_block',
                       scenario.parameters.get('amount_per_wallet',
                       scenario.parameters.get('amount_per_recipient',
                       scenario.parameters.get('start_amount',
                       scenario.parameters.get('amount',
                       scenario.parameters.get('loan_amount',
                       scenario.parameters.get('total_amount', 0))))))))

        # 화이트리스트 검사 통과 시 임계값 점수 강제 0 부여 (정상 플래시론 등 오탐 완전 차단)
        if scenario.parameters.get('is_whitelisted', False):
            return 0.0

        ratio = amount / (macro_threshold + 1e-8)
        if ratio >= 1.0:
            # 임계값 초과: sigmoid 기반 연속 점수 (0.5~0.95)
            return float(np.clip(1.0 / (1.0 + math.exp(-(ratio - 1.0))), 0.0, 0.95))
        else:
            # 임계값 미만: 비율 비례 낮은 점수 (0.0~0.15)
            return float(np.clip(ratio * 0.15, 0.0, 0.15))

    def _check_signature_validity(self, scenario: Scenario) -> float:
        """
        서명/권한 검증 (Macro의 핵심 보조 점수)
        2계층의 Macro는 사전 서명이 필요 — 공격은 서명 없이 시도.

        ▶ scenario.parameters['has_valid_signature']  (data_generator에서 확률적 결정)
           - 일반 공격:   5% 확률로 True (우연 서명 통과)
           - CAMOUFLAGE: 70% 확률로 True (서명 위조 성공)
           - 정상 거래:  True (항상 유효)

        반환 점수:
           has_valid_signature=True  → 0.05 (유효 서명: 낮은 의심도)
           has_valid_signature=False → 0.90 (서명 없음: 높은 의심도)
           is_whitelisted=True       → 0.02 (화이트리스트: 가장 낮은 의심도)

        ⚠️  scenario.is_attack() 직접 조회 제거 — Data Leakage 해소
        """
        if scenario.parameters.get('is_whitelisted', False):
            return 0.02   # 화이트리스트 주소: 가장 낮은 의심도

        has_valid_sig = scenario.parameters.get('has_valid_signature', True)
        if has_valid_sig:
            return 0.05   # 유효한 서명: 낮은 의심도
        return 0.90       # 서명 없음: 높은 의심도
