# FDS 실험 환경 개선 계획

## 1. 목표: 객관적 평가 지표 측정

목표 결과 표:
| 시스템 구성 | Precision | Recall | F1-Score | Latency |
|------------|-----------|--------|----------|---------|
| 기존 수동 거버넌스 | 0.75 | 0.60 | 0.67 | 5000ms |
| FDS 단일 토큰 | 0.88 | 0.82 | 0.85 | 350ms |
| FDS 2계층 토큰 | 0.94 | 0.91 | 0.93 | 120ms |

## 2. 현재 문제점 분석

### 2.1. Ground Truth 부재
- **문제**: 현재 공격인지 정상인지 레이블이 없어 TP/FP/TN/FN 계산 불가
- **해결**: 레이블이 포함된 벤치마크 데이터셋 생성

### 2.2. 측정 인프라 부재
- **문제**: 탐지 결과, 시간, 정확도 등을 측정하는 시스템 없음
- **해결**: MetricsCollector 모듈 구현

### 2.3. 비교 대상(Baseline) 미구현
- **문제**: "기존 수동 거버넌스" 시뮬레이션이 없음
- **해결**: 지연된 의사결정을 시뮬레이션하는 ManualGovernance 클래스 구현

### 2.4. 자동화 부재
- **문제**: 대규모 실험을 수동으로만 실행 가능
- **해결**: BatchExperimentRunner 구현

---

## 3. 개선 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Benchmark Experiment Framework                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────┐     ┌──────────────────┐                     │
│  │  BenchmarkData   │     │  MetricsCollector│                      │
│  │  Generator       │     │                  │                      │
│  │                  │     │  - TP, FP, TN, FN│                      │
│  │  - 공격 시나리오 │     │  - Precision     │                      │
│  │  - 정상 트래픽   │     │  - Recall        │                      │
│  │  - Ground Truth  │     │  - F1-Score      │                      │
│  │    Labels        │     │  - Latency (ms)  │                      │
│  └────────┬─────────┘     └────────▲─────────┘                      │
│           │                        │                                 │
│           ▼                        │                                 │
│  ┌────────────────────────────────┴──────────────────────────────┐  │
│  │                    Detection Systems                          │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │  │
│  │  │   Baseline   │  │  FDS Single  │  │  FDS 2-Layer     │   │  │
│  │  │   (Manual)   │  │    Token     │  │    Token         │   │  │
│  │  │              │  │              │  │                  │   │  │
│  │  │ Delay:       │  │ Method A,B,C │  │ Micro: 느슨한    │   │  │
│  │  │ 150-400 블록 │  │ 임계값 탐지  │  │ Macro: 엄격한    │   │  │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                  BatchExperimentRunner                        │  │
│  │  - N회 반복 실험                                               │  │
│  │  - 결과 집계 및 통계 분석                                       │  │
│  │  - CSV/JSON 내보내기                                           │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. 구현 상세 계획

### 4.1. 벤치마크 데이터셋 생성기 (BenchmarkDataGenerator)

```python
class BenchmarkDataGenerator:
    """
    레이블이 포함된 테스트 데이터 생성
    - 공격 유형: infinite_mint, reserve_drain, flash_loan_depeg
    - 정상 유형: normal_transfer, normal_large_transfer, liquidity_add
    """
    
    def generate_attack_scenarios(self, attack_type: str, count: int) -> List[Scenario]:
        """공격 시나리오 생성 (label=ATTACK)"""
        pass
    
    def generate_normal_scenarios(self, count: int) -> List[Scenario]:
        """정상 거래 시나리오 생성 (label=NORMAL)"""
        pass
    
    def get_mixed_dataset(self, attack_ratio: float = 0.3) -> List[Scenario]:
        """공격과 정상이 섞인 데이터셋 반환"""
        pass
```

### 4.2. 메트릭 수집기 (MetricsCollector)

