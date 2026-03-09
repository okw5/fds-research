"""
FDS Watchtower Detection Engines
================================
3개 이종 탐지 엔진 + 집계기 + 서명기 + 오케스트레이터

Engines:
  - SequenceAnomalyEngine: BERT4ETH 참조 계정 행동 분석 [PLACEHOLDER]
  - FlashLoanRuleEngine: FlashGuard 참조 공격 시퀀스 매칭 [LITE]
  - HoustonLiteInvariantChecker: HOUSTON 참조 불변성 검사 [LITE]

Pipeline:
  TX Event → [Engine1, Engine2, Engine3] → ThreatAggregator → SignalSigner → On-chain TX
"""

from .base import (
    ThreatLevel,
    EngineResult,
    ThreatSignal,
    EngineBase,
)
from .sequence_anomaly import SequenceAnomalyEngine
from .flash_loan_rule import FlashLoanRuleEngine
from .houston_lite import HoustonLiteInvariantChecker
from .aggregator import ThreatAggregator

__all__ = [
    "ThreatLevel",
    "EngineResult",
    "ThreatSignal",
    "EngineBase",
    "SequenceAnomalyEngine",
    "FlashLoanRuleEngine",
    "HoustonLiteInvariantChecker",
    "ThreatAggregator",
]
