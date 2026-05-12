"""
7_Threshold_Optimization.py
앙상블 엔진 가중치 & 오버라이드 임계값 Grid Search 최적화 실험 페이지

구성:
  Part 1 - 엔진 가중치 / 오버라이드 임계값 수동 실험
  Part 2 - Grid Search: 가중치 조합 자동 탐색 → 최적 F1/보안점수 도출
  Part 3 - 민감도 분석: 선택된 조합의 ROC/PR/CV 통계 근거
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import itertools
import sys
import os
import time

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from lib.benchmark.data_generator import BenchmarkDataGenerator
from lib.benchmark.detection_systems import FDSTwoLayerSystem

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Engine Weight Optimization - FDS Research",
    page_icon="🎯",
    layout="wide"
)

st.title("🎯 앙상블 엔진 가중치 & 임계값 최적화 실험")
st.markdown("""
**연구 목적**: FDS 2계층 Macro 엔진의 3개 서브 엔진 가중치와 오버라이드 임계값을 실험적으로 조정하여 최적의 탐지 성능(F1/보안점수)을 도출합니다.

| 엔진 | 역할 | 기본 가중치 |
|------|------|-----------|
| **Engine 1** (SequenceAnomaly) | 피처 분포 기반 이상 점수 | 0.50 |
| **Engine 2** (FlashLoanRule) | 서명/권한 검증 점수 | 0.30 |
| **Engine 3** (HoustonLite) | 금액 임계값 보조 점수 | 0.20 |
""")

# ── 사이드바: 실험 파라미터 ───────────────────────────────────────────────────
st.sidebar.header("🔧 실험 설정")

st.sidebar.subheader("📊 데이터셋 설정")
dataset_size = st.sidebar.slider(
    "데이터셋 크기", min_value=100, max_value=5000, value=500, step=100,
    help="테스트할 총 시나리오 수"
)
attack_ratio = st.sidebar.slider(
    "공격 비율", min_value=0.01, max_value=0.20, value=0.05, step=0.01,
    help="시뮬레이션 데이터의 공격 비율"
)
dataset_source = st.sidebar.radio(
    "데이터셋 소스",
    options=["시뮬레이션", "07-28 실제 TX 데이터", "하이브리드 (혼합)"],
    index=2,
    help="Benchmark Experiment 페이지와 동일한 데이터셋 소스"
)
random_seed = st.sidebar.number_input("랜덤 시드", min_value=0, max_value=9999, value=42)

st.sidebar.divider()
st.sidebar.subheader("⚙️ 엔진 가중치 (수동 실험)")
w1 = st.sidebar.slider("Engine 1 (SequenceAnomaly)", 0.0, 1.0, 0.50, 0.05,
                        help="피처 분포 기반 이상 점수 가중치")
w2 = st.sidebar.slider("Engine 2 (FlashLoanRule)", 0.0, 1.0, 0.30, 0.05,
                        help="서명/권한 검증 점수 가중치")
w3 = st.sidebar.slider("Engine 3 (HoustonLite)", 0.0, 1.0, 0.20, 0.05,
                        help="금액 임계값 보조 점수 가중치")

total_w = w1 + w2 + w3
if total_w > 0:
    st.sidebar.caption(f"정규화됨: E1={w1/total_w:.2f}, E2={w2/total_w:.2f}, E3={w3/total_w:.2f}")
else:
    st.sidebar.warning("가중치 합이 0입니다!")

st.sidebar.divider()
st.sidebar.subheader("🔒 임계값 설정")
override_threshold = st.sidebar.slider(
    "CRITICAL 오버라이드 임계값", 0.70, 0.99, 0.90, 0.01,
    help="CRITICAL 판정의 confidence가 이 값 이상일 때만 오버라이드 발동"
)
macro_decision_threshold = st.sidebar.slider(
    "Macro 판정 임계값", 0.30, 0.70, 0.48, 0.01,
    help="Macro 최종 점수가 이 값을 초과하면 ATTACK 판정"
)

st.sidebar.divider()
st.sidebar.subheader("🔍 Grid Search 설정")
grid_step = st.sidebar.select_slider(
    "가중치 탐색 단위",
    options=[0.05, 0.10, 0.20, 0.25],
    value=0.10,
    help="작을수록 세밀하지만 조합 수가 급증 (0.10 → ~66조합, 0.05 → ~231조합)"
)
grid_override_values = st.sidebar.multiselect(
    "Grid Search 오버라이드 임계값",
    options=[0.80, 0.85, 0.88, 0.90, 0.92, 0.95],
    default=[0.85, 0.90, 0.95],
    help="Grid Search 시 시도할 오버라이드 임계값들"
)

col_btn1, col_btn2 = st.sidebar.columns(2)
run_manual = col_btn1.button("▶️ 수동 실험", type="secondary", use_container_width=True)
run_grid = col_btn2.button("🔍 Grid Search", type="primary", use_container_width=True)

# ── 세션 상태 ────────────────────────────────────────────────────────────────
if 'opt_dataset' not in st.session_state:
    st.session_state.opt_dataset = None
if 'opt_manual_results' not in st.session_state:
    st.session_state.opt_manual_results = None
if 'opt_grid_results' not in st.session_state:
    st.session_state.opt_grid_results = None


# ── 헬퍼 함수 ────────────────────────────────────────────────────────────────

def generate_dataset(source, size, ratio, seed):
    """데이터셋 생성"""
    generator = BenchmarkDataGenerator(seed=seed)
    if source == "시뮬레이션":
        return generator.get_mixed_dataset(total_count=size, attack_ratio=ratio, network_mix=True)
    elif source == "07-28 실제 TX 데이터":
        return generator.get_0728_real_transaction_dataset(limit=size, shuffle=True)
    else:  # 하이브리드
        import random as _random
        _random.seed(seed)
        sim_count = int(size * 0.7)
        tx_data = generator.get_0728_real_transaction_dataset(limit=size - sim_count, shuffle=True)
        sim_data = generator.get_mixed_dataset(total_count=sim_count, attack_ratio=ratio, network_mix=True, shuffle=False)
        dataset = sim_data + tx_data
        _random.shuffle(dataset)
        return dataset


def run_experiment(dataset, engine_weights, override_thresh, macro_thresh, seed=42):
    """특정 가중치/임계값 조합으로 FDS 2계층 실험 실행"""
    np.random.seed(seed)
    
    system = FDSTwoLayerSystem(config={
        'engine_weights': {
            'engine1_anomaly': engine_weights[0],
            'engine2_signature': engine_weights[1],
            'engine3_threshold': engine_weights[2],
        },
        'override_threshold': override_thresh,
        'macro_decision_threshold': macro_thresh,
    })
    
    tp, fp, fn, tn = 0, 0, 0, 0
    total_latency = 0.0
    
    for scenario in dataset:
        prediction, latency_ms = system.detect(scenario)
        total_latency += latency_ms
        is_attack = scenario.label.value == "ATTACK"
        pred_attack = prediction == "ATTACK"
        
        if is_attack and pred_attack:
            tp += 1
        elif not is_attack and pred_attack:
            fp += 1
        elif is_attack and not pred_attack:
            fn += 1
        else:
            tn += 1
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
    security_score = f1 * (1.0 - fpr)
    avg_latency = total_latency / len(dataset) if dataset else 0
    
    return {
        'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn,
        'Precision': precision, 'Recall': recall,
        'F1': f1, 'FPR': fpr,
        'SecurityScore': security_score,
        'AvgLatency': avg_latency,
    }


def generate_weight_combinations(step=0.10):
    """합이 1.0이 되는 가중치 조합 생성 (정규화됨)"""
    combos = []
    values = np.arange(0.0, 1.0 + step/2, step)
    for w1 in values:
        for w2 in values:
            w3 = 1.0 - w1 - w2
            if w3 >= -0.001 and w3 <= 1.001:
                w3 = max(0.0, w3)
                combos.append((round(w1, 2), round(w2, 2), round(w3, 2)))
    return combos


# ── 데이터셋 자동 생성 ──────────────────────────────────────────────────────
if run_manual or run_grid:
    with st.spinner("데이터셋 생성 중..."):
        dataset = generate_dataset(dataset_source, dataset_size, attack_ratio, random_seed)
        st.session_state.opt_dataset = dataset
        
        total = len(dataset)
        atk = sum(1 for s in dataset if s.label.value == "ATTACK")
        nrm = total - atk
        real_tx = sum(1 for s in dataset if s.parameters.get('method') == 'real_tx')
        
        msg = f"📊 데이터셋: {total}개 (정상: {nrm}, 공격: {atk})"
        if real_tx > 0:
            msg += f" | 실제TX: {real_tx}개"
        st.info(msg)


# ── 수동 실험 ────────────────────────────────────────────────────────────────
if run_manual and st.session_state.opt_dataset:
    with st.spinner("수동 가중치 실험 실행 중..."):
        result = run_experiment(
            st.session_state.opt_dataset,
            (w1, w2, w3),
            override_threshold,
            macro_decision_threshold,
            seed=random_seed
        )
        st.session_state.opt_manual_results = {
            'weights': (w1, w2, w3),
            'override': override_threshold,
            'macro_thresh': macro_decision_threshold,
            'metrics': result,
        }
    st.success("✅ 수동 실험 완료!")


# ── Grid Search 실험 ─────────────────────────────────────────────────────────
if run_grid and st.session_state.opt_dataset:
    combos = generate_weight_combinations(grid_step)
    override_vals = grid_override_values if grid_override_values else [0.90]
    total_runs = len(combos) * len(override_vals)
    
    st.info(f"🔍 Grid Search 시작: {len(combos)}개 가중치 조합 × {len(override_vals)}개 임계값 = **{total_runs}회** 실험")
    
    progress = st.progress(0)
    status = st.empty()
    grid_rows = []
    
    for idx, (ov_thresh, combo) in enumerate(itertools.product(override_vals, combos)):
        result = run_experiment(
            st.session_state.opt_dataset,
            combo,
            ov_thresh,
            macro_decision_threshold,
            seed=random_seed
        )
        grid_rows.append({
            'E1_Weight': combo[0],
            'E2_Weight': combo[1],
            'E3_Weight': combo[2],
            'Override_Threshold': ov_thresh,
            'Precision': result['Precision'],
            'Recall': result['Recall'],
            'F1': result['F1'],
            'FPR': result['FPR'],
            'SecurityScore': result['SecurityScore'],
            'AvgLatency': result['AvgLatency'],
            'TP': result['TP'],
            'FP': result['FP'],
            'FN': result['FN'],
            'TN': result['TN'],
        })
        
        if (idx + 1) % max(1, total_runs // 100) == 0 or idx == total_runs - 1:
            progress.progress((idx + 1) / total_runs)
            status.text(f"진행: {idx+1}/{total_runs}")
    
    progress.empty()
    status.empty()
    
    st.session_state.opt_grid_results = pd.DataFrame(grid_rows)
    st.success(f"✅ Grid Search 완료! {total_runs}개 조합 탐색 완료")


# ============================================================================
# 결과 렌더링
# ============================================================================

# ── Part 1: 수동 실험 결과 ────────────────────────────────────────────────────
if st.session_state.opt_manual_results:
    st.divider()
    st.header("📊 수동 실험 결과")
    
    r = st.session_state.opt_manual_results
    m = r['metrics']
    wts = r['weights']
    tw = sum(wts)
    if tw > 0:
        nw = [x/tw for x in wts]
    else:
        nw = [0.33, 0.33, 0.34]
    
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("F1-Score", f"{m['F1']:.4f}")
    col2.metric("Precision", f"{m['Precision']:.4f}")
    col3.metric("Recall", f"{m['Recall']:.4f}")
    col4.metric("FPR", f"{m['FPR']:.4f}")
    col5.metric("보안점수", f"{m['SecurityScore']:.4f}")
    
    col6, col7, col8, col9 = st.columns(4)
    col6.metric("TP", m['TP'])
    col7.metric("FP", m['FP'])
    col8.metric("FN", m['FN'])
    col9.metric("TN", m['TN'])
    
    st.caption(
        f"가중치: E1={nw[0]:.2f}, E2={nw[1]:.2f}, E3={nw[2]:.2f} | "
        f"오버라이드 임계값: {r['override']} | Macro 판정 임계값: {r['macro_thresh']}"
    )


# ── Part 2: Grid Search 결과 ─────────────────────────────────────────────────
if st.session_state.opt_grid_results is not None:
    grid_df = st.session_state.opt_grid_results
    
    st.divider()
    st.header("🔍 Grid Search 결과")
    
    # ── 2-A. 최적 조합 Top 10 ────────────────────────────────────────────────
    st.subheader("🏆 ① F1-Score 기준 최적 가중치 조합 Top 10")
    
    top_f1 = grid_df.nlargest(10, 'F1').reset_index(drop=True)
    top_f1.index = top_f1.index + 1  # 1부터 시작
    
    st.dataframe(
        top_f1[['E1_Weight', 'E2_Weight', 'E3_Weight', 'Override_Threshold',
                'F1', 'Precision', 'Recall', 'FPR', 'SecurityScore']].style
            .highlight_max(subset=['F1'], color='#d4edda')
            .highlight_max(subset=['SecurityScore'], color='#cce5ff')
            .format({
                'F1': '{:.4f}', 'Precision': '{:.4f}', 'Recall': '{:.4f}',
                'FPR': '{:.4f}', 'SecurityScore': '{:.4f}',
            }),
        use_container_width=True
    )
    
    best_f1_row = grid_df.loc[grid_df['F1'].idxmax()]
    
    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
    col_b1.metric("🥇 최적 F1", f"{best_f1_row['F1']:.4f}")
    col_b2.metric("E1/E2/E3", f"{best_f1_row['E1_Weight']:.2f}/{best_f1_row['E2_Weight']:.2f}/{best_f1_row['E3_Weight']:.2f}")
    col_b3.metric("Override", f"{best_f1_row['Override_Threshold']:.2f}")
    col_b4.metric("보안점수", f"{best_f1_row['SecurityScore']:.4f}")
    
    st.divider()
    
    # ── 2-B. 보안 점수 기준 Top 10 ───────────────────────────────────────────
    st.subheader("🛡️ ② 보안점수 (F1×(1-FPR)) 기준 최적 가중치 Top 10")
    
    top_sec = grid_df.nlargest(10, 'SecurityScore').reset_index(drop=True)
    top_sec.index = top_sec.index + 1
    
    st.dataframe(
        top_sec[['E1_Weight', 'E2_Weight', 'E3_Weight', 'Override_Threshold',
                 'SecurityScore', 'F1', 'Precision', 'Recall', 'FPR']].style
            .highlight_max(subset=['SecurityScore'], color='#d4edda')
            .format({
                'SecurityScore': '{:.4f}', 'F1': '{:.4f}', 'Precision': '{:.4f}',
                'Recall': '{:.4f}', 'FPR': '{:.4f}',
            }),
        use_container_width=True
    )
    
    best_sec_row = grid_df.loc[grid_df['SecurityScore'].idxmax()]
    
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    col_s1.metric("🥇 최적 보안점수", f"{best_sec_row['SecurityScore']:.4f}")
    col_s2.metric("E1/E2/E3", f"{best_sec_row['E1_Weight']:.2f}/{best_sec_row['E2_Weight']:.2f}/{best_sec_row['E3_Weight']:.2f}")
    col_s3.metric("Override", f"{best_sec_row['Override_Threshold']:.2f}")
    col_s4.metric("F1", f"{best_sec_row['F1']:.4f}")
    
    st.divider()
    
    # ── 2-C. 오버라이드 임계값별 비교 ─────────────────────────────────────────
    st.subheader("📈 ③ 오버라이드 임계값별 최적 성능 비교")
    
    override_summary = []
    for ov in sorted(grid_df['Override_Threshold'].unique()):
        subset = grid_df[grid_df['Override_Threshold'] == ov]
        best = subset.loc[subset['F1'].idxmax()]
        override_summary.append({
            '오버라이드 임계값': ov,
            '최적 E1': best['E1_Weight'],
            '최적 E2': best['E2_Weight'],
            '최적 E3': best['E3_Weight'],
            'F1': best['F1'],
            'Precision': best['Precision'],
            'Recall': best['Recall'],
            'FPR': best['FPR'],
            '보안점수': best['SecurityScore'],
        })
    
    ov_df = pd.DataFrame(override_summary)
    st.dataframe(
        ov_df.style
            .highlight_max(subset=['F1'], color='#d4edda')
            .highlight_max(subset=['보안점수'], color='#cce5ff')
            .format({
                'F1': '{:.4f}', 'Precision': '{:.4f}', 'Recall': '{:.4f}',
                'FPR': '{:.4f}', '보안점수': '{:.4f}',
            }),
        use_container_width=True, hide_index=True
    )
    
    # 오버라이드 임계값별 F1/보안점수 차트
    fig_ov = go.Figure()
    fig_ov.add_trace(go.Bar(
        x=[str(r['오버라이드 임계값']) for _, r in ov_df.iterrows()],
        y=ov_df['F1'],
        name='F1-Score',
        marker_color='#3498db'
    ))
    fig_ov.add_trace(go.Bar(
        x=[str(r['오버라이드 임계값']) for _, r in ov_df.iterrows()],
        y=ov_df['보안점수'],
        name='보안점수',
        marker_color='#2ecc71'
    ))
    fig_ov.update_layout(
        barmode='group',
        title='오버라이드 임계값별 최적 F1 & 보안점수',
        xaxis_title='Override Threshold',
        yaxis_title='Score',
        height=400,
        plot_bgcolor='rgba(240,248,255,1)',
    )
    st.plotly_chart(fig_ov, use_container_width=True)
    
    st.divider()
    
    # ── 2-D. 히트맵: E1 vs E2 고정 시 F1 분포 ────────────────────────────────
    st.subheader("🗺️ ④ 가중치 히트맵 (Engine 1 vs Engine 2)")
    
    # 가장 좋은 override threshold의 데이터만 히트맵용으로 사용
    best_ov = best_f1_row['Override_Threshold']
    heatmap_df = grid_df[grid_df['Override_Threshold'] == best_ov].copy()
    
    pivot = heatmap_df.pivot_table(
        index='E2_Weight', columns='E1_Weight', values='F1', aggfunc='max'
    )
    
    fig_heat = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=[f"{v:.2f}" for v in pivot.columns],
        y=[f"{v:.2f}" for v in pivot.index],
        colorscale='Viridis',
        colorbar_title='F1-Score',
        text=np.round(pivot.values, 3),
        texttemplate='%{text}',
        textfont=dict(size=10),
    ))
    fig_heat.update_layout(
        title=f'F1-Score 히트맵 (Override={best_ov}, E3=1-E1-E2)',
        xaxis_title='Engine 1 (SequenceAnomaly) Weight',
        yaxis_title='Engine 2 (FlashLoanRule) Weight',
        height=500,
    )
    st.plotly_chart(fig_heat, use_container_width=True)
    
    st.divider()
    
    # ── 2-E. 레이더 차트: Top 5 비교 ─────────────────────────────────────────
    st.subheader("🎯 ⑤ Top 5 가중치 조합 다차원 비교 (레이더 차트)")
    
    top5 = grid_df.nlargest(5, 'F1').reset_index(drop=True)
    categories = ['F1', 'Recall', 'Precision', '보안점수', '1-FPR']
    colors_radar = px.colors.qualitative.Set1
    
    fig_radar = go.Figure()
    for i, row in top5.iterrows():
        vals = [
            row['F1'], row['Recall'], row['Precision'],
            row['SecurityScore'], 1.0 - row['FPR'],
        ]
        label = f"E1={row['E1_Weight']:.1f}/E2={row['E2_Weight']:.1f}/E3={row['E3_Weight']:.1f}"
        fig_radar.add_trace(go.Scatterpolar(
            r=vals + [vals[0]],
            theta=categories + [categories[0]],
            fill='toself',
            name=label,
            line=dict(color=colors_radar[i % len(colors_radar)], width=2.5 if i == 0 else 1.5),
            opacity=0.9 if i == 0 else 0.5,
        ))
    
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        title='Top 5 가중치 조합 다차원 성능 비교',
        height=520,
    )
    st.plotly_chart(fig_radar, use_container_width=True)
    
    st.divider()
    
    # ── 2-F. 종합 결론 ───────────────────────────────────────────────────────
    st.subheader("📝 Grid Search 종합 결론")
    
    col_c1, col_c2, col_c3 = st.columns(3)
    col_c1.metric(
        "F1 최적 가중치",
        f"E1={best_f1_row['E1_Weight']:.2f} / E2={best_f1_row['E2_Weight']:.2f} / E3={best_f1_row['E3_Weight']:.2f}",
        f"F1 = {best_f1_row['F1']:.4f}"
    )
    col_c2.metric(
        "보안점수 최적 가중치",
        f"E1={best_sec_row['E1_Weight']:.2f} / E2={best_sec_row['E2_Weight']:.2f} / E3={best_sec_row['E3_Weight']:.2f}",
        f"보안 = {best_sec_row['SecurityScore']:.4f}"
    )
    col_c3.metric(
        "기본 설정 (0.50/0.30/0.20)",
        f"F1 = {grid_df[(grid_df['E1_Weight']==0.50) & (grid_df['E2_Weight']==0.30) & (grid_df['E3_Weight']==0.20)]['F1'].max():.4f}"
        if not grid_df[(grid_df['E1_Weight']==0.50) & (grid_df['E2_Weight']==0.30) & (grid_df['E3_Weight']==0.20)].empty
        else "N/A",
        "현재 기본값"
    )
    
    # CSV 내보내기
    st.divider()
    st.subheader("💾 Grid Search 결과 내보내기")
    col_dl1, col_dl2 = st.columns(2)
    
    with col_dl1:
        csv_full = grid_df.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            "📥 전체 Grid Search 결과 CSV",
            csv_full, "grid_search_full.csv", "text/csv"
        )
    with col_dl2:
        csv_top = grid_df.nlargest(20, 'F1').to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            "📥 Top 20 결과 CSV",
            csv_top, "grid_search_top20.csv", "text/csv"
        )


# ── 실험 전 안내 ─────────────────────────────────────────────────────────────
if st.session_state.opt_manual_results is None and st.session_state.opt_grid_results is None:
    st.divider()
    st.info("👈 사이드바에서 파라미터를 설정한 뒤 **수동 실험** 또는 **Grid Search** 버튼을 눌러주세요.")
    
    with st.expander("📖 실험 가이드"):
        st.markdown("""
### 수동 실험
- 사이드바에서 Engine 1/2/3 가중치와 오버라이드 임계값을 직접 설정하고 **▶️ 수동 실험** 클릭
- 한 번의 실험으로 해당 설정의 F1, Precision, Recall, FPR, 보안점수를 즉시 확인

### Grid Search
- **🔍 Grid Search** 클릭 시 가중치 조합을 자동으로 탐색
- 탐색 단위(step)를 작게 설정할수록 더 세밀하지만 시간이 오래 걸림
- 결과: Top 10 F1/보안점수, 히트맵, 레이더 차트, 오버라이드별 비교 등

### 엔진 가중치 의미
| 엔진 | 높이면 | 낮추면 |
|------|--------|--------|
| **E1 (SequenceAnomaly)** | 행동 패턴 기반 탐지 ↑ | 통계 이상 의존도 ↓ |
| **E2 (FlashLoanRule)** | 서명/권한 검증 중시 ↑ | 서명 우회 공격에 취약 |
| **E3 (HoustonLite)** | 금액 규칙 기반 탐지 ↑ | 소액 분산 공격에 취약 |
        """)
