"""
AnomalyScorer
피처 벡터로부터 이상 점수(anomaly score)를 산출한다.

method='zscore' (기본):
    가중 Z-Score를 sigmoid로 변환.
    sklearn 불필요, 빠름, 설명 가능성 높음.
    정상 기대 점수 ≈ 0.20~0.35

method='gmm':
    정상 샘플 N개로 Gaussian Mixture Model 사전 학습 후
    log-likelihood → sigmoid 변환.
    sklearn 필요 (pip install scikit-learn).
    정상 기대 점수 ≈ 0.25~0.45

설정 예시:
    cfg = DetectionConfig.get_fds_two_layer_config()
    cfg['anomaly_method'] = 'zscore'   # 또는 'gmm'
"""

import math
import numpy as np
from typing import Dict, Tuple

try:
    from sklearn.mixture import GaussianMixture
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

try:
    from .feature_extractor import NORMAL_DIST, FEATURE_NAMES, _sample_feature
except ImportError:
    from feature_extractor import NORMAL_DIST, FEATURE_NAMES, _sample_feature


# ── 정상 분포의 이론적 모멘트 (Z-Score 캘리브레이션용) ────────────────────────
# (mean, std) — 각 분포의 기대값과 표준편차 (해석적 계산값)
NORMAL_MOMENTS: Dict[str, Tuple[float, float]] = {
    # Gamma(shape=2, scale=3):   mean=6.0,  std=sqrt(2)*3=4.24
    'tx_frequency':    (6.0,  4.24),
    # Poisson(3):                mean=3.0,  std=sqrt(3)=1.73
    'contract_depth':  (3.0,  1.73),
    # LogNormal(0, 0.5):         mean≈1.13, std≈0.60
    'gas_price_ratio': (1.13, 0.60),
    # NegBinom(n=5, p=0.4):      mean=7.5,  std≈4.33
    'active_wallets':  (7.5,  4.33),
    # Normal(0, 1):              mean=0.0,  std=1.0
    'value_zscore':    (0.0,  1.0),
}

# 피처별 판별 가중치 (합=1.0, 도메인 지식 기반)
FEATURE_WEIGHTS: Dict[str, float] = {
    'tx_frequency':    0.20,
    'contract_depth':  0.15,
    'gas_price_ratio': 0.20,
    'active_wallets':  0.20,
    'value_zscore':    0.25,
}

# ── 내부 유틸 ──────────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    """수치 안정적 sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def _generate_normal_samples(n: int) -> np.ndarray:
    """NORMAL_DIST에서 학습용 정상 샘플 N개 생성."""
    rows = []
    for _ in range(n):
        row = [
            _sample_feature(NORMAL_DIST[f][0], NORMAL_DIST[f][1])
            for f in FEATURE_NAMES
        ]
        rows.append(row)
    return np.array(rows, dtype=float)


# ── 메인 클래스 ────────────────────────────────────────────────────────────────

class AnomalyScorer:
    """
    피처 벡터 기반 이상 점수 산출기.

    score() 반환값:
        0.0 ~ 1.0 (0=완전 정상, 1=완전 이상)

    정상 거래 기대 score:
        zscore 방식: ~0.20~0.35
        gmm    방식: ~0.25~0.45

    회피/위장(THRESHOLD_EVASION, CAMOUFLAGE) 공격은 피처 분포가 정상과
    겹치도록 설계되어 있어 score가 임계값 미만으로 자연스럽게 낮게 나온다.
    → 미탐이 하드코딩 없이 데이터에 의해 발생
    """

    def __init__(
        self,
        method: str = 'zscore',
        n_gmm_components: int = 2,
        n_fit_samples: int = 800,
    ):
        if method not in ('zscore', 'gmm'):
            raise ValueError("method must be 'zscore' or 'gmm'")
        self.method = method
        self._gmm = None
        self._gmm_ll_mean = 0.0
        self._gmm_ll_std = 1.0

        if method == 'gmm':
            if not HAS_SKLEARN:
                raise ImportError(
                    "GMM 방식은 scikit-learn이 필요합니다.\n"
                    "설치: pip install scikit-learn"
                )
            self._fit_gmm(n_components=n_gmm_components, n_samples=n_fit_samples)

    # ── Z-Score 방식 ──────────────────────────────────────────────────────────

    def _zscore_score(self, features: Dict[str, float]) -> float:
        """
        score = sigmoid( Σ(w_i * |z_i|) - bias )

        bias=1.2 로 설정 시:
          정상 거래의 기대 가중-Z ≈ 0.80 → score ≈ 0.31 (캘리브레이션됨)
          대형 공격의 기대 가중-Z ≈ 2.5+ → score ≈ 0.75+
          회피 공격의 기대 가중-Z ≈ 1.0  → score ≈ 0.45 (임계값 근처)
        """
        weighted_z = 0.0
        for feat, weight in FEATURE_WEIGHTS.items():
            val = features.get(feat, 0.0)
            mean, std = NORMAL_MOMENTS[feat]
            z = abs(val - mean) / (std + 1e-8)
            weighted_z += weight * z

        # bias=1.2: 정상 기대 score ≈ 0.31
        return float(np.clip(_sigmoid(weighted_z - 1.2), 0.0, 1.0))

    # ── GMM 방식 ──────────────────────────────────────────────────────────────

    def _fit_gmm(self, n_components: int, n_samples: int):
        """정상 샘플로 GMM을 사전 학습하고 log-likelihood 통계를 저장."""
        X = _generate_normal_samples(n_samples)
        gmm = GaussianMixture(
            n_components=n_components,
            covariance_type='full',
            random_state=42,
        )
        gmm.fit(X)
        self._gmm = gmm

        ll = gmm.score_samples(X)
        self._gmm_ll_mean = float(ll.mean())
        self._gmm_ll_std  = float(ll.std() + 1e-8)

    def _gmm_score(self, features: Dict[str, float]) -> float:
        """
        GMM log-likelihood → 이상 점수 변환.
        정상 분포에서 멀수록(ll 낮을수록) score ↑.
        score = sigmoid( -(ll - mean_ll) / std_ll )
        """
        x = np.array([[features.get(f, 0.0) for f in FEATURE_NAMES]])
        ll = float(self._gmm.score_samples(x)[0])
        z  = -(ll - self._gmm_ll_mean) / self._gmm_ll_std
        return float(np.clip(_sigmoid(z), 0.0, 1.0))

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def score(self, features: Dict[str, float]) -> float:
        """
        이상 점수를 반환한다.

        Args:
            features: extract_features() 반환값

        Returns:
            float in [0.0, 1.0]
        """
        if self.method == 'zscore':
            return self._zscore_score(features)
        return self._gmm_score(features)
