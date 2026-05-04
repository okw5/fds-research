"""
5_Benchmark_Experiment.py
객관적 평가 지표(Precision, Recall, F1-Score, Latency) + 확장 지표(피해금액, 가용성) 측정
"""

import streamlit as st
import pandas as pd
import altair as alt
import time
import sys
import os

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from lib.benchmark.scenario import Scenario, ScenarioType
from lib.benchmark.data_generator import BenchmarkDataGenerator
from lib.benchmark.metrics_collector import MetricsCollector
from lib.benchmark.experiment_runner import BatchExperimentRunner, ExperimentConfig
from lib.benchmark.detection_systems import (
    ManualGovernanceSystem,
    FDSSingleLayerSystem,
    FDSTwoLayerSystem,
    FDSEngine1System,
    FDSEngine2System,
    FDSEngine3System
)

# Page Config
st.set_page_config(
    page_title="Benchmark Experiment - FDS Research", 
    page_icon="📊", 
    layout="wide"
)

st.title("📊 객관적 평가 벤치마크 실험")
st.markdown("""
이 페이지에서는 기존 탐지 지표뿐만 아니라 **비즈니스 관점의 핵심 지표(피해금액, 서비스 중단 시간)**를 포함하여
세 가지 시스템을 정량적으로 비교합니다.

#### 비교 대상
1. **기존 수동 거버넌스**: 인간 모니터링, 공격 시 전체 네트워크 중단 (Baseline)
2. **FDS 단일 토큰**: 자동 탐지, 공격 시 전체 토큰 일시정지
3. **FDS 2계층 토큰**: Micro/Macro 분리, **Macro만 정지하고 소액결제는 무중단 유지** (제안 모델)
""")

# ============================================================================
# 사이드바: 실험 설정
# ============================================================================
st.sidebar.header("🔧 실험 설정")

dataset_size = st.sidebar.slider(
    "데이터셋 크기",
    min_value=100,
    max_value=2000,
    value=500,
    step=100,
    help="테스트할 총 시나리오 수"
)

attack_ratio = st.sidebar.slider(
    "공격 비율",
    min_value=0.1,
    max_value=0.5,
    value=0.3,
    step=0.05,
    help="데이터셋 중 공격 시나리오의 비율"
)

iterations = st.sidebar.slider(
    "반복 횟수",
    min_value=1,
    max_value=60,
    value=1,
    step=1,
    help="통계적 유의성을 위한 반복 실험 횟수"
)

include_network_mix = st.sidebar.checkbox(
    "네트워크 혼잡 시나리오 포함",
    value=True,
    help="정상/혼잡/극심한 혼잡 네트워크 조건 포함"
)

st.sidebar.divider()
st.sidebar.subheader("📦 데이터셋 소스")
dataset_source = st.sidebar.radio(
    "데이터셋 유형 선택",
    options=["시뮬레이션", "실제 컨트랙트", "하이브리드 (혼합)"],
    index=2,
    help=(
        "• 시뮬레이션: 무작위 파라미터 기반 가상 시나리오\n"
        "• 실제 컨트랙트: sample_data의 91개 실제 .sol 파일 정적 분석\n"
        "• 하이브리드: 시뮬레이션 + 실제 컨트랙트 결합 (가장 객관적)"
    ),
)
if dataset_source == "실제 컨트랙트":
    st.sidebar.info("📌 50개 악성(positive) + 41개 정상(negative) = 91개 실제 Ethereum 스마트 컨트랙트")
elif dataset_source == "하이브리드 (혼합)":
    st.sidebar.info("📌 시뮬레이션 시나리오에 91개 실제 컨트랙트를 추가하여 객관성을 극대화합니다.")

random_seed = st.sidebar.number_input(
    "랜덤 시드",
    min_value=0,
    max_value=9999,
    value=42,
    help="재현 가능한 실험을 위한 시드값"
)

# Session State 초기화
if 'benchmark_results' not in st.session_state:
    st.session_state.benchmark_results = None
if 'benchmark_dataset' not in st.session_state:
    st.session_state.benchmark_dataset = None

# ============================================================================
# 데이터셋 미리보기
# ============================================================================
st.divider()
st.subheader("📂 벤치마크 데이터셋")

col_gen, col_preview = st.columns([1, 2])

