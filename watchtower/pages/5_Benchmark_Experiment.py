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
# 결과 표시
# ============================================================================
if st.session_state.benchmark_results:
    st.divider()
    st.subheader("📈 실험 결과 분석")
    
    results = st.session_state.benchmark_results
    collectors = results['collectors']
    runner = results['runner']
    
    # 1. 핵심 비교 표 (종합)
    st.markdown("### 🏆 시스템 성능 종합 비교")
    
    comparison_data = []
    for name, collector in collectors.items():
        summary = collector.get_summary()
        comparison_data.append({
            '시스템 구성': name,
            # 성능
            'Precision': f"{summary['precision']:.2f}",
            'Recall': f"{summary['recall']:.2f}",
            'F1-Score': f"{summary['f1_score']:.2f}",
            'Latency': f"{summary['latency']['avg_ms']:.0f}ms",
            # 비즈니스 임팩트
            '피해금액(총)': f"${summary['financial_loss']['total_usd']:,.0f}",
            '평균 서비스 중단': f"{summary['service_downtime']['avg_per_detection_min']:.1f}분",
            '소액결제 가용률': f"{summary['availability']['micro_availability']*100:.1f}%"
        })
    
    comparison_df = pd.DataFrame(comparison_data)
    
    # 강조 표시를 위한 스타일링
    st.dataframe(
        comparison_df, 
        use_container_width=True, 
        hide_index=True,
        column_config={
            '소액결제 가용률': st.column_config.ProgressColumn(
                "소액결제 가용률",
                format="%s",
                min_value=0,
                max_value=100,
            ),
        }
    )
    
    # 2. 상세 시각화
    st.markdown("### 📊 상세 지표 시각화")
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "🛡️ 보안 성능 (Precision/Recall)", 
        "💰 피해 규모 및 중단 시간", 
        "🚦 서비스 가용성",
        "⚡ Latency & 기타"
    ])
    
    # Tab 1: 보안 성능
    with tab1:
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
            x=alt.X('Metric:N', title='평가 지표', axis=alt.Axis(labelAngle=0)),
            y=alt.Y('Value:Q', title='점수 (0~1)', scale=alt.Scale(domain=[0, 1])),
            color=alt.Color('System:N', title='시스템'),
            xOffset='System:N',
            tooltip=['System', 'Metric', 'Value']
        ).properties(
            width=600,
            height=400,
            title='탐지 정확도 비교'
        )
        st.altair_chart(chart, use_container_width=True)
    
    # Tab 2: 피해 규모 및 중단 시간
    with tab2:
        col_loss, col_downtime = st.columns(2)
        
        with col_loss:
            st.markdown("**💸 총 예상 피해금액 (낮을수록 좋음)**")
            loss_data = []
            for name, collector in collectors.items():
                loss = collector.get_summary()['financial_loss']['total_usd']
                loss_data.append({'System': name, 'Total Loss ($)': loss})
            
            loss_chart = alt.Chart(pd.DataFrame(loss_data)).mark_bar().encode(
                x=alt.X('System:N', title='시스템', axis=alt.Axis(labelAngle=0)),
                y=alt.Y('Total Loss ($):Q', title='피해금액 ($)'),
                color=alt.Color('System:N'),
                tooltip=['System', 'Total Loss ($)']
            ).properties(height=350)
            st.altair_chart(loss_chart, use_container_width=True)
            
        with col_downtime:
            st.markdown("**⏱️ 공격 탐지 1건당 평균 서비스 중단 시간 (낮을수록 좋음)**")
            downtime_data = []
            for name, collector in collectors.items():
                dt = collector.get_summary()['service_downtime']['avg_per_detection_min']
                downtime_data.append({'System': name, 'Avg Downtime (min)': dt})
            
            dt_chart = alt.Chart(pd.DataFrame(downtime_data)).mark_bar().encode(
                x=alt.X('System:N', title='시스템', axis=alt.Axis(labelAngle=0)),
                y=alt.Y('Avg Downtime (min):Q', title='평균 중단 시간 (분)'),
                color=alt.Color('System:N'),
                tooltip=['System', 'Avg Downtime (min)']
            ).properties(height=350)
            st.altair_chart(dt_chart, use_container_width=True)
            
    # Tab 3: 서비스 가용성
    with tab3:
        st.markdown("**🟢 소액결제 서비스 가용률 비교**")
        st.caption("공격 발생 및 대응 중에도 일반 사용자의 소액결제가 가능한 비율입니다.")
        
        avail_data = []
        for name, collector in collectors.items():
            avail = collector.get_summary()['availability']['micro_availability']
            avail_data.append({'System': name, 'Availability': avail})
            
        avail_chart = alt.Chart(pd.DataFrame(avail_data)).mark_bar().encode(
            y=alt.Y('System:N', title='시스템'),
            x=alt.X('Availability:Q', title='가용률 (0~1)', scale=alt.Scale(domain=[0, 1])),
            color=alt.Color('System:N'),
            tooltip=['System', alt.Tooltip('Availability', format='.1%')]
        ).properties(height=300)
        st.altair_chart(avail_chart, use_container_width=True)
        
        st.markdown("**❄️ 동결 범위 분포 (Freeze Scope)**")
        st.caption("방어 조치가 전체 네트워크에 영향을 미치는지, 선별적인지 보여줍니다.")
        
        freeze_data = []
        for name, collector in collectors.items():
            dist = collector.get_summary()['availability']['freeze_scope_distribution']
            for scope, count in dist.items():
                if count > 0:
                    freeze_data.append({'System': name, 'Scope': scope, 'Count': count})
        
        freeze_chart = alt.Chart(pd.DataFrame(freeze_data)).mark_arc().encode(
            theta=alt.Theta("Count", stack=True),
            color=alt.Color("Scope", legend=alt.Legend(title="동결 범위")),
            column=alt.Column("System", header=alt.Header(titleOrient="bottom", labelOrient="bottom")),
            tooltip=["System", "Scope", "Count"]
        ).properties(width=200, height=200)
        st.altair_chart(freeze_chart)
    
    # Tab 4: Latency & 기타
    with tab4:
        latency_data = []
        for name, collector in collectors.items():
            summary = collector.get_summary()
            latency_data.append({
                'System': name,
                'Average': summary['latency']['avg_ms'],
                'P95': summary['latency']['p95_ms']
            })
        
        lat_df = pd.melt(pd.DataFrame(latency_data), id_vars=['System'], var_name='Metric', value_name='ms')
        
        lat_chart = alt.Chart(lat_df).mark_bar().encode(
            x=alt.X('System:N', axis=alt.Axis(labelAngle=0)),
            y=alt.Y('ms:Q', title='Latency (ms)'),
            color='Metric:N',
            xOffset='Metric:N'
        ).properties(height=350)
        st.altair_chart(lat_chart, use_container_width=True)
        
        # 혼동 행렬
        st.markdown("**혼동 행렬 (Confusion Matrix)**")
        cm_cols = st.columns(3)
        for idx, (name, collector) in enumerate(collectors.items()):
            cm = collector.get_confusion_matrix()
            with cm_cols[idx]:
                st.markdown(f"**{name}**")
                cm_df = pd.DataFrame([
                    ['실제: 공격', f"TP: {cm['TP']}", f"FN: {cm['FN']}"],
                    ['실제: 정상', f"FP: {cm['FP']}", f"TN: {cm['TN']}"]
                ], columns=['', '예측: 공격', '예측: 정상'])
                st.dataframe(cm_df, hide_index=True, use_container_width=True)

    # 3. 데이터 내보내기
    st.divider()
    st.markdown("### 💾 보고서 및 데이터 내보내기")
    
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
\\caption{{FDS 시스템별 성능 및 비즈니스 영향 비교}}
\\begin{{tabular}}{{lcccccc}}
\\hline
시스템 & Precision & Recall & Latency & 피해금액 & 중단시간 & 가용성 \\\\
\\hline
"""
        for name, collector in collectors.items():
            s = collector.get_summary()
            latex_table += f"{name} & {s['precision']:.2f} & {s['recall']:.2f} & {s['latency']['avg_ms']:.0f}ms & \${s['financial_loss']['total_usd']:,.0f} & {s['service_downtime']['avg_per_detection_min']:.1f}min & {s['availability']['micro_availability']*100:.1f}\\% \\\\\n"
        
        latex_table += """\\hline
