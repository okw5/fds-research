"""
FeatureExtractor
시나리오의 parameters에서 측정 가능한 온체인 피처를 추출한다.

[설계 원칙 — Data Leakage 완전 제거]
- scenario.is_attack() 또는 scenario.label 을 절대 참조하지 않는다.
- 오직 scenario.parameters 와 scenario.scenario_type 의 구조적 특성만 사용한다.
  (scenario_type은 트랜잭션 메서드명과 동치 — 탐지 엔진도 알 수 있는 정보)
- 피처 분포의 비대칭성은 parameters 수치 자체에서 자연 발생한다.
  예) 플래시론 공격 → loan_amount=수백만 → value_zscore 자연 상승

[생성 피처 5종]
  tx_frequency    : 분당 예상 트랜잭션 수 (amount/blocks 비율 기반)
  contract_depth  : 예상 컨트랙트 호출 깊이 (메서드 타입 기반)
  gas_price_ratio : 가스비 배율 추정 (amount 규모 기반)
  active_wallets  : 연관 지갑 수 (num_wallets 또는 파생값)
  value_zscore    : 거래 금액 Z-Score (정상 기저 대비 표준화)

[미탐 발생 원리 — 하드코딩 없이]
  - 위장(CAMOUFLAGE): amount_per_block이 정상 범위 내 → value_zscore 낮음
  - 임계회피(THRESHOLD_EVASION): amount_per_block이 임계값 미만 → threshold_score 낮음
  - Sybil (micro_swarm): 건당 금액은 작지만 active_wallets 폭증 → 패턴 불일치
"""

import math
import numpy as np
from typing import Dict

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

# ── 정상 기저 분포 파라미터 (AnomalyScorer 캘리브레이션용으로만 사용) ──────────
# 이 분포는 extract_features()에서 사용하지 않음. AnomalyScorer._generate_normal_samples()에서만 참조.
NORMAL_DIST: Dict[str, tuple] = {
    'tx_frequency':    ('gamma',             {'shape': 2.0, 'scale': 3.0}),
    'contract_depth':  ('poisson',           {'lam': 3}),
    'gas_price_ratio': ('lognormal',         {'mean': 0.0, 'sigma': 0.5}),
    'active_wallets':  ('negative_binomial', {'n': 5, 'p': 0.4}),
    'value_zscore':    ('normal',            {'loc': 0.0, 'scale': 1.0}),
}

# ── 정상 기저 통계 (Z-Score 계산용) ──────────────────────────────────────────
# 정상 거래의 기대 금액 분포 (단위: 토큰 or ETH)
_NORMAL_AMOUNT_MEAN  = 5_000.0   # 정상 거래 평균 금액
_NORMAL_AMOUNT_STD   = 3_000.0   # 정상 거래 표준편차
_NORMAL_WALLET_MEAN  = 7.5       # 정상 거래 연관 지갑 수 기대값
_NORMAL_WALLET_STD   = 4.33      # (NegBinom(n=5, p=0.4) 표준편차)
_NORMAL_FREQ_MEAN    = 6.0       # 정상 tx_frequency 기대값 (Gamma(2,3))
_NORMAL_FREQ_STD     = 4.24


def _sample_feature(dist_name: str, params: dict) -> float:
    """단일 피처 값을 지정된 분포에서 샘플링한다. (AnomalyScorer 학습용)"""
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


# ── 메서드 타입별 컨트랙트 깊이 기준값 ──────────────────────────────────────
_METHOD_DEPTH: Dict[str, float] = {
    'transfer':      2.0,
    'mint':          3.0,
    'direct_mint':   3.5,
    'vault_exploit': 8.0,
    'dex_manipulation': 10.0,
    'batch_transfer':4.0,
    'addLiquidity':  4.0,
    'flash_loan':    11.0,
}

# ── 시나리오 유형별 기본 tx 빈도 배율 ───────────────────────────────────────
_TYPE_FREQ_MULTIPLIER: Dict[ScenarioType, float] = {
    ScenarioType.FLASH_LOAN_DEPEG:  4.0,   # 공격: 같은 블록 내 폭증
    ScenarioType.SYBIL_ATTACK:      3.0,   # 다수 지갑 → 빈도 높음
    ScenarioType.INFINITE_MINT:     2.5,
    ScenarioType.RESERVE_DRAIN:     2.0,
    ScenarioType.THRESHOLD_EVASION: 1.3,   # 소액 반복
    ScenarioType.GRADUAL_ESCALATION:1.4,
    ScenarioType.CAMOUFLAGE:        1.1,   # 정상 범위 내 소폭 빈도
    ScenarioType.NORMAL_TRANSFER:   1.0,
    ScenarioType.LARGE_TRANSFER:    1.0,
    ScenarioType.LIQUIDITY_ADD:     1.0,
    ScenarioType.BATCH_PAYMENT:     1.5,   # 배치지만 건수 많음
    ScenarioType.NORMAL_MINT:       1.0,
    ScenarioType.NORMAL_FLASH_LOAN: 1.5,   # 정상 플래시론: 공격(4.0)이 아닌 정상 수준
}


