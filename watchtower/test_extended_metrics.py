"""
FDS 벤치마크 시스템 확장 지표 테스트
- DetectionResponse 사용 확인
- 피해금액, 서비스 중단 시간 계산 확인
- 3개 시스템 비교
"""

import sys
import os
import random

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib', 'benchmark'))

from scenario import Scenario
from data_generator import BenchmarkDataGenerator
from experiment_runner import BatchExperimentRunner, ExperimentConfig
from detection_systems import (
    ManualGovernanceSystem, 
    FDSSingleLayerSystem, 
    FDSTwoLayerSystem
)

def main():
    print("=" * 80)
    print("FDS 벤치마크 확장 지표 테스트")
    print("=" * 80)
    
    # 1. 데이터셋 생성 (작게 50개만)
    print("\n[1] 데이터셋 생성 중...")
    generator = BenchmarkDataGenerator(seed=42)
    dataset = generator.get_mixed_dataset(
        total_count=50,
        attack_ratio=0.3,
        network_mix=True
    )
    print(f"  - 총 {len(dataset)}개 시나리오 생성됨")
    
    # 2. 시스템 초기화
    systems = [
        ManualGovernanceSystem(),
        FDSSingleLayerSystem(),
        FDSTwoLayerSystem()
    ]
    
    # 3. 실험 실행 (확장 지표 사용)
    print("\n[2] 실험 실행 중 (use_extended=True)...")
    config = ExperimentConfig(
        iterations=1, 
        random_seed=42, 
        use_extended=True  # 중요!
    )
    
    runner = BatchExperimentRunner(systems, dataset, config)
    runner.run_all()
    
    # 4. 결과 출력
    print("\n[3] 결과 확인")
    results = runner.get_detailed_comparison()
    
    for system_name, data in results['systems'].items():
        print(f"\n--- {system_name} ---")
        
        # 기본 지표
        p = data['precision']
        r = data['recall']
        f1 = data['f1_score']
        lat = data['latency']['avg_ms']
        print(f"  [Security] Precision: {p:.2f}, Recall: {r:.2f}, F1: {f1:.2f}, Latency: {lat:.0f}ms")
        
        # 확장 지표 (신규)
        loss = data['financial_loss']['total_usd']
        downtime = data['service_downtime']['avg_per_detection_min']
        avail = data['availability']['micro_availability']
        
        print(f"  [Business] Total Loss: ${loss:,.0f}")
        print(f"             Avg Downtime: {downtime:.1f} min")
        print(f"             Micro Availability: {avail*100:.1f}%")
        
        # 검증 로직
        if system_name == "FDS 2계층 토큰":
            if avail < 0.9:
                print("  [Warning] 2계층 토큰의 가용성이 너무 낮습니다! (기대치: >90%)")
            if downtime > 10:
                print("  [Warning] 2계층 토큰의 중단 시간이 너무 깁니다! (기대치: <5분)")
        
        elif system_name == "기존 수동 거버넌스":
            if avail > 0.1:
                print("  [Warning] 수동 거버넌스의 가용성이 너무 높습니다! (기대치: ~0%)")
                
    print("\n" + "=" * 80)
    print("✅ 테스트 완료")

if __name__ == "__main__":
    main()
