"""
DetectionSystem 추상 베이스 클래스
모든 탐지 시스템이 구현해야 하는 인터페이스 정의

v3: 지수 증가 피해 모델, Macro 공격 후 Micro 2차 피해 추적 추가
"""

import math
from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional
from dataclasses import dataclass, field

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
    탐지 결과 응답 데이터 클래스 (v3)
    
    Attributes:
        prediction: 예측 결과 ('ATTACK' or 'NORMAL')
        latency_ms: 탐지 소요 시간 (밀리초)
        financial_loss: 탐지까지 발생한 예상 직접 피해금액 (USD)
        micro_secondary_loss: Macro pause 이후 Micro 채널로 유입된 위조 토큰에 의한 2차 피해 (2계층 전용)
        leaked_tokens: Macro 탐지 전 생성된 위조 토큰 수 (2계층 전용 추적)
        service_downtime_sec: 방어 조치로 인한 서비스 중단 시간 (초)
        downtime_opportunity_cost: 서비스 중단 기간 동안 포기한 정상 거래 수익 (단일계층·수동 전용)
        micro_available: 소액결제 서비스 가용 여부 (True=유지, False=중단)
        freeze_scope: 동결 범위 ('none', 'selective', 'full_network')
        response_action: 방어 조치 유형 ('none', 'pause_macro', 'freeze_wallet', 'pause_all')
    """
    prediction: str
    latency_ms: float
    financial_loss: float = 0.0
    micro_secondary_loss: float = 0.0      # 2계층 Micro 채널 2차 피해
    leaked_tokens: float = 0.0             # Macro 탐지 전 생성된 위조 토큰
    service_downtime_sec: float = 0.0
    downtime_opportunity_cost: float = 0.0  # 단일/수동의 Downtime 간접 손실
    micro_available: bool = True
    freeze_scope: str = 'none'       # none, selective, full_network
    response_action: str = 'none'    # none, pause_macro, freeze_wallet, pause_all
    gas_details: Dict[str, float] = field(default_factory=dict)


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
    
    # =========================================================================
    # 공격 유형별 확산 속도 (초당 피해 확산 지수)
    # 높을수록 빠른 시간 안에 피해가 기하급수적으로 늘어남
    # =========================================================================
    ATTACK_VELOCITY = {
        'infinite_mint':    0.18,   # 대량 발행 → 토큰 가치 즉시 희석, 매우 빠름
        'reserve_drain':    0.14,   # 금고 고갈 → 준비금 비례 손실, 빠름
        'flash_loan_depeg': 0.09,   # 플래시론 → 블록 단위 진행, 중간
        'sybil_attack':     0.05,   # 분산 공격 → 상대적으로 느림
        'threshold_evasion': 0.03,  # 소액 반복 → 느림
        'gradual_escalation': 0.04, # 점진 증가 → 느림
        'camouflage':       0.02,   # 위장 → 느림
    }

    # 일일 정상 거래량 (달러) — 서비스 중단 기회비용 계산용
    DAILY_NORMAL_VOLUME_USD = 5_000_000  # 하루 500만 달러 거래량 가정

    def _estimate_financial_loss(self, scenario: Scenario, latency_ms: float,
                                  detected: bool) -> float:
        """
        지수 증가 피해 모델 (v2)

        발행코인에 치명적인 공격(무한발행·준비금탈취)은 탐지가 늦을수록
        피해가 기하급수적으로 증가합니다.

        공식:
            loss = attack_value × (1 - e^(-velocity × latency_sec))
            → latency가 길수록 손실률이 1(100%)에 수렴

        미탐(FN)인 경우:
            수동 거버넌스 대응 시간(평균 300초) 동안 지속 진행된 것으로 가정.
        """
        if not scenario.is_attack():
            return 0.0

        # 공격 금액 추출
        attack_amount = float(scenario.parameters.get(
            'amount', scenario.parameters.get(
                'total_amount', scenario.parameters.get('loan_amount', 0))))

        s_type = scenario.scenario_type.value
        velocity = self.ATTACK_VELOCITY.get(s_type, 0.05)

        if not detected:
            # 미탐(FN): 수동 대응 시간(~300초)까지 공격이 진행된 것으로 가정
            effective_latency_sec = 300.0
        else:
            effective_latency_sec = latency_ms / 1000.0

        # 지수 누적 손실률: 1 - e^(-v*t), 최대 98%
        loss_ratio = min(0.98, 1.0 - math.exp(-velocity * effective_latency_sec))
        return attack_amount * loss_ratio

    def _estimate_downtime_opportunity_cost(self, service_downtime_sec: float) -> float:
        """
        서비스 중단 기간 동안 처리하지 못한 정상 거래의 기회 손실 계산.
        단일계층·수동거버넌스의 '전체 pause' 비용을 정량화합니다.

        opportunity_cost = (daily_volume / 86400) × downtime_sec
        """
        return (self.DAILY_NORMAL_VOLUME_USD / 86400.0) * service_downtime_sec
    
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
        """
        수동 거버넌스 시스템 설정 — 인간 4단계 워크플로우 파라미터

        [단계별 시간 구성]
        ① 알림 수신·확인   : 30~120 초  (담당자 알림 인지)
        ② 상황 판단·승인   : 120~600 초  (심각도 평가, 대응 결정)
          → latency_ms = (①+②) × 1000  (서킷 브레이커 결정까지)
        ③ 컨트랙트 pause  : 60~300 초   (수동 트랜잭션 서명·전송)
        ④ 조사·복구       : 900~3600 초  (원인 분석 후 unpause)
          → service_downtime_sec = ③+④

        논문 목표: 총 대응 시간 30~80분 = latency(2.5~12분) + downtime(16~65분)
        """
        return {
            # ① 알림 수신~확인 (초)
            'alert_notice_min_sec': 30,
            'alert_notice_max_sec': 120,
            # ② 상황 판단·승인 (초) — 공격 유형 복잡도에 따라 배수 조정
            'situation_assess_min_sec': 120,
            'situation_assess_max_sec': 600,
            # ③ 컨트랙트 pause 실행 (초)
            'contract_pause_min_sec': 60,
            'contract_pause_max_sec': 300,
            # ④ 조사·복구 (초)
            'recovery_min_sec': 900,
            'recovery_max_sec': 3600,
            # 탐지 정확도 & 오탐율 (인간 인지 한계)
            'detection_accuracy': 0.68,
            'false_positive_rate': 0.15,
        }
    
    @classmethod
    def get_fds_single_layer_config(cls) -> Dict[str, Any]:
        """
        FDS 단일계층 설정 — 동일 엔진으로 Macro+Micro 모두 처리

        [대형 Macro 공격]
        - latency: 250~450ms (2계층과 동일 탐지 엔진, 동일 속도)
        - 전체 pause → downtime 5~30분

        [소규모 Micro 공격 (시빌·임계회피)]
        - 개별 건이 임계값 미달 → 누적 패턴 윈도우 필요
        - 기본 latency × micro_detection_delay_multiplier (3.5배)
        - 결과: Micro 공격 탐지 800~1600ms (vs 2계층 60ms)

        [엔진 과부하 모델]
        - overload_threshold_tx 건 이상 처리 시 과부하 진입
        - 과부하 중: latency × overload_latency_multiplier
        - 과부하 중: 정상 거래 FPR += overload_fpr_increment (최대 max_overload_fpr)
        """
        return {
            # 기본 latency (Macro 공격 기준, 2계층 Macro 엔진과 동일)
            'base_latency_ms': 250,
            'latency_variance_ms': 100,
            'congestion_multiplier': 2.5,
            # 임계값
            'mint_threshold': cls.DEFAULT_MINT_THRESHOLD,
            'drain_threshold': cls.DEFAULT_DRAIN_THRESHOLD,
            'depeg_threshold': cls.DEFAULT_DEPEG_THRESHOLD,
            'window_size': cls.DEFAULT_WINDOW_SIZE,
            # Micro 공격 누적 탐지 지연 (개별 건 임계값 미달 시 누적 필요)
            'micro_detection_delay_multiplier': 3.5,
            # 엔진 과부하 파라미터
            'overload_threshold_tx': 50,        # 이 건 이상 처리 시 과부하 시작
            'overload_fpr_increment': 0.04,     # 과부하 단계당 FPR +4%
            'overload_latency_multiplier': 1.8, # 과부하 시 latency 1.8배
            'max_overload_fpr': 0.18,           # FPR 최대 18%까지 상승
        }
    
    @classmethod
    def get_fds_two_layer_config(cls) -> Dict[str, Any]:
        """
        FDS 2계층 설정 — Macro/Micro 엔진 완전 분리

        [Macro 엔진 — 대형 공격 전담]
        - 사전 서명 검증 포함: 80~160ms (평균 120ms)
        - 대형 Macro 공격 시 단일계층과 유사한 속도

        [Micro 엔진 — 소규모 공격 전담, 독립 실행]
        - 경량 처리, 과부하 없음: 40~80ms (평균 60ms)
        - 시빌·임계회피 공격 시 단일계층보다 훨씬 빠름
        - 전체 엔진과 격리되어 과부하 면역(overload_immune=True)

        [핵심 차별점]
        - 단일계층: Micro 공격 시 800~1600ms + FPR 상승
        - 2계층:   Micro 공격 시 60ms + FPR 유지 (엔진 분리)
        """
        return {
            # Macro 엔진 파라미터 (사전 서명 검증 포함)
            'macro_base_latency_ms': 120,
            'macro_latency_variance_ms': 40,
            # Micro 엔진 파라미터 (경량, 독립)
            'micro_base_latency_ms': 60,
            'micro_latency_variance_ms': 20,
            # 공통
            'congestion_multiplier': 1.5,
            'drain_threshold': cls.DEFAULT_DRAIN_THRESHOLD * 0.5,
            'depeg_threshold': cls.DEFAULT_DEPEG_THRESHOLD * 0.6,
            'window_size': cls.DEFAULT_WINDOW_SIZE,
            'micro_threshold': cls.DEFAULT_MICRO_THRESHOLD,
            'macro_threshold': cls.DEFAULT_MACRO_THRESHOLD,
            # 과부하 면역 (엔진이 분리되어 있으므로 Micro 처리가 Macro에 영향 없음)
            'overload_immune': True,
            'micro_fast_path': True,
        }

