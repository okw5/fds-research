# Benchmark_Experiment 페이지 — 현재 코드 검토 및 시뮬레이션 개선 계획

## 1. 현재 코드와 요건 비교 (Gap Analysis)

### ✅ 잘 맞는 부분

| 항목 | 요건 | 현재 코드 상태 |
|---|---|---|
| 비교군 구성 | 수동거버넌스 / 단일계층 / 2계층 | [ManualGovernanceSystem](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/manual_governance.py#28-181), [FDSSingleLayerSystem](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/fds_single_layer.py#29-243), [FDSTwoLayerSystem](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/fds_two_layer.py#33-353) 3개 구현 완료 |
| 공격 유형 4종 | 무한발행 / 준비금탈취 / 플래시론 / 시빌+임계회피 | `INFINITE_MINT`, `RESERVE_DRAIN`, `FLASH_LOAN_DEPEG`, `SYBIL_ATTACK`, `THRESHOLD_EVASION` 구현됨 |
| 공격 규모 범위 | 무한발행 100~500K, 준비금 10~5K ETH, 플래시론 10M~100M USDC | [data_generator.py](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/data_generator.py)에서 [(100, 500000)](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/fds_single_layer.py#50-73), [(10, 5000)](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/fds_single_layer.py#50-73), [(100_000, 100_000_000)](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/fds_single_layer.py#50-73) 범위 설정됨 ✅ |
| 탐지율/오탐율 | 3시스템 비교 측정 | `MetricsCollector`에서 confusion matrix 기반 계산 구현 ✅ |
| 대응시간 비교 | 수동(30~80분) >> 단일(350ms) ≒ 2계층(350ms) | 수동: 3500~6000ms(시뮬레이션 단위, Downtime은 30~120분으로 별도 표현), 자동: 250~450ms / 80~150ms ✅ |
| 가스 소비량 분석 | sig_verify / pause / blacklist / overhead | `gas_details` 딕셔너리로 3항목 측정 ✅ |
| 자산 보존율 | 3시스템 비교 | [financial_loss](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/base.py#120-168) 기반 `prevention_rate` 계산 ✅ |
| 서비스 가동률 | 2계층 압도적 우수 | `micro_available` 플래그와 `availability` 집계 ✅ |
| 실험 데이터 크기 | 정상 1,000건 + 공격별 200건 | 슬라이더로 설정 가능, 기본값 500건. **요건이 명시한 1,000+200×4 고정 구성이 기본값이 아님** ⚠️ |
| 반복 횟수 | 각 시나리오 50회 이상 | 슬라이더 1~10회 (기본 1회). **요건의 50회 최소 기준 미달** ⚠️ |

---

### ❌ / ⚠️ 요건과 다르거나 개선이 필요한 부분

#### 문제 1 — Downtime 시뮬레이션이 공격 규모·대응 속도를 반영하지 못함 (핵심 문제)

현재 `service_downtime_sec`는 **공격 금액과 무관하게 고정 랜덤 범위**로 산출됩니다:

```python
# fds_single_layer.py 현재 코드
service_downtime_sec = random.uniform(600, 1800)   # 공격 금액 무관
service_downtime_sec = random.uniform(1800, 7200)  # 500만 이상만 다름
```

요건은 다음을 요구합니다:
- **발행코인에 큰 문제가 생길 공격(무한발행·준비금탈취)은 즉시 시스템을 내려야 함**
- **내리지 못하면 피해금액이 기하급수적으로 증가** — 현재는 단순 선형 비율 손실 모델
- **빠르게 대응할수록 피해금액이 적어야 함** — 현재는 대략적이나 로그/지수 스케일이 아님
- **2계층은 Macro 공격 후 Micro 결제망으로 피해가 누적** — 현재 2계층은 Micro 공격 시 즉시 지갑 동결만 하고, **Macro 공격 탐지 후 소액망을 통한 피해 누적이 없음**

#### 문제 2 — 단일계층 vs 2계층의 Downtime 차이가 드러나지 않음

현재 4번 차트(Downtime 분석)에서:
- 단일계층: `pause_all` → 전체 중단이지만 자동탐지로 빠름 (5~30분)
- 2계층: 일반 Macro → Micro 유지, Macro 중단 2~10분 (더 좋아 보임)

그런데 **Catastrophic 공격(500만 토큰 이상)인 경우 2계층도 `pause_all`** 을 하는데, 현재 데이터 생성기는 [(100, 500000)](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/fds_single_layer.py#50-73) 범위라서 500만에 도달하기 어렵습니다. 따라서 실제로 2계층의 `pause_all` 케이스가 거의 생성되지 않아 **Downtime 비교 차트에서 두 시스템의 차이가 미미하게** 나타납니다.

#### 문제 3 — 대응시간 기준 불일치

요건: 수동 거버넌스 응답 시간 **30~80분**
현재 코드: `response_delay_min_ms: 3500, response_delay_max_ms: 6000` (3.5~6초로 시뮬레이션, 단위가 ms임)

페이지 하단 목표표에 30~120분이라고 별도 표시는 하고 있지만, 실제 시뮬레이션의 **latency_ms** 값은 3.5~6초입니다. 이 숫자는 "트랜잭션 레벨의 지연"이고, 실제 서비스 중단 시간(1800~7200초)은 별도로 표현됩니다. 논문 독자에게 혼란을 줄 수 있으므로 명확하게 구분해야 합니다.

---

## 2. 개선 계획 — 피해금액 지수증가 + 단일·2계층 상세 비교

### 2-A. 피해금액 모델 개선: 지수적 증가 모델

**현재:** 탐지 지연 ms → 고정 비율(5%, 10%, 30%, 50%) 손실

**변경:** `attack_velocity` (공격별 초당 피해 속도) × 대응 전까지 경과 시간으로 **지수 누적 피해** 계산

```python
# 개선 예시 (base.py _estimate_financial_loss 대체)
def _estimate_financial_loss_v2(self, scenario, latency_ms, detected):
    """
    공격 유형마다 '초당 피해율'을 정의하고, 
    대응까지 경과 초에 지수적으로 피해가 누적되는 모델.
    
    피해금액 = attack_value * (e^(velocity * t) - 1)
    단, t = 대응 지연(초), velocity = 공격유형별 확산 속도
    """
    VELOCITIES = {
        'infinite_mint':   0.15,   # 매우 빠름 - 발행 즉시 토큰 가치 희석
        'reserve_drain':   0.12,   # 빠름 - 금고 고갈 시 비례 손실
        'flash_loan_depeg': 0.08,  # 플래시론은 블록 단위로 진행
        'sybil_attack':    0.04,   # 분산 공격 - 상대적으로 느림
        'threshold_evasion': 0.03, # 소액 반복 - 느림
    }
    ...
```

**핵심:** 수동거버넌스(~300초 지연) → 피해금액 수십 배, 단일계층(~0.35초 지연) → 작은 피해, 2계층(~0.15초 지연) → 훨씬 작은 피해

---

### 2-B. 2계층 특화 시뮬레이션: Macro 공격 후 Micro 채널 피해 누적

**목적:** Macro 공격(무한발행) 탐지 후 Macro 계층은 pause되지만, 이미 발행된 위조 토큰이 **소액결제망(Micro)으로 흘러들어 피해가 누적**되는 상황을 시뮬레이션

```
기존 2계층 시뮬레이션:
  Macro 공격 감지 → pause_macro OR pause_all → 끝

개선 2계층 시뮬레이션:
  Step 1: Macro 탐지 지연(latency_ms) 동안 대량 민트 발생
      → 위조 토큰 X개 생성
  Step 2: Macro pause_macro 발동 (Macro 계층 차단)
      → 그러나 이미 생성된 X개 토큰은 시스템에 존재
  Step 3: 위조 토큰이 Micro 계층(소액결제망)으로 유입
      → Micro 계층에서 N건의 소액 결제 처리 (탐지 전까지)
      → micro_secondary_loss = leaked_tokens * micro_tx_count * price
  Step 4: Micro 계층 이상 패턴 탐지 → 개별 지갑 blacklist
      → 추가 피해 차단
  
  Total loss(2계층) = 탐지 전 직접 손실 + micro_secondary_loss
  Total loss(단일)  = 탐지 전 직접 손실 (+ 더 높은 downtime으로 간접 손실)
```

이 설계로 **단일계층과 2계층의 차이를 디테일하게** 볼 수 있습니다:
- 단일계층: 빠른 전체 정지 → Micro도 차단되지만 downtime 비용 발생
- 2계층: Macro 정지 + Micro 유지 → Micro 경유 누적 피해는 있지만 서비스 연속성 유지, 총 downtime은 훨씬 낮음

---

### 2-C. 코드 변경 파일 목록

#### [MODIFY] [base.py](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/base.py)
- [_estimate_financial_loss()](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/base.py#120-168) → `_estimate_financial_loss_v2()` 로 지수 증가 모델 교체
- [DetectionResponse](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/base.py#22-44)에 `micro_secondary_loss: float = 0.0`, `leaked_tokens: float = 0.0` 필드 추가

#### [MODIFY] [fds_two_layer.py](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/fds_two_layer.py)
- [detect_extended()](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/base.py#79-96) 에 2단계 피해 계산 추가:
  - Step 1: Macro 탐지 가 완료되기 전 발행된 위조 토큰 수 계산
  - Step 2: Micro 채널 유입 후 추가 누적 피해 (`micro_secondary_loss`) 산출

#### [MODIFY] [fds_single_layer.py](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/fds_single_layer.py)
- [detect_extended()](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/base.py#79-96) 에 같은 지수 손실 모델 적용
- Downtime 기간 중 서비스 불능에 따른 **간접 손실(service outage cost)** 추가: `downtime_opportunity_cost = service_downtime_sec * daily_tx_volume / 86400`

#### [MODIFY] [manual_governance.py](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/manual_governance.py)
- 같은 지수 손실 모델 적용. 수동의 긴 탐지 지연이 지수 모델에서 훨씬 큰 피해로 표현됨

#### [MODIFY] [data_generator.py](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/data_generator.py)
- [generate_infinite_mint_attack()](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/data_generator.py#55-73): `amount_range` 기본값을 [(100_000, 500_000)](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/lib/benchmark/detection_systems/fds_single_layer.py#50-73) 로 올려 Catastrophic 범위(5M 토큰)에 쉽게 도달하게 설정
- Catastrophic 공격을 위한 `generate_catastrophic_mint_attack()` 신규 추가

#### [MODIFY] [5_Benchmark_Experiment.py](file:///c:/Users/woori/Documents/%EB%8C%80%ED%95%99%EC%9B%90/fds-research/watchtower/pages/5_Benchmark_Experiment.py)
- **④ Downtime 분석 차트** 개선:
  - Macro/Micro 공격 × Catastrophic 여부 3개 카테고리로 구분
  - `micro_secondary_loss` 별도 스택바로 표현
  - **피해금액 vs 대응시간 산점도** 차트 추가 (핵심 그래프: 빠를수록 피해 적은 관계 시각화)
- **⑥ 공격 진행 타임라인 시뮬레이션** 신규 섹션 추가:
  - 무한발행 1건을 선택하여 3시스템의 시간축 피해 누적을 라인차트로 시각화

---

## 3. 구현 검증 계획

### 자동 검증 (unit test)
```bash
# 기존 test_benchmark.py 실행
cd c:\Users\woori\Documents\대학원\fds-research\watchtower
python -m pytest test_benchmark.py -v
```

### 수동 검증 (Streamlit UI)
```bash
cd c:\Users\woori\Documents\대학원\fds-research\watchtower
streamlit run Home.py
```
1. 사이드바에서 데이터셋 크기 **1,000**, 공격 비율 **0.3**, 반복 **3회** 설정
2. **데이터셋 생성** → Catastrophic 공격 시나리오가 포함되는지 상세보기에서 확인
3. **벤치마크 실험 시작** 클릭
4. **④ Downtime 분석**: 단일계층의 Macro 공격 Downtime과 2계층의 Macro Downtime + Micro 2차 피해가 **별개 컬럼**으로 나타나는지 확인
5. **피해금액 vs 대응시간 산점도**: 우하향 패턴(빠를수록 피해 감소)이 명확히 나타나는지 확인
6. **⑥ 타임라인 시뮬레이션**: 무한발행 공격에 대해 3시스템의 피해 누적 라인이 구분 가능한지 확인

