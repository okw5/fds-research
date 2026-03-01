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
    FDSTwoLayerSystem
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
    max_value=10,
    value=1,
    help="통계적 유의성을 위한 반복 실험 횟수"
)

include_network_mix = st.sidebar.checkbox(
    "네트워크 혼잡 시나리오 포함",
    value=True,
    help="정상/혼잡/극심한 혼잡 네트워크 조건 포함"
)

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
            dataset = generator.get_mixed_dataset(
                total_count=dataset_size,
                attack_ratio=attack_ratio,
                network_mix=include_network_mix
            )
            st.session_state.benchmark_dataset = dataset
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
        systems = [
            ManualGovernanceSystem(),
            FDSSingleLayerSystem(),
            FDSTwoLayerSystem()
        ]
        
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
    st.caption("탐지율·오탐율·응답 시간·자산 보존율·서비스 가동률 등 8개 핵심 지표로 3개 시스템을 비교합니다.")

    summary_rows = []
    for name, collector in collectors.items():
        summary = collector.get_summary()
        cm = summary['confusion_matrix']
        fpr = cm['FP'] / (cm['FP'] + cm['TN']) if (cm['FP'] + cm['TN']) > 0 else 0
        gas = summary.get('gas_consumption', {})
        avg_gas = sum(gas.get(f'avg_{k}', 0) for k in ['signature_verification', 'pause', 'blacklist_addition'])
        summary_rows.append({
            '시스템 구성': name,
            '탐지율 (Recall)': f"{summary['recall']*100:.1f}%",
            '오탐율 (FPR)': f"{fpr*100:.1f}%",
            'F1-Score': f"{summary['f1_score']:.3f}",
            '응답 시간 (avg)': f"{summary['latency']['avg_ms']:.0f} ms",
            '자산 보존율': f"{summary['financial_loss']['prevention_rate']*100:.1f}%",
            '서비스 가동률': f"{summary['availability']['micro_availability']*100:.1f}%",
            '평균 Downtime': f"{summary['service_downtime']['avg_per_detection_min']:.1f} 분",
            '평균 가스비 (Gas)': f"{avg_gas:,.0f}",
        })

    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

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
            # 보존율: 실제 손실 / (TP건에서 복원된 금액 기준) 단순화
            tp_cases = [r for r in matched if r.is_true_positive]
            fn_cases = [r for r in matched if r.is_false_negative]
            total = len(matched)
            if total == 0:
                rate = 1.0
            else:
                # TP → 탐지 성공 (보존), FN → 탐지 실패 (손실)
                rate = len(tp_cases) / (len(tp_cases) + len(fn_cases)) if (tp_cases or fn_cases) else 1.0
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
    # 단일 계층과 2계층만 비교
    box_df = lat_df[lat_df['시스템'].isin(['FDS 단일 토큰', 'FDS 2계층 토큰'])]

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
    st.caption("Micro / Macro 공격별 서비스 중단 시간을 로그 스케일로 시각화. 2계층은 Micro 공격 시 중단 시간 0초를 달성합니다.")

    macro_scenario_types = {'infinite_mint', 'reserve_drain', 'flash_loan_depeg'}
    downtime_rows = []
    for name, collector in collectors.items():
        for r in collector.results:
            if r.predicted != 'ATTACK':
                continue
            s_type = r.metadata.get('scenario_type', '')
            category = 'Macro 공격' if s_type in macro_scenario_types else 'Micro 공격'
            downtime_rows.append({'시스템': name, '공격 유형': category, '중단시간(초)': max(0.01, r.service_downtime_sec)})

    if downtime_rows:
        dt_df = pd.DataFrame(downtime_rows).groupby(['시스템', '공격 유형'])['중단시간(초)'].mean().reset_index()
        dt_chart = alt.Chart(dt_df).mark_bar().encode(
            x=alt.X('공격 유형:N', title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y('중단시간(초):Q', title='평균 중단 시간 (초, Log Scale)', scale=alt.Scale(type='log')),
            color=alt.Color('시스템:N', title='시스템'),
            xOffset='시스템:N',
            tooltip=['시스템', '공격 유형', alt.Tooltip('중단시간(초)', format='.1f')]
        ).properties(height=380, title='공격 성격별 서비스 중단 시간 비교')
        st.altair_chart(dt_chart, use_container_width=True)
        st.markdown("> **Note**: 2계층 시스템은 소액 결제 계층을 유지하여 Micro 공격 시 서비스 중단 시간 **0초**를 달성합니다.")
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
    # 내보내기
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
    {'시스템': '기존 수동 거버넌스', '탐지율': '~60%', '오탐율': '~15%',
     '응답 시간': '~5,000 ms', '자산 보존율': '낮음', '서비스 가동률': '0% (전체 정지)', '중단 시간': '30~120 분'},
    {'시스템': 'FDS 단일 계층', '탐지율': '~85%', '오탐율': '~5%',
     '응답 시간': '~350 ms', '자산 보존율': '중간', '서비스 가동률': '0% (전체 정지)', '중단 시간': '5~30 분'},
    {'시스템': 'FDS 2계층 (제안)', '탐지율': '>92%', '오탐율': '<2%',
     '응답 시간': '<150 ms', '자산 보존율': '높음 (최소화)', '서비스 가동률': '100% (Micro 유지)', '중단 시간': '0초 (Micro) / <5분 (Macro)'},
])
st.dataframe(target_df, use_container_width=True, hide_index=True)