```python
class MetricsCollector:
    """
    탐지 결과를 수집하고 평가 지표 계산
    """
    
    def __init__(self):
        self.results = []  # (prediction, ground_truth, latency_ms)
    
    def record(self, predicted: str, actual: str, latency_ms: float):
        """
        predicted: 'ATTACK' or 'NORMAL' (탐지 시스템의 판단)
        actual: 'ATTACK' or 'NORMAL' (Ground Truth)
        latency_ms: 탐지에 걸린 시간 (ms)
        """
        self.results.append({
            'predicted': predicted,
            'actual': actual,
            'latency_ms': latency_ms
        })
    
    def calculate_precision(self) -> float:
        """Precision = TP / (TP + FP)"""
        pass
    
    def calculate_recall(self) -> float:
        """Recall = TP / (TP + FN)"""
        pass
    
    def calculate_f1(self) -> float:
        """F1 = 2 * (Precision * Recall) / (Precision + Recall)"""
        pass
    
    def calculate_avg_latency(self) -> float:
        """평균 탐지 지연시간 (ms)"""
        pass
    
    def get_summary(self) -> dict:
        """모든 메트릭 요약"""
        pass
```

### 4.3. 탐지 시스템 인터페이스 (DetectionSystem)

```python
class DetectionSystem(ABC):
    """모든 탐지 시스템의 추상 베이스 클래스"""
    
    @abstractmethod
    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        """
        Returns: (prediction, latency_ms)
        - prediction: 'ATTACK' or 'NORMAL'
        - latency_ms: 탐지 소요 시간
        """
        pass


class ManualGovernanceSystem(DetectionSystem):
    """기존 수동 거버넌스 시뮬레이션 (Baseline)"""
    
    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        # 5000ms 지연 + 불완전한 탐지 (오탐/미탐 포함)
        pass


class FDSSingleLayerSystem(DetectionSystem):
    """FDS 단일 토큰 시스템"""
    
    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        # ~350ms 지연 + 높은 정확도
        pass


class FDSTwoLayerSystem(DetectionSystem):
    """FDS 2계층 토큰 시스템"""
    
    def detect(self, scenario: Scenario) -> Tuple[str, float]:
        # ~120ms 지연 + 최고 정확도
        pass
```

### 4.4. 일괄 실험 실행기 (BatchExperimentRunner)

```python
class BatchExperimentRunner:
    """대규모 자동화 실험 실행"""
    
    def __init__(self, systems: List[DetectionSystem], dataset: List[Scenario]):
        self.systems = systems
        self.dataset = dataset
    
    def run_experiments(self, iterations: int = 10) -> Dict[str, MetricsCollector]:
        """
        각 시스템에 대해 N회 반복 실험 수행
        Returns: {system_name: MetricsCollector}
        """
        pass
    
    def export_results(self, path: str):
        """결과를 CSV로 내보내기"""
        pass
```

---

## 5. 데이터셋 명세

### 5.1. 공격 시나리오 (Label: ATTACK)

| ID | Type | Description | Parameters |
|----|------|-------------|------------|
| A1 | infinite_mint | 대량 민트 공격 | amount: 50000 ~ 500000 |
| A2 | reserve_drain | 금고 탈취 | amount: 1000 ~ 5000 ETH |
| A3 | flash_loan_depeg | 가격 조작 | loan: 10M ~ 100M USDC |
| A4 | threshold_evasion | 임계값 회피 | amount: threshold * 0.95 |
| A5 | sybil_attack | 분산 공격 | wallets: 10, each: 5000 |
| A6 | gradual_escalation | 점진적 증가 | start: 1000, multiplier: 2 |

### 5.2. 정상 시나리오 (Label: NORMAL)

| ID | Type | Description | Parameters |
|----|------|-------------|------------|
| N1 | normal_transfer | 일반 송금 | amount: 100 ~ 10000 |
| N2 | large_transfer | 대량 정상 송금 | amount: 8000 (임계값 근접) |
| N3 | liquidity_add | 유동성 공급 | amount: 50000 (정상적 대량) |
| N4 | batch_payment | 급여/배당 지급 | count: 100, each: 500 |

### 5.3. 데이터셋 구성

```
총 1000개 시나리오:
- 공격: 300개 (30%)
  - A1: 50개, A2: 50개, A3: 50개, A4: 50개, A5: 50개, A6: 50개
- 정상: 700개 (70%)
  - N1: 400개, N2: 150개, N3: 100개, N4: 50개
```

