"""
FDS 벤치마크 실험 테스트 스크립트
객관적 평가 지표 측정 확인
"""

import sys
import os

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib', 'benchmark'))

from scenario import Scenario, ScenarioType, ScenarioLabel
from data_generator import BenchmarkDataGenerator
from metrics_collector import MetricsCollector
from experiment_runner import BatchExperimentRunner, ExperimentConfig
from detection_systems import (
    ManualGovernanceSystem,
    FDSSingleLayerSystem,
    FDSTwoLayerSystem
)

def main():
    print("=" * 70)
    print("FDS 벤치마크 실험 테스트")
    print("=" * 70)
    
    # 1. 데이터셋 생성
    print("\n[1/3] 데이터셋 생성 중...")
    generator = BenchmarkDataGenerator(seed=42)
    dataset = generator.get_mixed_dataset(
        total_count=100,  # 테스트용 작은 데이터셋
        attack_ratio=0.3,
        network_mix=True
    )
    
    attack_count = sum(1 for s in dataset if s.is_attack())
    print(f"  - 총 시나리오: {len(dataset)}")
    print(f"  - 공격: {attack_count}, 정상: {len(dataset) - attack_count}")
    
    # 2. 시스템 초기화
    print("\n[2/3] 탐지 시스템 초기화...")
    systems = [
        ManualGovernanceSystem(),
        FDSSingleLayerSystem(),
        FDSTwoLayerSystem()
    ]
    for s in systems:
        print(f"  - {s.name}")
    
    # 3. 실험 실행
    print("\n[3/3] 실험 실행 중...")
    config = ExperimentConfig(iterations=1, random_seed=42)
    runner = BatchExperimentRunner(systems, dataset, config)
    
    def progress_cb(progress, msg):
        if int(progress * 100) % 20 == 0:
            print(f"  ... {progress*100:.0f}% - {msg}")
    
    results = runner.run_all(progress_callback=progress_cb)
    
    # 결과 출력
    print("\n" + "=" * 70)
    print("실험 결과 (목표 대비)")
    print("=" * 70)
    print(f"{'시스템':<25} {'Precision':>10} {'Recall':>10} {'F1-Score':>10} {'Latency':>12}")
    print("-" * 70)
    
    targets = {
        "기존 수동 거버넌스": (0.75, 0.60, 0.67, "5000ms"),
        "FDS 단일 토큰": (0.88, 0.82, 0.85, "350ms"),
        "FDS 2계층 토큰": (0.94, 0.91, 0.93, "120ms")
    }
    
    for name, collector in results.items():
        summary = collector.get_summary()
        p = summary['precision']
        r = summary['recall']
        f1 = summary['f1_score']
        lat = summary['latency']['avg_ms']
        
        target = targets.get(name, (0, 0, 0, "N/A"))
        
        print(f"{name:<25} {p:>10.2f} {r:>10.2f} {f1:>10.2f} {lat:>10.0f}ms")
        print(f"{'(목표)':<25} {target[0]:>10.2f} {target[1]:>10.2f} {target[2]:>10.2f} {target[3]:>12}")
        print()
    
    print("=" * 70)
    print("✅ 벤치마크 테스트 완료!")
    print("💡 Streamlit 페이지에서 더 상세한 실험을 수행할 수 있습니다:")
    print("   streamlit run watchtower/app.py")
    print("=" * 70)

if __name__ == "__main__":
    main()
