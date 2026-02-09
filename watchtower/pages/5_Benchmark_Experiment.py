"""
5_Benchmark_Experiment.py
객관적 평가 지표(Precision, Recall, F1-Score, Latency) 측정을 위한 벤치마크 실험 페이지
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

from lib.benchmark.scenario import Scenario, ScenarioType, ScenarioLabel
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
    page_title="Benchmark Experiment", 
    page_icon="📊", 
    layout="wide"
)

st.title("📊 객관적 평가 벤치마크 실험")
st.markdown("""
이 페이지에서는 **Precision, Recall, F1-Score, Latency** 등 객관적 평가 지표를 측정하여
세 가지 시스템을 정량적으로 비교합니다.

- **기존 수동 거버넌스**: 인간이 모니터링하고 판단하는 방식 (Baseline)
- **FDS 단일 토큰**: 자동화된 임계값 기반 탐지
- **FDS 2계층 토큰**: Micro/Macro 분리로 선택적 차단 (제안 모델)
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
            random_seed=random_seed
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
# 결과 표시
# ============================================================================
if st.session_state.benchmark_results:
    st.divider()
    st.subheader("📈 실험 결과")
    
    results = st.session_state.benchmark_results
    collectors = results['collectors']
    runner = results['runner']
    
    # 1. 핵심 비교 표
    st.markdown("### 🏆 시스템 비교 (핵심 지표)")
    
    comparison_data = []
    for name, collector in collectors.items():
        summary = collector.get_summary()
        comparison_data.append({
            '시스템 구성': name,
            'Precision': f"{summary['precision']:.2f}",
            'Recall': f"{summary['recall']:.2f}",
            'F1-Score': f"{summary['f1_score']:.2f}",
            'Latency': f"{summary['latency']['avg_ms']:.0f}ms",
            '정확도': f"{summary['accuracy']*100:.1f}%"
        })
    
    comparison_df = pd.DataFrame(comparison_data)
    st.dataframe(comparison_df, use_container_width=True, hide_index=True)
    
    # 2. 시각화 차트들
    st.markdown("### 📊 시각화")
    
    tab1, tab2, tab3, tab4 = st.tabs(["메트릭 비교", "혼동 행렬", "Latency 분포", "상세 분석"])
    
    with tab1:
        # 메트릭 비교 바 차트
        metrics_data = []
        for name, collector in collectors.items():
            summary = collector.get_summary()
            metrics_data.extend([
                {'System': name, 'Metric': 'Precision', 'Value': summary['precision']},
                {'System': name, 'Metric': 'Recall', 'Value': summary['recall']},
                {'System': name, 'Metric': 'F1-Score', 'Value': summary['f1_score']},
            ])
        
        metrics_df = pd.DataFrame(metrics_data)
        
        chart = alt.Chart(metrics_df).mark_bar().encode(
            x=alt.X('Metric:N', title='평가 지표'),
            y=alt.Y('Value:Q', title='점수', scale=alt.Scale(domain=[0, 1])),
            color=alt.Color('System:N', title='시스템'),
            xOffset='System:N'
        ).properties(
            width=600,
            height=400,
            title='시스템별 평가 지표 비교'
        )
        
        st.altair_chart(chart, use_container_width=True)
    
    with tab2:
        # 혼동 행렬
        st.markdown("**각 시스템의 혼동 행렬 (TP/TN/FP/FN)**")
        
        cm_cols = st.columns(3)
        for idx, (name, collector) in enumerate(collectors.items()):
            cm = collector.get_confusion_matrix()
            with cm_cols[idx]:
                st.markdown(f"**{name}**")
                cm_df = pd.DataFrame([
                    ['', '예측: 공격', '예측: 정상'],
                    ['실제: 공격', f"TP: {cm['TP']}", f"FN: {cm['FN']}"],
                    ['실제: 정상', f"FP: {cm['FP']}", f"TN: {cm['TN']}"]
                ])
                st.dataframe(cm_df, hide_index=True, use_container_width=True)
    
    with tab3:
        # Latency 비교
        latency_data = []
        for name, collector in collectors.items():
            summary = collector.get_summary()
            latency_data.append({
                'System': name,
                'Average': summary['latency']['avg_ms'],
                'Median': summary['latency']['median_ms'],
                'P95': summary['latency']['p95_ms'],
                'Max': summary['latency']['max_ms']
            })
        
        latency_df = pd.DataFrame(latency_data)
        
        # 바 차트
        latency_melt = pd.melt(
            latency_df, 
            id_vars=['System'], 
            value_vars=['Average', 'Median', 'P95'],
            var_name='Metric',
            value_name='Latency (ms)'
        )
        
        latency_chart = alt.Chart(latency_melt).mark_bar().encode(
            x=alt.X('System:N', title='시스템'),
            y=alt.Y('Latency (ms):Q', title='지연시간 (ms)'),
            color='Metric:N',
            xOffset='Metric:N'
        ).properties(
            width=600,
            height=400,
            title='시스템별 Latency 비교'
        )
        
        st.altair_chart(latency_chart, use_container_width=True)
        
        st.markdown("**Latency 상세 (ms)**")
        st.dataframe(latency_df, use_container_width=True, hide_index=True)
    
    with tab4:
        # 상세 분석
        selected_system = st.selectbox(
            "분석할 시스템 선택",
            options=list(collectors.keys())
        )
        
        if selected_system:
            collector = collectors[selected_system]
            summary = collector.get_summary()
            
            st.json(summary)
    
    # 3. 데이터 내보내기
    st.markdown("### 💾 결과 내보내기")
    
    col_exp1, col_exp2, col_exp3 = st.columns(3)
    
    with col_exp1:
        # 요약 CSV
        summary_csv = comparison_df.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            "📥 요약 결과 (CSV)",
            summary_csv,
            "benchmark_summary.csv",
            "text/csv"
        )
    
    with col_exp2:
        # 상세 결과 JSON
        detailed = runner.get_detailed_comparison()
        detailed_json = __import__('json').dumps(detailed, indent=2, ensure_ascii=False)
        st.download_button(
            "📥 상세 결과 (JSON)",
            detailed_json,
            "benchmark_detailed.json",
            "application/json"
        )
    
    with col_exp3:
        # 논문용 LaTeX 표
        latex_table = f"""
\\begin{{table}}[h]
\\centering
\\caption{{Baseline 비교 (객관적 평가)}}
\\begin{{tabular}}{{lcccr}}
\\hline
시스템 구성 & Precision & Recall & F1-Score & Latency \\\\
\\hline
"""
        for name, collector in collectors.items():
            s = collector.get_summary()
            latex_table += f"{name} & {s['precision']:.2f} & {s['recall']:.2f} & {s['f1_score']:.2f} & {s['latency']['avg_ms']:.0f}ms \\\\\n"
        
        latex_table += """\\hline
\\end{tabular}
\\end{table}
"""
        st.download_button(
            "📥 LaTeX 표",
            latex_table,
            "benchmark_table.tex",
            "text/plain"
        )