---

## 6. Latency 측정 방법

### 6.1. 수동 거버넌스 Latency 시뮬레이션
```
시간 구성:
- 이상 징후 발견 ~ 담당자 인지: 1000-2000ms (알림 지연)
- 담당자 검토 ~ 의사결정: 2000-3000ms (최소 판단 시간)
- 의사결정 ~ 실행: 500-1000ms (실행 지연)
총: 3500-6000ms (평균 5000ms)
```

### 6.2. FDS 단일 토큰 Latency
```
시간 구성:
- 블록 수신 ~ 분석 완료: 50-100ms
- 탐지 알고리즘 실행: 100-150ms
- 서킷 브레이커 TX 전송: 100-200ms
총: 250-450ms (평균 350ms)
```

### 6.3. FDS 2계층 토큰 Latency
```
시간 구성:
- 블록 수신 ~ Micro 분석: 20-50ms (간소화)
- Macro 전용 검증: 50-80ms (사전 서명 검증)
- 우선순위 서킷 브레이커: 30-50ms (높은 Gas 우선)
총: 100-180ms (평균 120ms)
```

---

## 7. 구현 체크리스트

### Phase 1: 핵심 인프라 (우선순위 높음)
- [ ] BenchmarkDataGenerator 클래스 구현
- [ ] MetricsCollector 클래스 구현
- [ ] Scenario 데이터 클래스 정의

### Phase 2: 탐지 시스템 구현
- [ ] DetectionSystem 추상 베이스 클래스
- [ ] ManualGovernanceSystem 구현 (Baseline)
- [ ] FDSSingleLayerSystem 구현
- [ ] FDSTwoLayerSystem 구현

### Phase 3: 실험 실행기
- [ ] BatchExperimentRunner 구현
- [ ] 결과 집계 및 통계 분석
- [ ] CSV/JSON 내보내기

### Phase 4: UI 통합
- [ ] Streamlit 페이지: 5_Benchmark_Experiment.py
- [ ] 실험 설정 UI
- [ ] 실시간 진행률 표시
- [ ] 결과 시각화 (표, 차트)

---

## 8. 파일 구조

```
watchtower/
├── lib/
│   ├── utils.py (기존)
│   ├── benchmark/
│   │   ├── __init__.py
│   │   ├── data_generator.py      # BenchmarkDataGenerator
│   │   ├── metrics_collector.py   # MetricsCollector
│   │   ├── scenario.py            # Scenario 데이터 클래스
│   │   ├── detection_systems/
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # DetectionSystem ABC
│   │   │   ├── manual_governance.py
│   │   │   ├── fds_single_layer.py
│   │   │   └── fds_two_layer.py
│   │   └── experiment_runner.py   # BatchExperimentRunner
│   └── ...
├── pages/
│   ├── 1_Block_Explorer.py (기존)
│   ├── 2_Experiment_Runner.py (기존)
│   ├── 3_Research_Metrics.py (기존)
│   ├── 4_Two_Layer_Experiment.py (기존)
│   └── 5_Benchmark_Experiment.py  # 새 페이지
└── ...
```

---

## 9. 예상 결과

개선된 실험 환경에서 다음과 같은 결과를 측정할 수 있습니다:

| 시스템 구성 | Precision | Recall | F1-Score | Avg Latency |
|------------|-----------|--------|----------|-------------|
| 기존 수동 거버넌스 | 0.72-0.78 | 0.58-0.62 | 0.65-0.69 | 4500-5500ms |
| FDS 단일 토큰 | 0.86-0.90 | 0.80-0.84 | 0.83-0.87 | 300-400ms |
| FDS 2계층 토큰 | 0.92-0.96 | 0.89-0.93 | 0.90-0.95 | 100-150ms |

**핵심 개선점:**
1. **Ground Truth 기반 정확한 측정**: TP/FP/TN/FN 완벽 분류
2. **자동화된 대규모 실험**: 1000개 시나리오 × 3개 시스템 × 10회 반복
3. **재현 가능한 결과**: 동일 데이터셋으로 언제든 재실험 가능
4. **논문 품질 데이터**: CSV 내보내기로 직접 논문에 사용 가능