with col_gen:
    if st.button("🔄 데이터셋 생성", use_container_width=True):
        with st.spinner("데이터셋 생성 중..."):
            generator = BenchmarkDataGenerator(seed=random_seed)

            if dataset_source == "시뮬레이션":
                dataset = generator.get_mixed_dataset(
                    total_count=dataset_size,
                    attack_ratio=attack_ratio,
                    network_mix=include_network_mix
                )
            elif dataset_source == "실제 컨트랙트":
                dataset = generator.get_real_contract_dataset(shuffle=True)
            else:  # 하이브리드
                dataset = generator.get_hybrid_dataset(
                    total_simulated=dataset_size,
                    attack_ratio=attack_ratio,
                    network_mix=include_network_mix
                )

            st.session_state.benchmark_dataset = dataset

            # 실제 컨트랙트 통계 표시
            real_count = sum(1 for s in dataset if s.parameters.get('is_real_contract', False))
            if real_count > 0:
                st.success(f"✅ {len(dataset)}개 시나리오 생성 완료! (실제 컨트랙트: {real_count}개 포함)")
            else:
                st.success(f"✅ {len(dataset)}개 시나리오 생성 완료!")

with col_preview:
    if st.session_state.benchmark_dataset:
        dataset = st.session_state.benchmark_dataset
        
        # 데이터셋 통계
        attack_count = sum(1 for s in dataset if s.is_attack())
        normal_count = len(dataset) - attack_count
        
        c1, c2, c3 = st.columns(3)
        c1.metric("총 시나리오", len(dataset))
        c2.metric("공격 시나리오", attack_count, f"{attack_count/len(dataset)*100:.1f}%")
        c3.metric("정상 시나리오", normal_count, f"{normal_count/len(dataset)*100:.1f}%")

# 데이터셋 상세 보기
if st.session_state.benchmark_dataset:
    with st.expander("📋 데이터셋 상세 보기"):
        dataset_df = pd.DataFrame([
            {
                'ID': s.id,
                'Label': s.label.value,
                'Type': s.scenario_type.value,
                'Name': s.name,
                'Network': s.network_condition,
                'Amount': s.parameters.get('amount', s.parameters.get('total_amount', 'N/A'))
            }
            for s in st.session_state.benchmark_dataset[:50]  # 처음 50개만
        ])
        st.dataframe(dataset_df, use_container_width=True)
        st.caption(f"처음 50개만 표시됨 (총 {len(st.session_state.benchmark_dataset)}개)")

# ============================================================================
# 실험 실행
# ============================================================================
st.divider()
st.subheader("🚀 실험 실행")

if not st.session_state.benchmark_dataset:
    st.warning("먼저 데이터셋을 생성해주세요.")
else:
    if st.button("▶️ 벤치마크 실험 시작", type="primary", use_container_width=True):
        # 시스템 초기화
        sys_e1 = FDSEngine1System()
        sys_e1.name = "SequenceAnomaly + 1계층 모델"
        sys_e2 = FDSEngine2System()
        sys_e2.name = "FlashLoanRule + 1계층 모델"
        sys_e3 = FDSEngine3System()
        sys_e3.name = "HoustonLite + 1계층 모델"
        
        sys_mg = ManualGovernanceSystem()
        sys_mg.name = "앙상블모델 + 수동거버넌스"
        
        sys_sl = FDSSingleLayerSystem()
        sys_sl.name = "앙상블모델 + 1계층 모델"
        
        sys_tl = FDSTwoLayerSystem()
        sys_tl.name = "앙상블모델 + 2계층모델"
        
        systems = [sys_e1, sys_e2, sys_e3, sys_mg, sys_sl, sys_tl]
        
        config = ExperimentConfig(
            iterations=iterations,
            shuffle_per_iteration=True,
            random_seed=random_seed,
            use_extended=True  # 확장 지표 사용
        )
        
        runner = BatchExperimentRunner(
            systems=systems,
            dataset=st.session_state.benchmark_dataset,
            config=config
        )
        
        # 진행률 표시
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def progress_callback(progress, message):
            progress_bar.progress(progress)
            status_text.text(f"진행 중: {message} ({progress*100:.1f}%)")
        
        # 실험 실행
        start_time = time.time()
        results = runner.run_all(progress_callback=progress_callback)
        elapsed = time.time() - start_time
        
        progress_bar.progress(1.0)
        status_text.text(f"✅ 완료! (소요 시간: {elapsed:.2f}초)")
        
        # 결과 저장
        st.session_state.benchmark_results = {
            'collectors': results,
            'runner': runner,
            'elapsed': elapsed
        }
        
        st.success(f"🎉 벤치마크 실험 완료! {runner.total_experiments}개 실험 수행")
        time.sleep(1)
        st.rerun()