\\end{tabular}
\\end{table}
"""
        st.download_button(
            "📥 LaTeX 표 (논문용)",
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
    {
        '시스템': '기존 수동 거버넌스', 
        'Precision': 0.75, 
        'Recall': 0.60, 
        'Latency': '5000ms',
        '피해금액': 'High',
        '서비스 중단': '60분 이상',
        '소액결제 가용성': '불가 (0%)'
    },
    {
        '시스템': 'FDS 단일 토큰', 
        'Precision': 0.88, 
        'Recall': 0.82, 
        'Latency': '350ms',
        '피해금액': 'Medium',
        '서비스 중단': '15분 내외',
        '소액결제 가용성': '불가 (0%)'
    },
    {
        '시스템': 'FDS 2계층 토큰', 
        'Precision': 0.94, 
        'Recall': 0.91, 
        'Latency': '120ms',
        '피해금액': 'Low (최소화)',
        '서비스 중단': '< 5분 (Macro만)',
        '소액결제 가용성': '가능 (100%)'
    },
])

st.markdown("**📌 논문 목표 기준**")
st.dataframe(target_df, use_container_width=True, hide_index=True)

if st.session_state.benchmark_results:
    st.markdown("**📊 실제 실험 결과 (요약)**")
    st.dataframe(comparison_df, use_container_width=True, hide_index=True)
