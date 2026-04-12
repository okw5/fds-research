"""
FeatureExtractor
시나리오로부터 통계 분포 기반 피처 벡터를 생성한다.

피처 설계 원칙:
- 정상 거래  : NORMAL_DIST     에서 샘플링 (기저 분포)
- 공격 거래  : ATTACK_DIST     에서 샘플링 (편향 분포)
- 회피/위장  : 정상과 분포가 의도적으로 겹쳐 미탐이 데이터로 자연 발생

생성 피처 (5종):
  tx_frequency    : 분당 트랜잭션 수       (Gamma)
  contract_depth  : 컨트랙트 호출 깊이     (Poisson)
  gas_price_ratio : 평균 대비 가스비 배율  (LogNormal)
  active_wallets  : 연관 지갑 수           (NegativeBinomial)
  value_zscore    : 거래 금액 Z-Score      (Normal)
"""

import numpy as np
from typing import Dict, Tuple

try:
    from ..scenario import Scenario, ScenarioType
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scenario import Scenario, ScenarioType

# ── 피처 목록 ─────────────────────────────────────────────────────────────────
FEATURE_NAMES = [
    'tx_frequency',
    'contract_depth',
    'gas_price_ratio',
    'active_wallets',
    'value_zscore',
]

# ── 정상 기저 분포 파라미터 ────────────────────────────────────────────────────
# 형식: (분포명, kwargs)
NORMAL_DIST: Dict[str, Tuple[str, dict]] = {
    'tx_frequency':    ('gamma',             {'shape': 2.0, 'scale': 3.0}),  # 기대값=6.0
    'contract_depth':  ('poisson',           {'lam': 3}),                    # 기대값=3.0
    'gas_price_ratio': ('lognormal',         {'mean': 0.0, 'sigma': 0.5}),   # 기대값≈1.13
    'active_wallets':  ('negative_binomial', {'n': 5, 'p': 0.4}),            # 기대값≈7.5
    'value_zscore':    ('normal',            {'loc': 0.0, 'scale': 1.0}),    # 기대값=0.0
}

# ── 공격 유형별 편향 분포 파라미터 ────────────────────────────────────────────
# 지정하지 않은 피처는 NORMAL_DIST 사용
# 회피/위장 공격은 정상과 근접하도록 의도적 설계 → 미탐 자연 발생
ATTACK_DIST: Dict[ScenarioType, Dict[str, Tuple[str, dict]]] = {

    # ── 대규모 Macro 공격 (정상과 분포가 크게 다름) ──────────────────────────
    ScenarioType.INFINITE_MINT: {
        'tx_frequency':    ('gamma',     {'shape': 6.0, 'scale': 4.0}),  # 폭발적 빈도
        'value_zscore':    ('normal',    {'loc': 4.5,  'scale': 1.2}),   # 이상 고액
        'gas_price_ratio': ('lognormal', {'mean': 1.2, 'sigma': 0.6}),  # 높은 가스비
    },
    ScenarioType.RESERVE_DRAIN: {
        'tx_frequency':    ('gamma',   {'shape': 5.0, 'scale': 3.5}),
        'value_zscore':    ('normal',  {'loc': 3.8,  'scale': 1.1}),
        'contract_depth':  ('poisson', {'lam': 8}),                      # 깊은 호출
    },
    ScenarioType.FLASH_LOAN_DEPEG: {
        'tx_frequency':    ('gamma',     {'shape': 8.0, 'scale': 2.0}),  # 같은 블록 내 급증
        'contract_depth':  ('poisson',   {'lam': 10}),
        'gas_price_ratio': ('lognormal', {'mean': 2.0, 'sigma': 0.8}),
        'value_zscore':    ('normal',    {'loc': 3.0,  'scale': 1.5}),
    },
    ScenarioType.SYBIL_ATTACK: {
        # 소액 분산 → value_zscore는 낮지만 지갑 수가 압도적으로 많음
        'active_wallets': ('negative_binomial', {'n': 30, 'p': 0.2}),   # 기대값≈120
        'tx_frequency':   ('gamma',             {'shape': 5.0, 'scale': 3.0}),
        'value_zscore':   ('normal',            {'loc': 1.5,  'scale': 0.8}),
    },

    # ── 소규모 회피 공격 (정상과 분포 겹침 → 미탐 자연 발생) ─────────────────
    ScenarioType.THRESHOLD_EVASION: {
        # 의도적으로 정상과 근사한 파라미터 → AnomalyScorer 점수 낮게 나옴
        'tx_frequency':    ('gamma',     {'shape': 2.5, 'scale': 3.0}),  # 정상 근접
        'value_zscore':    ('normal',    {'loc': 0.8,  'scale': 1.2}),   # 정상 범위 내
        'gas_price_ratio': ('lognormal', {'mean': 0.2, 'sigma': 0.5}),
    },
    ScenarioType.GRADUAL_ESCALATION: {
        'tx_frequency':    ('gamma',  {'shape': 2.8, 'scale': 3.2}),
        'value_zscore':    ('normal', {'loc': 1.5,  'scale': 1.0}),
    },
    ScenarioType.CAMOUFLAGE: {
        # 정상과 거의 동일한 분포 → 미탐 빈번히 발생
        'tx_frequency':    ('gamma',     {'shape': 2.0, 'scale': 3.0}),
        'value_zscore':    ('normal',    {'loc': 0.3,  'scale': 1.1}),
        'gas_price_ratio': ('lognormal', {'mean': 0.1, 'sigma': 0.5}),
    },
}


def _sample_feature(dist_name: str, params: dict) -> float:
    """단일 피처 값을 지정된 분포에서 샘플링한다."""
    rng = np.random
    if dist_name == 'gamma':
        return float(rng.gamma(**params))
    elif dist_name == 'poisson':
        return float(rng.poisson(**params))
    elif dist_name == 'lognormal':
        return float(rng.lognormal(**params))
    elif dist_name == 'negative_binomial':
        return float(rng.negative_binomial(**params))
    elif dist_name == 'normal':
        return float(rng.normal(**params))
    raise ValueError(f"Unknown distribution: {dist_name!r}")


def extract_features(scenario: Scenario) -> Dict[str, float]:
    """
    시나리오로부터 통계 기반 피처 벡터를 생성한다.

    공격 시나리오: ATTACK_DIST에 정의된 편향 분포 사용 (정의 없는 피처는 NORMAL_DIST)
    정상 시나리오: NORMAL_DIST에서만 샘플링

    Returns:
        dict  keys: tx_frequency, contract_depth, gas_price_ratio,
                    active_wallets, value_zscore
    """
    attack_override = (
        ATTACK_DIST.get(scenario.scenario_type, {})
        if scenario.is_attack()
        else {}
    )
    features: Dict[str, float] = {}
    for feat in FEATURE_NAMES:
        if feat in attack_override:
            dist_name, params = attack_override[feat]
        else:
            dist_name, params = NORMAL_DIST[feat]
        features[feat] = _sample_feature(dist_name, params)
    return features