# ============================================================================
# 결과 표시 - 논문 실증 결과 5개 시각화
# ============================================================================
if st.session_state.benchmark_results:
    st.divider()
    st.subheader("📈 논문 실증 결과 분석")

    results = st.session_state.benchmark_results
    collectors = results['collectors']
    runner = results['runner']

    # =========================================================================
    # ① 시스템 성능 지표 비교 요약표 (8개 지표)
    # =========================================================================
    st.markdown("### 📋 ① 시스템 성능 지표 비교 요약표")
    
    st.info(
        "💡 **재무 피해 산출 기준 (필독)**\n"
        f"• 아래 표기된 총액(USD)은 단일 보안 사고의 규모가 아니며, 3개 시스템에 대한 전체 **{runner.total_experiments:,}회 시나리오 반복 실험의 누적 합산액**입니다.\n"
        "• 가치 환산 제한 사항: 시뮬레이션된 토큰 수량은 **1 Token = $1 USD** 로 고정하여 산출되었으며, 유동성 고갈 및 슬리피지로 인한 2차적 자산 붕괴는 배제된 보수적인 명목 수치입니다."
    )
    
    st.caption("탐지율·오탐율·응답 시간·자산 보존율·서비스 가동률 등 8개 핵심 지표로 3개 시스템을 비교합니다.")

    summary_rows = []
    for name, collector in collectors.items():
        summary = collector.get_summary()
        cm = summary['confusion_matrix']
        fpr = cm['FP'] / (cm['FP'] + cm['TN']) if (cm['FP'] + cm['TN']) > 0 else 0
        gas = summary.get('gas_consumption', {})
        avg_gas = sum(gas.get(f'avg_{k}', 0) for k in ['signature_verification', 'pause', 'blacklist_addition'])
        tm = summary.get('two_layer_metrics', {})

        # Micro 2차 피해율: total_potential(공격 대상 자산 합) 분모 기준 — 자산보존율과 동일 분모
        _attack_rs = [r for r in collector.results if r.actual == 'ATTACK']
        _total_potential = sum(
            float(r.metadata.get('amount',
                  r.metadata.get('total_amount',
                  r.metadata.get('loan_amount', r.financial_loss))))
            for r in _attack_rs
        )
        _micro_loss = tm.get('total_micro_secondary_loss_usd', 0.0)
        _micro_pct = (_micro_loss / _total_potential * 100) if _total_potential > 0 else 0.0

        summary_rows.append({
            '시스템 구성': name,
            '탐지율 (Recall)': f"{summary['recall']*100:.1f}%",
            '오탐율 (FPR)': f"{fpr*100:.1f}%",
            'F1-Score': f"{summary['f1_score']:.3f}",
            '대응 시간 (avg)': f"{summary['latency']['avg_ms']:.0f} ms",
            '자산 보존율': f"{summary['financial_loss']['prevention_rate']*100:.1f}%",
            'Micro 2차 피해 (자산 대비)': f"{_micro_pct:.4f}%" if _micro_pct > 0 else "—",
            '평균 Downtime': f"{summary['service_downtime']['avg_per_detection_min']:.1f} 분",
            '평균 가스비 (Gas)': f"{avg_gas:,.0f}",
        })

    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    # ── 논문 인용용 계산식 세부 정보 ──────────────────────────────────────────
    with st.expander("📐 각 지표 계산식 세부 정보 (논문 인용용)", expanded=False):
        st.markdown("""
| 지표 | 계산식 | 비고 |
|---|---|---|
| **탐지율 (Recall)** | $\\text{Recall} = \\dfrac{TP}{TP + FN}$ | 실제 공격 중 탐지 성공 비율. FN 감소가 핵심 |
| **오탐율 (FPR)** | $\\text{FPR} = \\dfrac{FP}{FP + TN}$ | 정상 거래 중 공격으로 오탐된 비율. 낮을수록 서비스 연속성 보장 |
| **F1-Score** | $F_1 = \\dfrac{2 \\cdot P \\cdot R}{P + R}, \\quad P = \\dfrac{TP}{TP+FP}$ | Precision–Recall 조화 평균. 불균형 데이터셋에서 종합 탐지 성능 지표 |
| **대응 시간** | $\\bar{t}_{response} = \\dfrac{1}{N}\\sum_{i=1}^{N} t_i$ (ms) | 탐지 요청부터 회로 차단 결정까지 평균 소요 시간 |
| **자산 보존율** | $r_{pres} = 1 - \\dfrac{\\sum L_i}{\\sum V_i}$ | $L_i$: 실제 발생한 피해, $V_i$: 공격 시나리오의 잠재 피해금액(amount). 지수 손실 모델 $L_i = V_i \\cdot (1 - e^{-v \\cdot t_{latency}})$ 적용 |
| **Micro 2차 피해율** | $r_{micro} = \\dfrac{\\sum m_i}{\\sum V_i} \\times 100\\%$ | $m_i$: Macro pause 후 Micro 채널로 유입된 위조 토큰 피해. $m_i = V_i \\cdot \\rho_{leak} \\cdot \\rho_{inflow} \\cdot \\rho_{detect}$ (2계층 전용, 분모는 자산보존율과 동일) |
| **평균 Downtime** | $\\bar{d} = \\dfrac{\\sum d_k}{K}$ (분) | $K$: ATTACK으로 판정된 건수. 서킷 브레이커 발동부터 서비스 복구까지 평균 시간 |
| **평균 가스비** | $\\bar{g} = g_{sig} + g_{pause} + g_{blacklist}$ (Gas) | 탐지 1건당 서명 검증 + Pause + 블랙리스트 추가 3단계 가스 합산 평균 |

> **공통 실험 조건**: 1 Token = 1 USD 고정 환산. 네트워크 혼잡도(Normal / Congested / Severe) Log-Normal 분포 적용. 지수 손실 확산 속도 $v$는 공격 유형별 상이(무한발행 0.18 / 준비금 탈취 0.14 / 플래시론 0.09 / 시빌 0.05).
        """)

    # =========================================================================
    # ② 공격 시나리오별 자산 보존율 비교 (그룹 막대)
    # =========================================================================
    st.divider()
    st.markdown("### 🛡️ ② 공격 시나리오별 자산 보존율 비교")
    st.caption("4개 공격 시나리오에서 3개 시스템의 자산 보존율을 그룹 막대로 비교합니다.")

    target_scenario_map = {
        'infinite_mint': '무한 발행',
        'reserve_drain': '준비금 탈취',
        'flash_loan_depeg': '플래시론',
        'sybil_attack': '시빌 공격',
    }
    preservation_data = []
    for name, collector in collectors.items():
        for s_type, s_label in target_scenario_map.items():
            matched = [r for r in collector.results if r.metadata.get('scenario_type') == s_type]
            if not matched:
                continue
            # 정밀한 자산 보존율: 실제 손실을 전체 잠재 공격 금액으로 나눈 방어율 적용
            total_potential = 0.0
            total_loss = 0.0
            
            for r in matched:
                if r.actual == 'ATTACK':
                    potential = float(r.metadata.get('amount',
                                      r.metadata.get('total_amount',
                                      r.metadata.get('loan_amount', r.financial_loss))))
                    
                    if potential == 0 and r.financial_loss > 0:
                        potential = r.financial_loss if r.is_false_negative else r.financial_loss / 0.05
                    
                    total_potential += max(potential, r.financial_loss)
                    total_loss += r.financial_loss
                    
            rate = 1.0 - (total_loss / total_potential) if total_potential > 0 else 1.0
            preservation_data.append({'시스템': name, '시나리오': s_label, '자산 보존율': rate})

    if preservation_data:
        pres_df = pd.DataFrame(preservation_data)
        pres_chart = alt.Chart(pres_df).mark_bar().encode(
            x=alt.X('시나리오:N', title='공격 시나리오', axis=alt.Axis(labelAngle=0)),
            y=alt.Y('자산 보존율:Q', title='자산 보존율', axis=alt.Axis(format='%'), scale=alt.Scale(domain=[0, 1])),
            color=alt.Color('시스템:N', title='시스템'),
            xOffset='시스템:N',
            tooltip=['시스템', '시나리오', alt.Tooltip('자산 보존율', format='.1%')]
        ).properties(height=380, title='시나리오별 자산 보존율 (그룹 막대 그래프)')
        st.altair_chart(pres_chart, use_container_width=True)
    else:
        st.info("공격 시나리오 데이터가 충분하지 않습니다. 데이터셋을 더 크게 생성 후 재실험 해주세요.")

    # =========================================================================
    # ③ 응답 시간 분포 박스플롯 (네트워크 조건별)
    # =========================================================================
    st.divider()
    st.markdown("### ⚡ ③ 응답 시간 분포 박스플롯 (Network Condition)")
    st.caption("Normal / Congested / Severe 3가지 네트워크 조건에서 단일 계층 vs 2계층의 응답 시간 분포. 빨간 점선은 목표 350ms입니다.")

    latency_rows = []
    for name, collector in collectors.items():
        for r in collector.results:
            net_raw = r.metadata.get('network_condition', 'normal')
            net_label = {'normal': 'Normal', 'congested': 'Congested', 'severe': 'Severe'}.get(net_raw, net_raw.capitalize())
            latency_rows.append({'시스템': name, '네트워크': net_label, '응답시간(ms)': r.latency_ms})

    lat_df = pd.DataFrame(latency_rows)
    # 수동거버넌스를 제외하고 모두 비교
    box_df = lat_df[~lat_df['시스템'].str.contains('수동')]

    if not box_df.empty:
        # ★ 패싯(column)이 있으면 레이어(+)를 추가할 수 없으므로
        #    xOffset으로 두 시스템을 나란히 배치하고 레이어로 목표선 추가
        boxplot = alt.Chart(box_df).mark_boxplot(extent='min-max', size=25).encode(
            x=alt.X('네트워크:N', title='네트워크 상태',
                    sort=['Normal', 'Congested', 'Severe'],
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y('응답시간(ms):Q', title='응답 시간 (ms)'),
            color=alt.Color('시스템:N', title='시스템'),
            xOffset=alt.XOffset('시스템:N')   # 같은 x 안에서 시스템별로 옆에 배치
        ).properties(height=400)

        rule_350 = alt.Chart(pd.DataFrame({'y': [350]})).mark_rule(
            color='red', strokeDash=[6, 4], strokeWidth=2
        ).encode(
            y='y:Q',
            tooltip=alt.value('목표 350ms')
        )

        combined = (boxplot + rule_350).properties(
            title='네트워크 상태별 응답 시간 분포 (빨간 점선 = 목표 350ms)'
        )
        st.altair_chart(combined, use_container_width=True)
    else:
        st.info("박스플롯을 그리기 위한 충분한 데이터가 없습니다.")

    # =========================================================================
    # ④ 평균 서비스 중단 시간 비교 (로그 스케일)
    # =========================================================================
    st.divider()
    st.markdown("### ⏱️ ④ 평균 서비스 중단 시간 비교 (Downtime 분석)")
    st.caption(
        "공격 규모별(Catastrophic·Macro·Micro) 서비스 중단 시간 비교. "
        "Catastrophic 공격(무한발행 5M+ 토큰)은 즉시 대응하지 않으면 피해가 기하급수적으로 증가합니다. "
        "2계층은 Micro 2차 피해(주황)가 추가되는 대신 Downtime이 훨씬 짧습니다."
    )

    macro_scenario_types = {'infinite_mint', 'reserve_drain', 'flash_loan_depeg'}
    downtime_rows = []
    for name, collector in collectors.items():
        for r in collector.results:
            if r.service_downtime_sec <= 0:
                continue
            s_type = r.metadata.get('scenario_type', '')
            is_catastrophic = r.metadata.get('is_catastrophic', False) or (
                s_type in {'infinite_mint', 'reserve_drain'}
                and r.metadata.get('amount', 0) >= 5_000_000
            )
            if s_type in macro_scenario_types:
                category = 'Catastrophic 공격' if is_catastrophic else 'Macro 공격'
            else:
                category = 'Micro 공격'

            downtime_rows.append({
                '시스템': name,
                '공격 유형': category,
                '중단시간(초)': max(0.01, r.service_downtime_sec),
                'Micro 2차피해($)': r.micro_secondary_loss,
            })

    if downtime_rows:
        dt_df = pd.DataFrame(downtime_rows)

        # 패널 A: 평균 Downtime 막대 (로그 스케일)
        dt_avg = dt_df.groupby(['시스템', '공격 유형'])['중단시간(초)'].mean().reset_index()
        dt_chart = alt.Chart(dt_avg).mark_bar().encode(
            x=alt.X('공격 유형:N', title=None,
                    sort=['Catastrophic 공격', 'Macro 공격', 'Micro 공격'],
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y('중단시간(초):Q', title='평균 중단 시간 (초, Log Scale)',
                    scale=alt.Scale(type='log', zero=False)),
            color=alt.Color('시스템:N', title='시스템'),
            xOffset='시스템:N',
            tooltip=['시스템', '공격 유형', alt.Tooltip('중단시간(초)', format='.1f')]
        ).properties(height=350, title='공격 규모별 서비스 중단 시간 (Catastrophic → 즉각 대응 필요)')
        st.altair_chart(dt_chart, use_container_width=True)

        # 패널 B: 2계층 Micro 2차 피해
        micro_df = dt_df[dt_df['Micro 2차피해($)'] > 0]
        if not micro_df.empty:
            micro_avg = micro_df.groupby(['시스템', '공격 유형'])['Micro 2차피해($)'].mean().reset_index()
            micro_chart = alt.Chart(micro_avg).mark_bar(opacity=0.85).encode(
                x=alt.X('공격 유형:N', axis=alt.Axis(labelAngle=0)),
                y=alt.Y('Micro 2차피해($):Q', title='Micro 2차 피해 평균 (USD)'),
                color=alt.Color('시스템:N'),
                xOffset='시스템:N',
                tooltip=['시스템', '공격 유형', alt.Tooltip('Micro 2차피해($)', format='$,.2f')]
            ).properties(height=280, title='Macro 공격 후 Micro 채널 2차 피해 (2계층 전용)')
            st.altair_chart(micro_chart, use_container_width=True)

        st.markdown("""
        > **해석**:
        > - **Catastrophic** 공격 시 단일계층이 2계층보다 Downtime이 훨씬 깁니다.
        > - 2계층은 **Micro 2차 피해**가 존재하지만 Downtime을 최소화합니다.
        > - Micro 공격에서 2계층은 지갑 blacklist만 수행 → Downtime **0초** 달성.
        """)
    else:
        st.info("공격 탐지 데이터가 없습니다. 실험을 재실행 해주세요.")

    # =========================================================================
    # ⑤ 가스 소비량 분석 차트 (스택 막대)
    # =========================================================================
    st.divider()
    st.markdown("### ⛽ ⑤ 가스 소비량 분석 — Circuit Breaker 단계별")
    st.caption("서킷 브레이커 발동 시 서명 검증 / Pause / 블랙리스트 추가 각 단계별 가스 비용 비교. 경제적 실행 가능성을 검증합니다.")

    gas_step_labels = {
        'avg_signature_verification': '서명 검증 (Sig. Verify)',
        'avg_pause': 'Pause (State Change)',
        'avg_blacklist_addition': '블랙리스트 추가',
    }
    gas_rows = []
    for name, collector in collectors.items():
        gas = collector.get_summary().get('gas_consumption', {})
        for key, label in gas_step_labels.items():
            gas_rows.append({'시스템': name, '단계': label, '가스 비용 (Gas)': gas.get(key, 0)})

    gas_df = pd.DataFrame(gas_rows)
    gas_chart = alt.Chart(gas_df).mark_bar().encode(
        x=alt.X('시스템:N', title='시스템', axis=alt.Axis(labelAngle=0)),
        y=alt.Y('가스 비용 (Gas):Q', title='가스 비용 (Gas Units, 단계별 합계)'),
        color=alt.Color('단계:N', title='단계', scale=alt.Scale(scheme='set2')),
        tooltip=['시스템', '단계', '가스 비용 (Gas)']
    ).properties(height=380, title='Circuit Breaker 단계별 가스 소비량 비교')
    st.altair_chart(gas_chart, use_container_width=True)



    # =========================================================================
    # ⑦ 무한발행 공격 타임라인 시뮬레이션
    # =========================================================================
    st.divider()
    st.markdown("### 📈 ⑦ 무한발행 공격 타임라인 시뮬레이션")
    st.caption(
        "대량 민트 공격 1건에 대해 3개 시스템의 **시간 축별 누적 피해 공식(`1 - e^(-v×t)`)** 시뮬레이션. "
        "1계층(주황선)보다 2계층(초록선)이 더 빠르게 차단합니다. (수동거버넌스 제외)"
    )

    import math as _math

    ATTACK_AMOUNT = 3_000_000   # 300만 토큰 대량발행 가정
    ATTACK_VELOCITY = 0.18      # 무한발행 확산 속도
    TOKEN_PRICE_USD = 1.0

    # 시스템별 대응 시간(초) — 시뮬레이션 파라미터에서 산출 (수동거버넌스 제외)
    SYSTEM_RESPONSE = {
        '앙상블모델 + 1계층 모델':      0.35,   # 350ms
        '앙상블모델 + 2계층모델':       0.12,   # 120ms
        'SequenceAnomaly + 1계층 모델': 0.35,
        'FlashLoanRule + 1계층 모델':   0.35,
        'HoustonLite + 1계층 모델':     0.35,
    }
    SYSTEM_COLORS = {
        '앙상블모델 + 1계층 모델':      '#F39C12',
        '앙상블모델 + 2계층모델':       '#27AE60',
        'SequenceAnomaly + 1계층 모델': '#A569BD',
        'FlashLoanRule + 1계층 모델':   '#5DADE2',
        'HoustonLite + 1계층 모델':     '#45B39D',
    }

    t_max = 350
    t_points = [i * 0.5 for i in range(int(t_max / 0.5) + 1)]

    timeline_rows = []
    for sys_name, t_response in SYSTEM_RESPONSE.items():
        for t in t_points:
            if t < t_response:
                ratio = min(0.98, 1.0 - _math.exp(-ATTACK_VELOCITY * t))
            else:
                ratio = min(0.98, 1.0 - _math.exp(-ATTACK_VELOCITY * t_response))
            timeline_rows.append({
                '시간(초)': t,
                '누적피해(USD)': ATTACK_AMOUNT * TOKEN_PRICE_USD * ratio,
                '시스템': sys_name,
                '대응시각': t_response,
            })

    tl_df = pd.DataFrame(timeline_rows)

    line = alt.Chart(tl_df).mark_line(strokeWidth=2.5).encode(
        x=alt.X('시간(초):Q', title='공격 발생 후 경과 시간 (초)'),
        y=alt.Y('누적피해(USD):Q', title='누적 피해 (USD)'),
        color=alt.Color('시스템:N',
                        scale=alt.Scale(
                            domain=list(SYSTEM_COLORS.keys()),
                            range=list(SYSTEM_COLORS.values())
                        )),
        tooltip=['시스템', alt.Tooltip('시간(초)', format='.1f'),
                 alt.Tooltip('누적피해(USD)', format='$,.0f')]
    )

    vlines = alt.Chart(pd.DataFrame([
        {'대응시각': v, '시스템': k} for k, v in SYSTEM_RESPONSE.items()
    ])).mark_rule(strokeDash=[5, 4], strokeWidth=1.8).encode(
        x='대응시각:Q',
        color=alt.Color('시스템:N',
                        scale=alt.Scale(
                            domain=list(SYSTEM_COLORS.keys()),
                            range=list(SYSTEM_COLORS.values())
                        ))
    )

    st.altair_chart(
        (line + vlines).properties(
            height=430,
            title=f'무한발행 공격 타임라인: {ATTACK_AMOUNT:,} 토큰 대량발행 대응 시뮬레이션'
        ),
        use_container_width=True
    )
    st.caption("점선: 각 시스템의 대응 시각. 탐지엔진 단독 1계층과 앙상블 2계층의 미세한 대응 시간 차이를 확인할 수 있습니다.")

    # =========================================================================
    # ⑧ 단일계층 엔진 과부하 FPR 시각화
    # =========================================================================
    st.divider()
    st.markdown("### ⚠️ ⑨ 단일계층 엔진 과부하 vs FPR (핵심)")
    st.caption(
        """
        단일계층은 Macro+Micro 돕일 엔진으로 모두 처리하므로, 트랜잭션 수가 늘어나면 과부하로 FPR이 동적으로 상승합니다.
        2계층은 엔진이 분리되어 있어 Micro 처리가 Macro엔 영향을 주지 않으므로 FPR이 일정하게 유지됩니다.
        """
    )

    # 단일계층 과부하 맨델릴 모델: 건수 취축에 따른 FPR 변화
    overload_threshold = 50
    overload_fpr_increment = 0.04
    max_overload_fpr = 0.18
    base_fpr = 0.05

    tx_counts = list(range(0, 301, 10))
    overload_rows = []
    for tx in tx_counts:
        overload_level = tx // overload_threshold
        single_fpr = min(max_overload_fpr, base_fpr + overload_level * overload_fpr_increment)
        overload_rows.append({'처리 건수': tx, 'FPR (%)': single_fpr * 100, '시스템': '단일계층 (다이나믹 FPR)'})
        overload_rows.append({'처리 건수': tx, 'FPR (%)': base_fpr * 100 * 0.4, '시스템': '2계층 (엔진 분리, 일정 유지)'})

    overload_df = pd.DataFrame(overload_rows)
    overload_chart = alt.Chart(overload_df).mark_line(strokeWidth=2.5).encode(
        x=alt.X('시스템 회:Q' if '시스템 회' in overload_df.columns else '처리 건수:Q',
                title='누적 시나리오 처리 건수'),
        y=alt.Y('FPR (%):Q', title='오탐율 FPR (%)',
                scale=alt.Scale(domain=[0, 20])),
        color=alt.Color('시스템:N',
                        scale=alt.Scale(
                            domain=['단일계층 (다이나믹 FPR)', '2계층 (엔진 분리, 일정 유지)'],
                            range=['#F39C12', '#27AE60']
                        )),
        tooltip=['시스템', '처리 건수', alt.Tooltip('FPR (%)', format='.1f')]
    ).properties(
        height=350,
        title='단일계층 vs 2계층: 부하 증가에 따른 오탐율(FPR) 변화'
    )
    st.altair_chart(overload_chart, use_container_width=True)

    # 트랜잭션 별 단일계층 latency 비교 (실제 실험 데이터)
    sybil_latency_rows = []
    for name, collector in collectors.items():
        for r in collector.results:
            s_type = r.metadata.get('scenario_type', '')
            is_swarm = r.metadata.get('is_catastrophic', False)  # fallback metadata
            if s_type == 'sybil_attack':
                sybil_latency_rows.append({
                    '시스템': name,
                    '탐지시간(ms)': r.latency_ms,
                    '공격유형': 'Micro 시빌 떼' if r.metadata.get('amount', 9999) < 100_000 else '일반 시빌',
                })

    if sybil_latency_rows:
        sybil_df = pd.DataFrame(sybil_latency_rows)
        sybil_chart = alt.Chart(sybil_df).mark_boxplot(extent='min-max').encode(
            x=alt.X('시스템:N', axis=alt.Axis(labelAngle=0)),
            y=alt.Y('탐지시간(ms):Q', title='탐지 시간 (ms, log)',
                    scale=alt.Scale(type='log')),
            color='시스템:N',
            column='공격유형:N',
        ).properties(height=320, title='시빌 공격별 탐지 시간 분포: Micro 떼 vs 일반 시빌')
        st.altair_chart(sybil_chart, use_container_width=True)
        st.caption("단일계층의 Micro 시빌 떼 탐지시간과 2계층의 차이가 명확하일수록 엔진 분리 효과가 드러납니다.")

    # 제내보내기
    # =========================================================================
    st.divider()
    st.markdown("### 💾 결과 내보내기")
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        summary_csv = pd.DataFrame(summary_rows).to_csv(index=False, encoding='utf-8-sig')
        st.download_button("📥 요약 결과 (CSV)", summary_csv, "benchmark_summary.csv", "text/csv")
    with col_e2:
        if st.button("📥 상세 결과 (JSON) 다운로드"):
            detailed = runner.get_detailed_comparison()
            detailed_json = __import__('json').dumps(detailed, indent=2, ensure_ascii=False)
            st.download_button("⬇️ JSON 저장", detailed_json, "benchmark_detailed.json", "application/json")

# ============================================================================
# 하단: 논문 목표 기준표
# ============================================================================
st.divider()
st.subheader("🎯 논문 목표 기준 대조표")
target_df = pd.DataFrame([
    {
        '시스템': '기존 수동 거버넌스',
        '탐지율': '~60%',
        '오탐율': '~15%',
        '응답 시간 (latency)': '150,000ms 이상 (2.5분+)',
        '총 사고대응': '30~80분',
        '자산 보존율': '낮음',
        '서비스 실효 가동률': '~5~20% (전체 중단 빈번)',
        '중단 시간': '30~80분',
    },
    {
        '시스템': 'FDS 단일 계층',
        '탐지율': '~85%',
        '오탐율': '기본 5% / 과부하 최대 18%',
        '응답 시간 (latency)': 'Macro: 250ms / Micro: 875ms+',
        '총 사고대응': '5~30분',
        '자산 보존율': '중간',
        '서비스 실효 가동률': '~30~60% (소규모 공격 시 전체 중단율 높음)',
        '중단 시간': '5~30분',
    },
    {
        '시스템': 'FDS 2계층 (제안)',
        '탐지율': '>92%',
        '오탐율': 'Macro 5% / Micro ~2% (전용엔진, 과부하 면역)',
        '응답 시간 (latency)': 'Macro: 250ms / Micro: 60ms',
        '총 사고대응': '<15분',
        '자산 보존율': '높음 (최소화)',
        '서비스 실효 가동률': '85~95%+ (Micro 계속 유지)',
        '중단 시간': '0초 (Micro) / <15분 (Macro)',
    },
])
st.dataframe(target_df, use_container_width=True, hide_index=True)
