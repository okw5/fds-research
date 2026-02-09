"""
MetricsCollector
탐지 결과를 수집하고 Precision, Recall, F1-Score, Latency 등 평가 지표 계산
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
               metadata: Optional[Dict[str, Any]] = None):
        """
        탐지 결과 기록
        
        Args:
            scenario_id: 시나리오 고유 ID
            predicted: 탐지 시스템의 예측 ('ATTACK' or 'NORMAL')
            actual: Ground Truth ('ATTACK' or 'NORMAL')
            latency_ms: 탐지 소요 시간 (밀리초)
            metadata: 추가 메타데이터
        """
        result = DetectionResult(
            scenario_id=scenario_id,
            predicted=predicted.upper(),
            actual=actual.upper(),
            latency_ms=latency_ms,
            metadata=metadata or {}
        )
        self.results.append(result)
    
    def record_from_scenario(self, scenario, predicted: str, latency_ms: float):
        """시나리오 객체에서 직접 기록"""
        self.record(
            scenario_id=scenario.id,
            predicted=predicted,
            actual=scenario.label.value,
            latency_ms=latency_ms,
            metadata={
                'scenario_type': scenario.scenario_type.value,
                'network_condition': scenario.network_condition
            }
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
        """모든 메트릭 요약"""
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
            'collection_time': {
                'start': self.start_time,
                'end': self.end_time,
                'duration_sec': round(self.end_time - self.start_time, 2) if self.end_time and self.start_time else None
            }
        }
    
    def get_comparison_row(self) -> Dict[str, Any]:
        """비교 표용 간단한 행 데이터"""
        return {
            'System': self.system_name,
            'Precision': round(self.calculate_precision(), 2),
            'Recall': round(self.calculate_recall(), 2),
            'F1-Score': round(self.calculate_f1_score(), 2),
            'Latency (ms)': round(self.calculate_avg_latency(), 0)
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
                    'metadata': r.metadata
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
                'network_condition': r.metadata.get('network_condition', '')
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