# ============================================================================
# 목표 결과 비교
# ============================================================================
st.divider()
st.subheader("🎯 목표 결과 vs 실험 결과")

target_df = pd.DataFrame([
    {'시스템': '기존 수동 거버넌스', 'Precision': 0.75, 'Recall': 0.60, 'F1-Score': 0.67, 'Latency': '5000ms'},
    {'시스템': 'FDS 단일 토큰', 'Precision': 0.88, 'Recall': 0.82, 'F1-Score': 0.85, 'Latency': '350ms'},
    {'시스템': 'FDS 2계층 토큰', 'Precision': 0.94, 'Recall': 0.91, 'F1-Score': 0.93, 'Latency': '120ms'},
])

st.markdown("**📌 목표 결과 (논문 기준)**")
st.dataframe(target_df, use_container_width=True, hide_index=True)

if st.session_state.benchmark_results:
    st.markdown("**📊 실제 실험 결과**")
    st.dataframe(comparison_df, use_container_width=True, hide_index=True)
    
    st.info("""
    💡 **참고**: 실험 결과는 랜덤성이 포함되어 있어 실행마다 약간 다를 수 있습니다.
    - 반복 횟수를 늘리면 통계적으로 더 안정적인 결과를 얻을 수 있습니다.
    - 랜덤 시드를 고정하면 동일한 결과를 재현할 수 있습니다.
    """)
