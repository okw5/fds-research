"""
BatchExperimentRunner
대규모 자동화 실험 실행 및 결과 집계
"""

import time
import json
import csv
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import random

# 조건부 임포트: 패키지 모드와 직접 실행 모드 지원
try:
    from .scenario import Scenario
    from .metrics_collector import MetricsCollector
    from .detection_systems.base import DetectionSystem
except ImportError:
    from scenario import Scenario
    from metrics_collector import MetricsCollector
    from detection_systems.base import DetectionSystem


@dataclass
class ExperimentConfig:
    """실험 설정"""
    iterations: int = 1                 # 반복 횟수
    shuffle_per_iteration: bool = True  # 반복마다 셔플
    random_seed: Optional[int] = None   # 랜덤 시드
    export_path: Optional[str] = None   # 결과 내보내기 경로
    verbose: bool = True                # 상세 로그


class BatchExperimentRunner:
    """
    대규모 자동화 실험 실행기
    
    기능:
    - 여러 탐지 시스템에 대해 동일 데이터셋으로 실험
    - N회 반복 실험으로 통계적 유의성 확보
    - 결과 집계 및 비교 표 생성
    - CSV/JSON 내보내기
    """
    
    def __init__(self, 
                 systems: List[DetectionSystem],
                 dataset: List[Scenario],
                 config: Optional[ExperimentConfig] = None):
        """
        Args:
            systems: 비교할 탐지 시스템 목록
            dataset: 테스트 데이터셋 (공격 + 정상 시나리오)
            config: 실험 설정
        """
        self.systems = systems
        self.dataset = dataset
        self.config = config or ExperimentConfig()
        
        # 결과 저장소
        self.collectors: Dict[str, MetricsCollector] = {}
        self.iteration_results: List[Dict[str, Any]] = []
        
        # 진행 상황 추적
        self.total_experiments = 0
        self.completed_experiments = 0
        self.current_system = ""
        self.current_iteration = 0
        
        # 랜덤 시드 설정
        if self.config.random_seed is not None:
            random.seed(self.config.random_seed)
    
    def run_all(self, 
                progress_callback: Optional[callable] = None) -> Dict[str, MetricsCollector]:
        """
        모든 시스템에 대해 실험 실행
        
        Args:
            progress_callback: 진행률 콜백 함수 (progress: float, message: str)
            
        Returns:
            Dict[str, MetricsCollector]: 시스템별 메트릭 수집기
        """
        self.total_experiments = len(self.systems) * len(self.dataset) * self.config.iterations
        self.completed_experiments = 0
        
        for system in self.systems:
            self.current_system = system.name
            collector = MetricsCollector(system.name)
            collector.start_collection()
            
            for iteration in range(self.config.iterations):
                self.current_iteration = iteration + 1
                
                # 반복마다 셔플 (선택적)
                if self.config.shuffle_per_iteration:
                    random.shuffle(self.dataset)
                
                for scenario in self.dataset:
                    # 탐지 실행
                    prediction, latency_ms = system.detect(scenario)
                    
                    # 결과 기록
                    collector.record_from_scenario(scenario, prediction, latency_ms)
                    
                    # 진행률 업데이트
                    self.completed_experiments += 1
                    if progress_callback:
                        progress = self.completed_experiments / self.total_experiments
                        msg = f"{system.name} - Iteration {iteration + 1}/{self.config.iterations}"
                        progress_callback(progress, msg)
            
            collector.end_collection()
            self.collectors[system.name] = collector
            
            # 반복별 결과 저장
            self.iteration_results.append({
                'system': system.name,
                'summary': collector.get_summary()
            })
        
        return self.collectors
    
    def get_comparison_table(self) -> List[Dict[str, Any]]:
        """
        시스템 비교 표 생성
        
        Returns:
            List[Dict]: 각 시스템의 비교 데이터
        """
        table = []
        for name, collector in self.collectors.items():
            row = collector.get_comparison_row()
            table.append(row)
        return table
    
    def get_detailed_comparison(self) -> Dict[str, Any]:
        """상세 비교 데이터 반환"""
        comparison = {
            'experiment_info': {
                'total_systems': len(self.systems),
                'dataset_size': len(self.dataset),
                'iterations': self.config.iterations,
                'total_experiments': self.total_experiments,
                'timestamp': datetime.now().isoformat()
            },
            'systems': {}
        }
        
        for name, collector in self.collectors.items():
            comparison['systems'][name] = collector.get_summary()
        
        return comparison
    
    def get_confusion_matrix_comparison(self) -> Dict[str, Dict[str, int]]:
        """각 시스템의 혼동 행렬 비교"""
        return {
            name: collector.get_confusion_matrix()
            for name, collector in self.collectors.items()
        }
    
    def export_to_csv(self, filepath: str):
        """결과를 CSV로 내보내기"""
        all_rows = []
        for name, collector in self.collectors.items():
            all_rows.extend(collector.to_csv_rows())
        
        if not all_rows:
            return
        
        keys = all_rows[0].keys()
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_rows)
    
    def export_summary_csv(self, filepath: str):
        """요약 결과를 CSV로 내보내기"""
        table = self.get_comparison_table()
        if not table:
            return
        
        keys = table[0].keys()
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(table)
    
    def export_to_json(self, filepath: str):
        """결과를 JSON으로 내보내기"""
        data = self.get_detailed_comparison()
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def print_summary(self):
        """콘솔에 요약 출력"""
        print("\n" + "=" * 70)
        print("실험 결과 요약")
        print("=" * 70)
        
        table = self.get_comparison_table()
        
        # 헤더
        headers = list(table[0].keys()) if table else []
        print(f"{'시스템':<20} {'Precision':<12} {'Recall':<12} {'F1-Score':<12} {'Latency (ms)':<12}")
        print("-" * 70)
        
        for row in table:
            print(f"{row['System']:<20} {row['Precision']:<12} {row['Recall']:<12} {row['F1-Score']:<12} {row['Latency (ms)']:<12}")
        
        print("=" * 70 + "\n")
    
    def reset(self):
        """실행기 초기화"""
        self.collectors = {}
        self.iteration_results = []
        self.completed_experiments = 0
        for system in self.systems:
            system.reset_stats()


