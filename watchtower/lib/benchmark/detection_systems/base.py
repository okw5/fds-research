"""
DetectionSystem 추상 베이스 클래스
모든 탐지 시스템이 구현해야 하는 인터페이스 정의

v2: 피해금액, 서비스 중단 시간, 서비스 가용성 지표 추가
"""

from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional
from dataclasses import dataclass

# 조건부 임포트: 패키지 모드와 직접 실행 모드 지원
try:
    from ..scenario import Scenario, ScenarioType, ScenarioLabel
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scenario import Scenario, ScenarioType, ScenarioLabel


@dataclass
class DetectionResponse:
    """
    탐지 결과 응답 데이터 클래스 (확장)
    
    Attributes:
        prediction: 예측 결과 ('ATTACK' or 'NORMAL')
        latency_ms: 탐지 소요 시간 (밀리초)
        financial_loss: 탐지까지 발생한 예상 피해금액 (USD)
        service_downtime_sec: 방어 조치로 인한 서비스 중단 시간 (초)
        micro_available: 소액결제 서비스 가용 여부 (True=유지, False=중단)
        freeze_scope: 동결 범위 ('none', 'selective', 'full_network')
        response_action: 방어 조치 유형 ('none', 'pause_macro', 'freeze_wallet', 'pause_all')
    """
    prediction: str
    latency_ms: float
    financial_loss: float = 0.0
    service_downtime_sec: float = 0.0
    micro_available: bool = True
    freeze_scope: str = 'none'       # none, selective, full_network
    response_action: str = 'none'    # none, pause_macro, freeze_wallet, pause_all