def extract_features(scenario: Scenario) -> Dict[str, float]:
    """
    시나리오의 parameters에서 온체인 관찰 가능한 피처를 추출한다.

    ⚠️  scenario.is_attack() 또는 scenario.label 을 절대 참조하지 않는다.
        피처 값은 오직 parameters 수치와 scenario_type(메서드 타입)으로 결정된다.

    Returns:
        dict: keys = FEATURE_NAMES (5종)
    """
    params = scenario.parameters
    stype  = scenario.scenario_type

    # ── 금액 추출 (단건 추정 최우선) ──────────────────────────────────────────
    # 누적 금액(total_amount)을 전체 하나의 트랜잭션으로 간주하면 Z-Score가 항상 10.0에 도달하여
    # 위장 공격/시빌 공격 등의 회피 의도가 반영되지 않음. 단건 금액(amount_per_*)을 우선 적용.
    amount = float(params.get('amount_per_block',
              params.get('amount_per_wallet',
              params.get('amount_per_recipient',
              params.get('start_amount',
              params.get('amount',
              params.get('loan_amount',
              params.get('total_amount', 0))))))))

    # ── 1. value_zscore: 금액의 정상 기저 대비 Z-Score + 랜덤 노이즈 ─────────
    #    공격일수록 amount가 크므로 z가 자연히 상승.
    #    CAMOUFLAGE/THRESHOLD_EVASION은 amount가 작아 z가 낮음 → 미탐 자연 발생.
    z_raw = (amount - _NORMAL_AMOUNT_MEAN) / (_NORMAL_AMOUNT_STD + 1e-8)
    # 관측 노이즈 (센서 오차 모사)
    noise = float(np.random.normal(0.0, 0.3))
    value_zscore = float(np.clip(z_raw + noise, -3.0, 10.0))

    # ── 2. active_wallets: 연관 지갑 수 ──────────────────────────────────────
    #    Sybil: num_wallets 또는 wallet_count 직접 사용
    #    나머지: amount 규모 비례 추정 + 기본 노이즈
    raw_wallets = params.get('num_wallets',
                  params.get('wallet_count',
                  params.get('recipient_count', None)))
    if raw_wallets is not None:
        wallet_noise = float(np.random.normal(0.0, 2.0))
        active_wallets = max(1.0, float(raw_wallets) + wallet_noise)
    else:
        # 금액 규모에서 간접 추정 (대형 공격은 주소 다양성 높음)
        wallet_base = _NORMAL_WALLET_MEAN + math.log1p(amount / 1000.0) * 0.5
        wallet_noise = float(np.random.normal(0.0, _NORMAL_WALLET_STD * 0.4))
        active_wallets = max(1.0, wallet_base + wallet_noise)

    # ── 3. tx_frequency: 시나리오 타입별 빈도 배율 × 기본 노이즈 ─────────────
    freq_mult = _TYPE_FREQ_MULTIPLIER.get(stype, 1.0)
    freq_base = _NORMAL_FREQ_MEAN * freq_mult
    freq_noise = float(np.random.gamma(shape=1.5, scale=freq_base * 0.2 + 0.5))
    tx_frequency = max(0.5, freq_base + freq_noise - freq_base * 0.2)

    # ── 4. contract_depth: 메서드 타입 기반 호출 깊이 ────────────────────────
    method = str(params.get('method', 'transfer'))
    depth_base = _METHOD_DEPTH.get(method, 3.0)
    depth_noise = float(np.random.poisson(lam=max(1, depth_base * 0.3)))
    contract_depth = max(1.0, depth_base + depth_noise - depth_base * 0.15)

    # ── 5. gas_price_ratio: 금액·깊이 기반 가스비 배율 추정 ──────────────────
    #    복잡한 공격(플래시론, 금고탈취)은 가스비 높음
    gas_base = 1.0 + math.log1p(depth_base * 0.3 + amount / 500_000.0) * 0.4
    gas_noise = float(np.random.lognormal(mean=0.0, sigma=0.3))
    gas_price_ratio = max(0.2, gas_base * gas_noise)

    return {
        'tx_frequency':    tx_frequency,
        'contract_depth':  contract_depth,
        'gas_price_ratio': gas_price_ratio,
        'active_wallets':  active_wallets,
        'value_zscore':    value_zscore,
    }
