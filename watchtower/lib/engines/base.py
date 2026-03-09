"""
EngineBase — 모든 탐지 엔진의 추상 베이스 클래스

공통 타입:
  - ThreatLevel: 위협 수준 enum
  - EngineResult: 개별 엔진 분석 결과
  - ThreatSignal: 최종 집계된 위협 시그널

사용법:
  class MyEngine(EngineBase):
      def analyze(self, tx_data): ...
      def get_engine_info(self): ...
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum
import uuid
import time


# ---------------------------------------------------------------------------
# 공통 Enum / Dataclass
# ---------------------------------------------------------------------------

class ThreatLevel(Enum):
    """위협 수준 (5단계)"""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    def __gt__(self, other):
        order = list(ThreatLevel)
        return order.index(self) > order.index(other)

    def __ge__(self, other):
        order = list(ThreatLevel)
        return order.index(self) >= order.index(other)


# ThreatLevel → 수치 점수 매핑
THREAT_LEVEL_SCORES: Dict[ThreatLevel, float] = {
    ThreatLevel.NONE: 0.0,
    ThreatLevel.LOW: 0.25,
    ThreatLevel.MEDIUM: 0.50,
    ThreatLevel.HIGH: 0.75,
    ThreatLevel.CRITICAL: 1.0,
}


@dataclass
class EngineResult:
    """개별 엔진의 분석 결과"""
    engine_name: str
    threat_level: ThreatLevel
    confidence: float                   # 0.0 ~ 1.0
    details: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine_name": self.engine_name,
            "threat_level": self.threat_level.value,
            "confidence": round(self.confidence, 4),
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
        }


@dataclass
class ThreatSignal:
    """
    ThreatAggregator가 생성하는 최종 위협 시그널.
    JSON schema 대로 직렬화 가능.
    """
    signal_id: str = field(default_factory=lambda: f"sig-{uuid.uuid4().hex[:8]}")
    timestamp: int = field(default_factory=lambda: int(time.time()))
    threat_level: ThreatLevel = ThreatLevel.NONE
    final_score: float = 0.0
    recommended_action: str = "none"    # none | alert_only | blacklist_address | pause_macro | pause_all
    engine_results: List[EngineResult] = field(default_factory=list)
    target_tx: Dict[str, Any] = field(default_factory=dict)
    response: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "timestamp": self.timestamp,
            "threat_level": self.threat_level.value,
            "final_score": round(self.final_score, 4),
            "recommended_action": self.recommended_action,
            "target_tx": self.target_tx,
            "engine_results": [r.to_dict() for r in self.engine_results],
            "response": self.response,
        }


# ---------------------------------------------------------------------------
# EngineBase ABC
# ---------------------------------------------------------------------------

class EngineBase(ABC):
    """
    모든 탐지 엔진의 베이스 클래스.

    서브클래스는 analyze()와 get_engine_info()를 구현해야 합니다.
    is_placeholder=True 인 엔진은 논문에서 'placeholder' 로 명시합니다.
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config or {}
        self.is_placeholder: bool = False
        self._call_count: int = 0
        self._total_latency_ms: float = 0.0

    @abstractmethod
    def analyze(self, tx_data: Dict[str, Any]) -> EngineResult:
        """
        트랜잭션 데이터를 분석하고 결과를 반환합니다.

        Args:
            tx_data: 트랜잭션 관련 데이터 딕셔너리.
                공통 키:
                  - from (str): 발신자 주소
                  - to (str): 수신자 주소
                  - amount (float): 금액
                  - type (str): TX 유형 (예: "mint", "transfer")
                  - call_sequence (List[str]): 함수 호출 시퀀스
                  - state_before (dict): TX 이전 컨트랙트 상태
                  - state_after (dict): TX 이후 컨트랙트 상태

        Returns:
            EngineResult 인스턴스
        """
        pass

    @abstractmethod
    def get_engine_info(self) -> Dict[str, str]:
        """
        엔진 메타 정보를 반환합니다.

        반환값에 포함해야 하는 키:
          - name: 엔진 이름
          - reference: 논문 참조
          - status: "placeholder" | "lite" | "full"
          - real_integration_point: 실제 연동 시 교체 지점 설명
        """
        pass

    def record_call(self, latency_ms: float):
        """분석 호출 통계 기록 (내부용)"""
        self._call_count += 1
        self._total_latency_ms += latency_ms

    def get_stats(self) -> Dict[str, Any]:
        """엔진 통계 반환"""
        avg = (self._total_latency_ms / self._call_count
               if self._call_count > 0 else 0.0)
        return {
            "name": self.name,
            "is_placeholder": self.is_placeholder,
            "call_count": self._call_count,
            "avg_latency_ms": round(avg, 2),
        }

    def __repr__(self) -> str:
        tag = " [PLACEHOLDER]" if self.is_placeholder else ""
        return f"{self.__class__.__name__}('{self.name}'{tag})"
