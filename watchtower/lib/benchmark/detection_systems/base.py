"""
DetectionSystem 추상 베이스 클래스
모든 탐지 시스템이 구현해야 하는 인터페이스 정의
"""

from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional

# 조건부 임포트: 패키지 모드와 직접 실행 모드 지원
try:
    from ..scenario import Scenario, ScenarioType, ScenarioLabel
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scenario import Scenario, ScenarioType, ScenarioLabel


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
        시나리오를 분석하여 탐지 결과 반환
        
        Args:
            scenario: 분석할 시나리오
            
        Returns:
            Tuple[str, float]: (예측 결과, 탐지 지연시간)
            - 예측 결과: 'ATTACK' 또는 'NORMAL'
            - 탐지 지연시간: 밀리초 단위
        """
        pass
    
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