class DetectionSystem(ABC):
    """
    탐지 시스템의 추상 베이스 클래스
    
    모든 탐지 시스템은 이 클래스를 상속하여 detect() 메서드를 구현해야 함
    """
    
    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            name: 시스템 이름 (예: "FDS 2-Layer")
            config: 시스템 설정 (임계값 등)
        """
        self.name = name
        self.config = config or {}
        self._detection_count = 0
        self._total_latency = 0.0
    
    @abstractmethod
    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        """
        시나리오를 분석하여 탐지 결과 반환 (기본 인터페이스)
        
        Args:
            scenario: 분석할 시나리오
            
        Returns:
            Tuple[str, float]: (예측 결과, 탐지 지연시간)
            - 예측 결과: 'ATTACK' 또는 'NORMAL'
            - 탐지 지연시간: 밀리초 단위
        """
        pass
    
    def detect_extended(self, scenario: Scenario) -> DetectionResponse:
        """
        확장된 탐지 결과 반환 (피해금액, 서비스 중단 시간 포함)
        서브클래스에서 오버라이드하여 시스템별 특성 반영
        
        기본 구현: detect()를 호출하고 기본 DetectionResponse 반환
        """
        prediction, latency_ms = self.detect(scenario)
        return DetectionResponse(
            prediction=prediction,
            latency_ms=latency_ms,
            financial_loss=0.0,
            service_downtime_sec=0.0,
            micro_available=True,
            freeze_scope='none',
            response_action='none'
        )
    
    def get_name(self) -> str:
        """시스템 이름 반환"""
        return self.name
    
    def get_stats(self) -> Dict[str, Any]:
        """시스템 통계 반환"""
        avg_latency = self._total_latency / self._detection_count if self._detection_count > 0 else 0
        return {
            'name': self.name,
            'detection_count': self._detection_count,
            'avg_latency_ms': round(avg_latency, 2)
        }
    
    def reset_stats(self):
        """통계 초기화"""
        self._detection_count = 0
        self._total_latency = 0.0
    
    def _record_detection(self, latency_ms: float):
        """탐지 통계 기록 (내부용)"""
        self._detection_count += 1
        self._total_latency += latency_ms
    
    def _estimate_financial_loss(self, scenario: Scenario, latency_ms: float, 
                                  detected: bool) -> float:
        """
        탐지 지연 시간 동안 발생한 예상 피해금액 계산 (USD)
        
        로직:
        - 공격이 탐지되지 않으면(FN): 전체 공격 금액 손실
        - 공격이 탐지되면(TP): 탐지 지연 시간에 비례한 부분 손실
        - 정상 거래: 피해 없음
        
        Args:
            scenario: 시나리오
            latency_ms: 탐지 지연 시간
            detected: 공격으로 탐지했는지 여부
        """
        if not scenario.is_attack():
            return 0.0  # 정상 거래는 피해 없음
        
        # 공격 금액 추출
        attack_amount = scenario.parameters.get('amount', 
                        scenario.parameters.get('total_amount',
                        scenario.parameters.get('loan_amount', 0)))
        
        if not detected:
            # 미탐 (FN): 전체 금액 손실
            return float(attack_amount)
        
        # 탐지 성공 (TP): 지연 시간에 비례한 피해
        # 빠를수록 피해 적음, 느릴수록 피해 큼
        # 가정: 공격이 진행되는 속도에 따라 피해 발생
        # 1초(1000ms) 이내 탐지 → 피해 5% 미만
        # 5초(5000ms) → 피해 50%
        # 10초 이상 → 피해 90%
        
        if latency_ms <= 200:
            loss_ratio = 0.02  # 초고속 탐지: 2% 손실
        elif latency_ms <= 500:
            loss_ratio = 0.05  # 빠른 탐지: 5% 손실
        elif latency_ms <= 1000:
            loss_ratio = 0.10  # 보통: 10% 손실
        elif latency_ms <= 3000:
            loss_ratio = 0.30  # 느림: 30% 손실
        elif latency_ms <= 5000:
            loss_ratio = 0.50  # 매우 느림: 50% 손실
        else:
            loss_ratio = 0.80  # 초과: 80% 손실
        
        return float(attack_amount) * loss_ratio
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"


class DetectionConfig:
    """탐지 시스템 설정을 위한 헬퍼 클래스"""
    
    # 기본 임계값
    DEFAULT_MINT_THRESHOLD = 10000        # 민트 임계값 (토큰)
    DEFAULT_DRAIN_THRESHOLD = 0.10        # 금고 인출 임계값 (10%)
    DEFAULT_DEPEG_THRESHOLD = 0.05        # 디페그 임계값 (5%)
    DEFAULT_WINDOW_SIZE = 5               # 누적 윈도우 크기 (블록)
    
    # 2계층 시스템 설정
    DEFAULT_MICRO_THRESHOLD = 0.005       # Micro 임계값 (0.5%)
    DEFAULT_MACRO_THRESHOLD = 0.001       # Macro 임계값 (0.1%)
    
    @classmethod
    def get_manual_governance_config(cls) -> Dict[str, Any]:
        """수동 거버넌스 시스템 기본 설정"""
        return {
            'response_delay_min_ms': 3500,
            'response_delay_max_ms': 6000,
            'detection_accuracy': 0.70,  # 70% 탐지 정확도 (인간 판단 한계)
            'false_positive_rate': 0.15  # 15% 오탐율
        }
    
    @classmethod
    def get_fds_single_layer_config(cls) -> Dict[str, Any]:
        """FDS 단일 토큰 시스템 기본 설정"""
        return {
            'mint_threshold': cls.DEFAULT_MINT_THRESHOLD,
            'drain_threshold': cls.DEFAULT_DRAIN_THRESHOLD,
            'depeg_threshold': cls.DEFAULT_DEPEG_THRESHOLD,
            'window_size': cls.DEFAULT_WINDOW_SIZE,
            'base_latency_ms': 250,
            'latency_variance_ms': 100,
            'congestion_multiplier': 2.5  # 혼잡 시 지연 배수
        }
    
    @classmethod
    def get_fds_two_layer_config(cls) -> Dict[str, Any]:
        """FDS 2계층 토큰 시스템 기본 설정"""
        return {
            'micro_threshold': cls.DEFAULT_MICRO_THRESHOLD,
            'macro_threshold': cls.DEFAULT_MACRO_THRESHOLD,
            'drain_threshold': cls.DEFAULT_DRAIN_THRESHOLD * 0.5,  # 더 엄격
            'depeg_threshold': cls.DEFAULT_DEPEG_THRESHOLD * 0.6,  # 더 엄격
            'window_size': cls.DEFAULT_WINDOW_SIZE,
            'base_latency_ms': 80,
            'latency_variance_ms': 40,
            'congestion_multiplier': 1.5,  # 우선처리로 혼잡 영향 감소
            'micro_fast_path': True  # Micro 계층 빠른 처리
        }
