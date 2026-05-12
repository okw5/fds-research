"""
Single Engine Detection Systems
FDS 독립 엔진 (1계층 기반 시뮬레이션)
"""

from typing import Tuple
import numpy as np

# fds_single_layer.py 상속
from .fds_single_layer import FDSSingleLayerSystem

try:
    from ..scenario import Scenario, ScenarioType
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scenario import Scenario, ScenarioType


class FDSEngine1System(FDSSingleLayerSystem):
    """
    탐지엔진 1 (SequenceAnomalyEngine) ONLY
    설계: AnomalyScorer(행동/계정 패턴 통계점수) 100% 반영
    탐지 특성: 금액 규칙이 빠져 있어서 정상 대량거래 FP증가 가능성, 
    정교한 시퀀스 공격(Flashloan)에 대한 감지력 낮음(FN).
    """
    def __init__(self, config=None):
        super().__init__(config)
        self.name = "탐지엔진1 + 1계층 모델"

    def _run_detection_algorithms(self, scenario: Scenario):
        scorer_score = self._scorer.score(self._extract_features(scenario))
        
        # 엔진 1 단독: 순수 anomaly_score로만 판정
        avg_score = scorer_score
        
        noise_sigma = self._current_fpr * 0.5
        overload_noise = float(np.random.normal(loc=0.0, scale=noise_sigma))
        base_noise = float(np.random.normal(0.0, 0.03))
        
        final_score = float(np.clip(avg_score + base_noise + overload_noise, 0.0, 1.0))
        effective_threshold = max(0.50 - (self._current_fpr * 0.3), 0.30)
        
        self._last_applied_fpr = self._current_fpr
        self._last_applied_threshold = effective_threshold

        if final_score > effective_threshold:
            return ('ATTACK', self._current_fpr, effective_threshold)
        return ('NORMAL', self._current_fpr, effective_threshold)
        
    def _extract_features(self, scenario: Scenario):
        try:
            from ..feature_extractor import extract_features
            return extract_features(scenario)
        except ImportError:
            from feature_extractor import extract_features
            return extract_features(scenario)


class FDSEngine2System(FDSSingleLayerSystem):
    """
    탐지엔진 2 (FlashLoanRuleEngine) ONLY
    설계: 단순 임계값 규칙 및 시나리오 공격 패턴 검사 위주
    탐지 특성: Known attack pattern과 금액 기반 탐지가 매우 강력하나, 
    정상적인 고액거래나 새로운 공격 우회에 취약.
    """
    def __init__(self, config=None):
        super().__init__(config)
        self.name = "탐지엔진2 + 1계층 모델"

    def _run_detection_algorithms(self, scenario: Scenario):
        threshold_score = self._check_simple_threshold(scenario)
        
        # 특정 서명 공격유형에 민감하게 작용
        pattern_bonus = 0.0
        if scenario.scenario_type in [ScenarioType.FLASH_LOAN_DEPEG, ScenarioType.INFINITE_MINT, ScenarioType.SANDWICH_ATTACK]:
            pattern_bonus = 0.3
            
        avg_score = min(1.0, threshold_score + pattern_bonus)
        
        noise_sigma = self._current_fpr * 0.5
        overload_noise = float(np.random.normal(loc=0.0, scale=noise_sigma))
        base_noise = float(np.random.normal(0.0, 0.03))
        
        final_score = float(np.clip(avg_score + base_noise + overload_noise, 0.0, 1.0))
        effective_threshold = max(0.50 - (self._current_fpr * 0.2), 0.30)
        
        self._last_applied_fpr = self._current_fpr
        self._last_applied_threshold = effective_threshold

        if final_score > effective_threshold:
            return ('ATTACK', self._current_fpr, effective_threshold)
        return ('NORMAL', self._current_fpr, effective_threshold)


class FDSEngine3System(FDSSingleLayerSystem):
    """
    탐지엔진 3 (HoustonLiteInvariantChecker) ONLY
    설계: 시스템 불변량(Invariant) 위반 및 Catastrophic 감지 위주
    탐지 특성: 극단적 상태 변화(수백만 토큰, Reserve 붕괴)는 100% 잡아내지만,
    사소한 소액 회피공격이나 정상적인 가격변동구간에 취약함.
    """
    def __init__(self, config=None):
        super().__init__(config)
        self.name = "탐지엔진3 + 1계층 모델"

    def _run_detection_algorithms(self, scenario: Scenario):
        import time
        try:
            from watchtower.lib.engines.houston_lite import HoustonLiteInvariantChecker
        except ImportError:
            import sys
            import os
            # project root (/fds-research)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            from watchtower.lib.engines.houston_lite import HoustonLiteInvariantChecker

        # 싱글톤처럼 쓰려면 멤버 변수로 빼는 게 좋지만 벤치마크 속도를 위해 매번 생성하거나
        # 여기서 간이 생성 (실험 목적상 큰 차이 없음)
        if not hasattr(self, '_engine3'):
            self._engine3 = HoustonLiteInvariantChecker()

        tx_data = scenario.parameters.copy()
        tx_data['amount'] = float(tx_data.get('amount_per_block',
                            tx_data.get('amount',
                            tx_data.get('total_amount', 0))))
        tx_data['type'] = tx_data.get('method', 'transfer')
        
        # Engine3 평가 수행
        result = self._engine3.analyze(tx_data)
        
        # ThreatLevel을 1.0 체제의 점수로 변환 (간이 변환)
        level_scores = {
            'CRITICAL': 0.95,
            'HIGH':     0.75,
            'MEDIUM':   0.55,
            'LOW':      0.35,
            'NONE':     0.10
        }
        invariant_score = level_scores.get(result.threat_level.name, 0.1)
            
        avg_score = invariant_score
        
        noise_sigma = self._current_fpr * 0.5
        overload_noise = float(np.random.normal(loc=0.0, scale=noise_sigma))
        base_noise = float(np.random.normal(0.0, 0.04))
        
        final_score = float(np.clip(avg_score + base_noise + overload_noise, 0.0, 1.0))
        effective_threshold = max(0.55 - (self._current_fpr * 0.1), 0.40)
        
        self._last_applied_fpr = self._current_fpr
        self._last_applied_threshold = effective_threshold

        if final_score > effective_threshold:
            return ('ATTACK', self._current_fpr, effective_threshold)
        return ('NORMAL', self._current_fpr, effective_threshold)