class QuickBenchmark:
    """
    빠른 벤치마크 실행을 위한 헬퍼 클래스
    """
    
    @staticmethod
    def run_default_comparison(dataset_size: int = 1000,
                               attack_ratio: float = 0.3,
                               seed: int = 42) -> Dict[str, MetricsCollector]:
        """
        기본 설정으로 빠른 비교 실험 실행
        
        Args:
            dataset_size: 데이터셋 크기
            attack_ratio: 공격 비율
            seed: 랜덤 시드
        """
        from .data_generator import BenchmarkDataGenerator
        from .detection_systems import (
            ManualGovernanceSystem,
            FDSSingleLayerSystem,
            FDSTwoLayerSystem
        )
        
        # 데이터셋 생성
        generator = BenchmarkDataGenerator(seed=seed)
        dataset = generator.get_mixed_dataset(
            total_count=dataset_size,
            attack_ratio=attack_ratio,
            network_mix=True
        )
        
        # 시스템 초기화
        systems = [
            ManualGovernanceSystem(),
            FDSSingleLayerSystem(),
            FDSTwoLayerSystem()
        ]
        
        # 실험 실행
        config = ExperimentConfig(iterations=1, random_seed=seed)
        runner = BatchExperimentRunner(systems, dataset, config)
        results = runner.run_all()
        
        runner.print_summary()
        
        return results
    
    @staticmethod
    def run_statistical_comparison(dataset_size: int = 500,
                                   iterations: int = 10,
                                   seed: int = 42) -> Dict[str, MetricsCollector]:
        """
        통계적 유의성을 위한 반복 실험
        """
        from .data_generator import BenchmarkDataGenerator
        from .detection_systems import (
            ManualGovernanceSystem,
            FDSSingleLayerSystem,
            FDSTwoLayerSystem
        )
        
        generator = BenchmarkDataGenerator(seed=seed)
        dataset = generator.get_mixed_dataset(
            total_count=dataset_size,
            attack_ratio=0.3,
            network_mix=True
        )
        
        systems = [
            ManualGovernanceSystem(),
            FDSSingleLayerSystem(),
            FDSTwoLayerSystem()
        ]
        
        config = ExperimentConfig(
            iterations=iterations,
            shuffle_per_iteration=True,
            random_seed=seed
        )
        
        runner = BatchExperimentRunner(systems, dataset, config)
        results = runner.run_all()
        
        runner.print_summary()
        
        return results
