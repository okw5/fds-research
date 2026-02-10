"""
MetricsCollector
탐지 결과를 수집하고 Precision, Recall, F1-Score, Latency,
피해금액(Financial Loss), 서비스 중단 시간(Service Downtime),
서비스 가용성(Availability) 등 평가 지표 계산

v2: 확장 지표 추가
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import time
import json
from datetime import datetime


@dataclass
class DetectionResult:
    """개별 탐지 결과"""
    scenario_id: str
    predicted: str      # 'ATTACK' or 'NORMAL'
    actual: str         # 'ATTACK' or 'NORMAL' (Ground Truth)
    latency_ms: float   # 탐지 소요 시간 (밀리초)
    timestamp: float = field(default_factory=lambda: time.time())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 확장 지표
    financial_loss: float = 0.0           # 피해금액 (USD)
    service_downtime_sec: float = 0.0     # 서비스 중단 시간 (초)
    micro_available: bool = True          # 소액결제 가용 여부
    freeze_scope: str = 'none'            # 동결 범위
    response_action: str = 'none'         # 방어 조치
    
    @property
    def is_true_positive(self) -> bool:
        return self.predicted == 'ATTACK' and self.actual == 'ATTACK'
    
    @property
    def is_true_negative(self) -> bool:
        return self.predicted == 'NORMAL' and self.actual == 'NORMAL'
    
    @property
    def is_false_positive(self) -> bool:
        return self.predicted == 'ATTACK' and self.actual == 'NORMAL'
    
    @property
    def is_false_negative(self) -> bool:
        return self.predicted == 'NORMAL' and self.actual == 'ATTACK'
    
    @property
    def is_correct(self) -> bool:
        return self.predicted == self.actual


class MetricsCollector:
    """
    탐지 결과를 수집하고 평가 지표를 계산하는 클래스
    
    주요 지표:
    - Precision: TP / (TP + FP) - 탐지된 공격 중 실제 공격의 비율
    - Recall: TP / (TP + FN) - 실제 공격 중 탐지된 비율
    - F1-Score: 2 * (Precision * Recall) / (Precision + Recall)
    - Average Latency: 평균 탐지 지연 시간 (ms)
    
    확장 지표 (v2):
    - Financial Loss: 총 피해금액 / 평균 피해금액
    - Service Downtime: 총 서비스 중단 시간 / 평균 중단 시간
    - Micro Availability: 소액결제 서비스 가용률
    - Freeze Scope Distribution: 동결 범위 분포
    """
    
    def __init__(self, system_name: str = "unknown"):
        self.system_name = system_name
        self.results: List[DetectionResult] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
    
    def start_collection(self):
        """수집 시작 시간 기록"""
        self.start_time = time.time()
    
    def end_collection(self):
        """수집 종료 시간 기록"""
        self.end_time = time.time()
    
    def record(self, 
               scenario_id: str,
               predicted: str, 
               actual: str, 
               latency_ms: float,
               metadata: Optional[Dict[str, Any]] = None,
               financial_loss: float = 0.0,
               service_downtime_sec: float = 0.0,
               micro_available: bool = True,
               freeze_scope: str = 'none',
               response_action: str = 'none'):
        """
        탐지 결과 기록
        
        Args:
            scenario_id: 시나리오 고유 ID
            predicted: 탐지 시스템의 예측 ('ATTACK' or 'NORMAL')
            actual: Ground Truth ('ATTACK' or 'NORMAL')
            latency_ms: 탐지 소요 시간 (밀리초)
            metadata: 추가 메타데이터
            financial_loss: 피해금액 (USD)
            service_downtime_sec: 서비스 중단 시간 (초)
            micro_available: 소액결제 가용 여부
            freeze_scope: 동결 범위
            response_action: 방어 조치
        """
        result = DetectionResult(
            scenario_id=scenario_id,
            predicted=predicted.upper(),
            actual=actual.upper(),
            latency_ms=latency_ms,
            metadata=metadata or {},
            financial_loss=financial_loss,
            service_downtime_sec=service_downtime_sec,
            micro_available=micro_available,
            freeze_scope=freeze_scope,
            response_action=response_action
        )
        self.results.append(result)
    
    def record_from_scenario(self, scenario, predicted: str, latency_ms: float,
                             financial_loss: float = 0.0,
                             service_downtime_sec: float = 0.0,
                             micro_available: bool = True,
                             freeze_scope: str = 'none',
                             response_action: str = 'none'):
        """시나리오 객체에서 직접 기록"""
        self.record(
            scenario_id=scenario.id,
            predicted=predicted,
            actual=scenario.label.value,
            latency_ms=latency_ms,
            metadata={
                'scenario_type': scenario.scenario_type.value,
                'network_condition': scenario.network_condition
            },
            financial_loss=financial_loss,
            service_downtime_sec=service_downtime_sec,
            micro_available=micro_available,
            freeze_scope=freeze_scope,
            response_action=response_action
        )
    
    def record_from_response(self, scenario, response):
        """DetectionResponse 객체에서 기록"""
        self.record(
            scenario_id=scenario.id,
            predicted=response.prediction,
            actual=scenario.label.value,
            latency_ms=response.latency_ms,
            metadata={
                'scenario_type': scenario.scenario_type.value,
                'network_condition': scenario.network_condition
            },
            financial_loss=response.financial_loss,
            service_downtime_sec=response.service_downtime_sec,
            micro_available=response.micro_available,
            freeze_scope=response.freeze_scope,
            response_action=response.response_action
        )
    
    # =========================================================================
    # 기본 카운트 메서드
    # =========================================================================
    
    def get_true_positives(self) -> int:
        """True Positive 수 (공격을 공격으로 정확히 탐지)"""
        return sum(1 for r in self.results if r.is_true_positive)
    
    def get_true_negatives(self) -> int:
        """True Negative 수 (정상을 정상으로 정확히 판단)"""
        return sum(1 for r in self.results if r.is_true_negative)
    
    def get_false_positives(self) -> int:
        """False Positive 수 (정상을 공격으로 오탐)"""
        return sum(1 for r in self.results if r.is_false_positive)
    
    def get_false_negatives(self) -> int:
        """False Negative 수 (공격을 정상으로 미탐)"""
        return sum(1 for r in self.results if r.is_false_negative)
    
    # =========================================================================
    # 핵심 평가 지표
    # =========================================================================
    
    def calculate_precision(self) -> float:
        """
        Precision = TP / (TP + FP)
        탐지된 공격 중 실제 공격의 비율 (정밀도)
        """
        tp = self.get_true_positives()
        fp = self.get_false_positives()
        
        if tp + fp == 0:
            return 0.0
        
        return tp / (tp + fp)
    
    def calculate_recall(self) -> float:
        """
        Recall = TP / (TP + FN)
        실제 공격 중 탐지된 비율 (재현율, 민감도)
        """
        tp = self.get_true_positives()
        fn = self.get_false_negatives()
        
        if tp + fn == 0:
            return 0.0
        
        return tp / (tp + fn)
    
    def calculate_f1_score(self) -> float:
        """
        F1 = 2 * (Precision * Recall) / (Precision + Recall)
        Precision과 Recall의 조화 평균
        """
        precision = self.calculate_precision()
        recall = self.calculate_recall()
        
        if precision + recall == 0:
            return 0.0
        
        return 2 * (precision * recall) / (precision + recall)
    
    def calculate_accuracy(self) -> float:
        """
        Accuracy = (TP + TN) / Total
        전체 정확도
        """
        if len(self.results) == 0:
            return 0.0
        
        correct = sum(1 for r in self.results if r.is_correct)
        return correct / len(self.results)
    
    def calculate_specificity(self) -> float:
        """
        Specificity = TN / (TN + FP)
        정상을 정상으로 판단한 비율 (특이도)
        """
        tn = self.get_true_negatives()
        fp = self.get_false_positives()
        
        if tn + fp == 0:
            return 0.0
        
        return tn / (tn + fp)
    
    # =========================================================================
    # Latency 지표
    # =========================================================================
    
    def calculate_avg_latency(self) -> float:
        """평균 탐지 지연 시간 (ms)"""
        if len(self.results) == 0:
            return 0.0
        
        return sum(r.latency_ms for r in self.results) / len(self.results)
    
    def calculate_median_latency(self) -> float:
        """중앙값 탐지 지연 시간 (ms)"""
        if len(self.results) == 0:
            return 0.0
        
        latencies = sorted([r.latency_ms for r in self.results])
        mid = len(latencies) // 2
        
        if len(latencies) % 2 == 0:
            return (latencies[mid - 1] + latencies[mid]) / 2
        return latencies[mid]
    
    def calculate_p95_latency(self) -> float:
        """95 백분위 탐지 지연 시간 (ms)"""
        if len(self.results) == 0:
            return 0.0
        
        latencies = sorted([r.latency_ms for r in self.results])
        idx = int(len(latencies) * 0.95)
        return latencies[min(idx, len(latencies) - 1)]
    
    def calculate_max_latency(self) -> float:
        """최대 탐지 지연 시간 (ms)"""
        if len(self.results) == 0:
            return 0.0
        
        return max(r.latency_ms for r in self.results)
    
    # =========================================================================
    # 피해금액 (Financial Loss) 지표
    # =========================================================================
    
    def calculate_total_financial_loss(self) -> float:
        """총 피해금액 (USD)"""
        return sum(r.financial_loss for r in self.results)
    
    def calculate_avg_financial_loss(self) -> float:
        """평균 피해금액 (USD, 공격 시나리오 기준)"""
        attack_results = [r for r in self.results if r.actual == 'ATTACK']
        if not attack_results:
            return 0.0
        return sum(r.financial_loss for r in attack_results) / len(attack_results)
    
    def calculate_max_financial_loss(self) -> float:
        """최대 단일 피해금액 (USD)"""
        if not self.results:
            return 0.0
        return max(r.financial_loss for r in self.results)
    
    def calculate_loss_prevention_rate(self) -> float:
        """
        피해 방지율 (%)
        = 1 - (실제 피해 / 잠재적 전체 피해)
        """
        attack_results = [r for r in self.results if r.actual == 'ATTACK']
        if not attack_results:
            return 1.0
        
        # 잠재적 전체 피해: 미탐 시 100% 피해 기준
        # 실제 피해: 시스템이 산출한 피해금액
        total_potential = 0.0
        total_actual_loss = 0.0
        
        for r in attack_results:
            # 잠재적 피해: 메타데이터에서 amount 추출
            potential = r.metadata.get('amount', 
                       r.metadata.get('total_amount', 
                       r.metadata.get('loan_amount', r.financial_loss)))
            if potential == 0 and r.financial_loss > 0:
                # fallback
                if r.is_false_negative:
                    potential = r.financial_loss
                else:
                    potential = r.financial_loss / 0.05 if r.financial_loss > 0 else 0
            
            total_potential += potential if potential > 0 else r.financial_loss
            total_actual_loss += r.financial_loss
        
        if total_potential == 0:
            return 1.0
        
        return 1.0 - (total_actual_loss / total_potential)
    
    # =========================================================================
    # 서비스 중단 시간 (Downtime) 지표
    # =========================================================================
    
    def calculate_total_downtime(self) -> float:
        """총 서비스 중단 시간 (초)"""
        return sum(r.service_downtime_sec for r in self.results)
    
    def calculate_avg_downtime(self) -> float:
        """평균 서비스 중단 시간 (초, 공격 탐지 건 기준)"""
        detected = [r for r in self.results if r.predicted == 'ATTACK']
        if not detected:
            return 0.0
        return sum(r.service_downtime_sec for r in detected) / len(detected)
    
    def calculate_max_downtime(self) -> float:
        """최대 단일 서비스 중단 시간 (초)"""
        if not self.results:
            return 0.0
        return max(r.service_downtime_sec for r in self.results)
    
    def calculate_total_downtime_minutes(self) -> float:
        """총 서비스 중단 시간 (분)"""
        return self.calculate_total_downtime() / 60.0
    
    def calculate_avg_downtime_minutes(self) -> float:
        """평균 서비스 중단 시간 (분)"""
        return self.calculate_avg_downtime() / 60.0
    
    # =========================================================================
    # 서비스 가용성 (Availability) 지표
    # =========================================================================
    
    def calculate_micro_availability(self) -> float:
        """
        소액결제 서비스 가용률 (%)
        = 소액결제 가능했던 건수 / 전체 건수
        
        2계층 시스템의 핵심 장점: 소액결제 항상 가용
        """
        if not self.results:
            return 1.0
        
        available_count = sum(1 for r in self.results if r.micro_available)
        return available_count / len(self.results)
    
    def calculate_full_network_freeze_count(self) -> int:
        """전체 네트워크 동결 횟수"""
        return sum(1 for r in self.results if r.freeze_scope == 'full_network')
    
    def calculate_selective_freeze_count(self) -> int:
        """선택적 동결 횟수"""
        return sum(1 for r in self.results if r.freeze_scope == 'selective')
    
    def get_freeze_scope_distribution(self) -> Dict[str, int]:
        """동결 범위 분포"""
        distribution = {'none': 0, 'selective': 0, 'full_network': 0}
        for r in self.results:
            if r.freeze_scope in distribution:
                distribution[r.freeze_scope] += 1
            else:
                distribution[r.freeze_scope] = 1
        return distribution
    
    def get_response_action_distribution(self) -> Dict[str, int]:
        """방어 조치 유형 분포"""
        distribution = {}
        for r in self.results:
            distribution[r.response_action] = distribution.get(r.response_action, 0) + 1
        return distribution
    
    # =========================================================================
    # 요약 및 내보내기
    # =========================================================================
    
    def get_confusion_matrix(self) -> Dict[str, int]:
        """혼동 행렬 반환"""
        return {
            'TP': self.get_true_positives(),
            'TN': self.get_true_negatives(),
            'FP': self.get_false_positives(),
            'FN': self.get_false_negatives()
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """모든 메트릭 요약 (확장 지표 포함)"""
        return {
            'system_name': self.system_name,
            'total_samples': len(self.results),
            'confusion_matrix': self.get_confusion_matrix(),
            'precision': round(self.calculate_precision(), 4),
            'recall': round(self.calculate_recall(), 4),
            'f1_score': round(self.calculate_f1_score(), 4),
            'accuracy': round(self.calculate_accuracy(), 4),
            'specificity': round(self.calculate_specificity(), 4),
            'latency': {
                'avg_ms': round(self.calculate_avg_latency(), 2),
                'median_ms': round(self.calculate_median_latency(), 2),
                'p95_ms': round(self.calculate_p95_latency(), 2),
                'max_ms': round(self.calculate_max_latency(), 2)
            },
            # 확장 지표
            'financial_loss': {
                'total_usd': round(self.calculate_total_financial_loss(), 2),
                'avg_per_attack_usd': round(self.calculate_avg_financial_loss(), 2),
                'max_single_usd': round(self.calculate_max_financial_loss(), 2),
                'prevention_rate': round(self.calculate_loss_prevention_rate(), 4)
            },
            'service_downtime': {
                'total_sec': round(self.calculate_total_downtime(), 2),
                'total_min': round(self.calculate_total_downtime_minutes(), 2),
                'avg_per_detection_sec': round(self.calculate_avg_downtime(), 2),
                'avg_per_detection_min': round(self.calculate_avg_downtime_minutes(), 2),
                'max_single_sec': round(self.calculate_max_downtime(), 2)
            },
            'availability': {
                'micro_availability': round(self.calculate_micro_availability(), 4),
                'full_network_freezes': self.calculate_full_network_freeze_count(),
                'selective_freezes': self.calculate_selective_freeze_count(),
                'freeze_scope_distribution': self.get_freeze_scope_distribution(),
                'response_action_distribution': self.get_response_action_distribution()
            },
            'collection_time': {
                'start': self.start_time,
                'end': self.end_time,
                'duration_sec': round(self.end_time - self.start_time, 2) if self.end_time and self.start_time else None
            }
        }
    
    def get_comparison_row(self) -> Dict[str, Any]:
        """비교 표용 간단한 행 데이터 (확장 지표 포함)"""
        return {
            'System': self.system_name,
            'Precision': round(self.calculate_precision(), 2),
            'Recall': round(self.calculate_recall(), 2),
            'F1-Score': round(self.calculate_f1_score(), 2),
            'Latency (ms)': round(self.calculate_avg_latency(), 0),
            'Financial Loss ($)': round(self.calculate_total_financial_loss(), 0),
            'Avg Downtime (min)': round(self.calculate_avg_downtime_minutes(), 1),
            'Micro Availability': f"{self.calculate_micro_availability()*100:.1f}%",
        }
    
    def export_results(self, filepath: str):
        """결과를 JSON 파일로 내보내기"""
        data = {
            'summary': self.get_summary(),
            'results': [
                {
                    'scenario_id': r.scenario_id,
                    'predicted': r.predicted,
                    'actual': r.actual,
                    'latency_ms': r.latency_ms,
                    'is_correct': r.is_correct,
                    'timestamp': r.timestamp,
                    'metadata': r.metadata,
                    'financial_loss': r.financial_loss,
                    'service_downtime_sec': r.service_downtime_sec,
                    'micro_available': r.micro_available,
                    'freeze_scope': r.freeze_scope,
                    'response_action': r.response_action
                }
                for r in self.results
            ]
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def to_csv_rows(self) -> List[Dict[str, Any]]:
        """CSV 내보내기용 행 데이터"""
        return [
            {
                'system': self.system_name,
                'scenario_id': r.scenario_id,
                'predicted': r.predicted,
                'actual': r.actual,
                'latency_ms': r.latency_ms,
                'is_correct': r.is_correct,
                'result_type': 'TP' if r.is_true_positive else 'TN' if r.is_true_negative else 'FP' if r.is_false_positive else 'FN',
                'scenario_type': r.metadata.get('scenario_type', ''),
                'network_condition': r.metadata.get('network_condition', ''),
                'financial_loss': r.financial_loss,
                'service_downtime_sec': r.service_downtime_sec,
                'micro_available': r.micro_available,
                'freeze_scope': r.freeze_scope,
                'response_action': r.response_action
            }
            for r in self.results
        ]
    
    def reset(self):
        """수집된 데이터 초기화"""
        self.results = []
        self.start_time = None
        self.end_time = None
    
    def __len__(self) -> int:
        return len(self.results)
    
    def __repr__(self) -> str:
        return f"MetricsCollector(system='{self.system_name}', samples={len(self.results)}, precision={self.calculate_precision():.2f}, recall={self.calculate_recall():.2f})"
