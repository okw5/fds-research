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
from lib.benchmark.scenario import ScenarioType
from lib.benchmark.feature_extractor import extract_features
from lib.benchmark.anomaly_scorer import AnomalyScorer

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Engine Weight Optimization - FDS Research",
    page_icon="🎯",
    layout="wide"
)

st.title("🎯 앙상블 엔진 가중치 & 임계값 최적화 실험")
st.markdown("""
**연구 목적**: FDS 2계층 Macro 엔진의 3개 내부 엔진(Engine) 가중치와 오버라이드 임계값을 실험적으로 조정하여 최적의 탐지 성능(F1/보안점수)을 도출합니다.

| 엔진 | 역할 | 기본 가중치 |
|-----------|------|-----------|
| **Engine 1** (이상탐지) | 피처 분포 기반 이상 점수 | 0.50 |
| **Engine 2** (패턴매칭) | 시나리오 패턴 및 컨트랙트 이상 검증 | 0.30 |
| **Engine 3** (HoustonLite) | 불변성 기반 규칙 점수 | 0.20 |
""")

# ── 사이드바: 실험 파라미터 ───────────────────────────────────────────────────
st.sidebar.header("🔧 실험 설정")

st.sidebar.subheader("📊 데이터셋 설정")
dataset_size = st.sidebar.slider(
    "데이터셋 크기", min_value=100, max_value=100_000, value=500, step=100,
    help="테스트할 총 시나리오 수 (최대 10만개)"
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
w1 = st.sidebar.slider("Engine 1 (이상탐지)", 0.0, 1.0, 0.50, 0.05,
                        help="피처 분포 기반 이상 점수 가중치")
w2 = st.sidebar.slider("Engine 2 (패턴매칭)", 0.0, 1.0, 0.30, 0.05,
                        help="패턴 매칭 검증 점수 가중치")
w3 = st.sidebar.slider("Engine 3 (HoustonLite)", 0.0, 1.0, 0.20, 0.05,
                        help="불변성 기반 임계값 검증 가중치")

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

col_btn1, col_btn2, col_btn3 = st.sidebar.columns(3)
run_manual = col_btn1.button("▶️ 수동", type="secondary", use_container_width=True)
run_grid = col_btn2.button("🔍 Grid", type="primary", use_container_width=True)
run_engine_analysis = col_btn3.button("🔬 엔진분석", type="secondary", use_container_width=True)

# ── 세션 상태 ────────────────────────────────────────────────────────────────
if 'opt_dataset' not in st.session_state:
    st.session_state.opt_dataset = None
if 'opt_manual_results' not in st.session_state:
    st.session_state.opt_manual_results = None
if 'opt_grid_results' not in st.session_state:
    st.session_state.opt_grid_results = None
if 'opt_engine_analysis' not in st.session_state:
    st.session_state.opt_engine_analysis = None


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


# 공격 유형별 피해금액 추정 비율 (금액 대비 실제 손실률)
_ATTACK_LOSS_RATIO = {
    'infinite_mint':      0.30,  # 발행량의 30% — 시장 가치 희석
    'reserve_drain':      0.85,  # 탈취액의 85% — 직접 손실
    'flash_loan_depeg':   0.15,  # 탈취액의 15% — 가격 조작 피해
    'sybil_attack':       0.20,  # 총 발행량의 20%
    'threshold_evasion':  0.30,  # 누적 탈취의 30%
    'gradual_escalation': 0.25,
    'camouflage':         0.15,
    'sandwich_attack':    0.40,  # MEV 피해
}

# 정상 거래 유형별 차단 시 기회비용 (토큰 단위 볼륨)
_NORMAL_BLOCK_RATIO = {
    'normal_transfer':    1.0,
    'large_transfer':     1.0,
    'liquidity_add':      1.2,   # 유동성 공급 차단 → 추가 손실
    'batch_payment':      1.0,
    'normal_mint':        1.1,
    'normal_flash_loan':  0.5,   # 정상 차익거래 차단
}

def _estimate_scenario_amount(scenario) -> float:
    """시나리오의 대표 금액 추출 (피해금액 계산용)"""
    p = scenario.parameters
    return float(
        p.get('amount',
        p.get('loan_amount',
        p.get('total_amount',
        p.get('amount_per_block',
        p.get('amount_per_wallet', 0)))))
    )


def run_experiment(dataset, engine_weights, override_thresh, macro_thresh, seed=42):
    """특정 가중치/임계값 조합으로 FDS 2계층 실험 실행
    
    반환 지표:
      - 기본: TP/FP/FN/TN, Precision/Recall/F1/FPR/SecurityScore
      - 피해금액: FN_FinancialLoss (미탐 공격 성공 시 추정 손실)
      - 오탐금액: FP_BlockedVolume (정상 거래 차단 시 기회비용)
    """
    np.random.seed(seed)

    system = FDSTwoLayerSystem(config={
        'engine_weights': {
            'engine1_anomaly':   engine_weights[0],
            'engine2_signature': engine_weights[1],
            'engine3_threshold': engine_weights[2],
        },
        'override_threshold':      override_thresh,
        'macro_decision_threshold': macro_thresh,
    })

    tp, fp, fn, tn = 0, 0, 0, 0
    total_latency = 0.0
    fn_financial_loss = 0.0   # 미탐 → 공격 성공 시 추정 피해
    fp_blocked_volume = 0.0   # 오탐 → 정상 거래 차단 볼륨

    for scenario in dataset:
        prediction, latency_ms = system.detect(scenario)
        total_latency += latency_ms
        is_attack   = scenario.label.value == "ATTACK"
        pred_attack = prediction == "ATTACK"

        if is_attack and pred_attack:
            tp += 1
        elif not is_attack and pred_attack:
            fp += 1
            # 오탐 차단 볼륨 누적
            amt = _estimate_scenario_amount(scenario)
            block_ratio = _NORMAL_BLOCK_RATIO.get(
                scenario.scenario_type.value, 1.0)
            fp_blocked_volume += amt * block_ratio
        elif is_attack and not pred_attack:
            fn += 1
            # 미탐 → 공격 성공 피해금액 누적
            amt = _estimate_scenario_amount(scenario)
            loss_ratio = _ATTACK_LOSS_RATIO.get(
                scenario.scenario_type.value, 0.25)
            fn_financial_loss += amt * loss_ratio
        else:
            tn += 1

    precision      = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall         = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1             = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    fpr            = fp / (fp + tn) if (fp + tn) > 0 else 0
    security_score = f1 * (1.0 - fpr)
    avg_latency    = total_latency / len(dataset) if dataset else 0

    return {
        'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn,
        'Precision': precision, 'Recall': recall,
        'F1': f1, 'FPR': fpr,
        'SecurityScore': security_score,
        'AvgLatency': avg_latency,
        'FN_FinancialLoss':  fn_financial_loss,
        'FP_BlockedVolume':  fp_blocked_volume,
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
if run_manual or run_grid or run_engine_analysis:
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
            'FN_FinancialLoss': result.get('FN_FinancialLoss', 0),
            'FP_BlockedVolume': result.get('FP_BlockedVolume', 0),
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

    r   = st.session_state.opt_manual_results
    m   = r['metrics']
    wts = r['weights']
    tw  = sum(wts)
    nw  = [x/tw for x in wts] if tw > 0 else [0.33, 0.33, 0.34]

    # ── 기본 성능 지표 ──────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("F1-Score",  f"{m['F1']:.4f}")
    col2.metric("Precision", f"{m['Precision']:.4f}")
    col3.metric("Recall",    f"{m['Recall']:.4f}")
    col4.metric("FPR",       f"{m['FPR']:.4f}")
    col5.metric("보안점수",   f"{m['SecurityScore']:.4f}")

    col6, col7, col8, col9 = st.columns(4)
    col6.metric("TP (정탐)",  m['TP'])
    col7.metric("FP (오탐)",  m['FP'])
    col8.metric("FN (미탐)",  m['FN'])
    col9.metric("TN (정상확인)", m['TN'])

    # ── 피해금액·오탐 영향 패널 ────────────────────────────────────
    fn_loss = m.get('FN_FinancialLoss', 0)
    fp_vol  = m.get('FP_BlockedVolume', 0)

    st.subheader("💸 재무적 영향 추정")
    ca, cb = st.columns(2)

    with ca:
        st.error(
            f"### 🔴 미탐 피해금액 (FN)"
            f"\n**{fn_loss:,.0f} 토큰** 상당"
            f"\n미탐된 공격 {m['FN']}건이 성공했을 경우의 추정 피해")
        if m['FN'] > 0:
            st.caption(
                f"FN 1건당 평균: {fn_loss/m['FN']:,.0f} 토큰 | "
                f"전체 공격 중 미탐율: {m['FN']/(m['TP']+m['FN'])*100:.1f}%"
                if (m['TP']+m['FN']) > 0 else "")

    with cb:
        st.warning(
            f"### 🟡 오탐 차단 볼륨 (FP)"
            f"\n**{fp_vol:,.0f} 토큰** 상당"
            f"\n오탐으로 차단된 정상 거래 {m['FP']}건의 기회비용")
        if m['FP'] > 0:
            st.caption(
                f"FP 1건당 평균: {fp_vol/m['FP']:,.0f} 토큰 | "
                f"전체 정상 중 오탐율: {m['FP']/(m['FP']+m['TN'])*100:.1f}%"
                if (m['FP']+m['TN']) > 0 else "")

    # 피해/비용 비교 바 차트
    if fn_loss > 0 or fp_vol > 0:
        fig_fin = go.Figure(data=[
            go.Bar(name='미탐 피해금액 (FN)', x=['재무 영향'], y=[fn_loss],
                    marker_color='#e74c3c'),
            go.Bar(name='오탐 기회비용 (FP)', x=['재무 영향'], y=[fp_vol],
                    marker_color='#f39c12'),
        ])
        fig_fin.update_layout(
            barmode='group', height=300,
            title='미탐 피해금액 vs 오탐 기회비용 비교 (토큰 단위)',
            yaxis_title='토큰 수량',
            plot_bgcolor='rgba(245,248,255,1)',
        )
        st.plotly_chart(fig_fin, use_container_width=True)

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
    
    best_weights_df = grid_df.loc[grid_df.groupby(['E1_Weight', 'E2_Weight', 'E3_Weight'])['F1'].idxmax()]
    top_f1 = best_weights_df.nlargest(10, 'F1').reset_index(drop=True)
    top_f1.index = top_f1.index + 1  # 1부터 시작
    
    st.dataframe(
        top_f1[['E1_Weight', 'E2_Weight', 'E3_Weight',
                'F1', 'Precision', 'Recall', 'FPR', 'SecurityScore',
                'FN_FinancialLoss', 'FP_BlockedVolume']].style
            .highlight_max(subset=['F1'], color='#d4edda')
            .highlight_max(subset=['SecurityScore'], color='#cce5ff')
            .highlight_min(subset=['FN_FinancialLoss'], color='#ffeeba')
            .format({
                'F1': '{:.4f}', 'Precision': '{:.4f}', 'Recall': '{:.4f}',
                'FPR': '{:.4f}', 'SecurityScore': '{:.4f}',
                'FN_FinancialLoss': '{:,.0f}', 'FP_BlockedVolume': '{:,.0f}',
            }),
        use_container_width=True
    )
    
    best_f1_row = top_f1.loc[1] if not top_f1.empty else grid_df.loc[grid_df['F1'].idxmax()]
    
    col_b1, col_b2, col_b3 = st.columns(3)
    col_b1.metric("🥇 최적 F1", f"{best_f1_row['F1']:.4f}")
    col_b2.metric("E1/E2/E3", f"{best_f1_row['E1_Weight']:.2f}/{best_f1_row['E2_Weight']:.2f}/{best_f1_row['E3_Weight']:.2f}")
    col_b3.metric("보안점수", f"{best_f1_row['SecurityScore']:.4f}")
    
    st.divider()
    
    # ── 2-B. 보안 점수 기준 Top 10 ───────────────────────────────────────────
    st.subheader("🛡️ ② 보안점수 (F1×(1-FPR)) 기준 최적 가중치 Top 10")
    
    best_sec_weights_df = grid_df.loc[grid_df.groupby(['E1_Weight', 'E2_Weight', 'E3_Weight'])['SecurityScore'].idxmax()]
    top_sec = best_sec_weights_df.nlargest(10, 'SecurityScore').reset_index(drop=True)
    top_sec.index = top_sec.index + 1
    
    st.dataframe(
        top_sec[['E1_Weight', 'E2_Weight', 'E3_Weight',
                 'SecurityScore', 'F1', 'Precision', 'Recall', 'FPR']].style
            .highlight_max(subset=['SecurityScore'], color='#d4edda')
            .format({
                'SecurityScore': '{:.4f}', 'F1': '{:.4f}', 'Precision': '{:.4f}',
                'Recall': '{:.4f}', 'FPR': '{:.4f}',
            }),
        use_container_width=True
    )
    
    best_sec_row = top_sec.loc[1] if not top_sec.empty else grid_df.loc[grid_df['SecurityScore'].idxmax()]
    
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("🥇 최적 보안점수", f"{best_sec_row['SecurityScore']:.4f}")
    col_s2.metric("E1/E2/E3", f"{best_sec_row['E1_Weight']:.2f}/{best_sec_row['E2_Weight']:.2f}/{best_sec_row['E3_Weight']:.2f}")
    col_s3.metric("F1", f"{best_sec_row['F1']:.4f}")
    
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
    
    # ── 2-D. 3D 산점도: 3개 엔진 가중치별 F1 분포 ────────────────────────────
    st.subheader("🗺️ ④ 가중치 3D 산점도 (Engine 1 vs 2 vs 3)")
    
    # 가장 좋은 override threshold의 데이터만 시각화용으로 사용
    best_ov = best_f1_row['Override_Threshold']
    heatmap_df = grid_df[grid_df['Override_Threshold'] == best_ov].copy()
    
    fig_3d = px.scatter_3d(
        heatmap_df,
        x='E1_Weight',
        y='E2_Weight',
        z='E3_Weight',
        color='F1',
        size='F1',
        color_continuous_scale='Viridis',
        opacity=0.8,
        hover_data=['SecurityScore', 'Precision', 'Recall']
    )
    
    fig_3d.update_layout(
        title=f'엔진별 가중치 조율에 따른 F1-Score 3D 분포 (Override={best_ov})',
        scene=dict(
            xaxis_title='Engine 1 (이상탐지)',
            yaxis_title='Engine 2 (패턴매칭)',
            zaxis_title='Engine 3 (HoustonLite)',
            camera=dict(
                eye=dict(x=1.5, y=1.5, z=1.2)
            )
        ),
        margin=dict(l=0, r=0, b=0, t=50),
        height=600,
    )
    st.plotly_chart(fig_3d, use_container_width=True)
    
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


# ═════════════════════════════════════════════════════════════════════════════
# Part 3: 엔진별 공격유형 탐지분석
# ═════════════════════════════════════════════════════════════════════════════

if run_engine_analysis and st.session_state.opt_dataset:
    with st.spinner("엔진별 공격유형 탐지 분석 중..."):
        np.random.seed(random_seed)
        scorer = AnomalyScorer(method='zscore')
        system = FDSTwoLayerSystem()
        
        ATTACK_TYPES = {
            ScenarioType.INFINITE_MINT: '무한발행',
            ScenarioType.RESERVE_DRAIN: '준비금탈취',
            ScenarioType.FLASH_LOAN_DEPEG: '플래시론',
            ScenarioType.SYBIL_ATTACK: '시빌어택',
            ScenarioType.SANDWICH_ATTACK: '샌드위치',
            ScenarioType.THRESHOLD_EVASION: '임계값회피',
            ScenarioType.GRADUAL_ESCALATION: '점진적증가',
            ScenarioType.CAMOUFLAGE: '위장공격',
        }
        NORMAL_TYPES = {
            ScenarioType.NORMAL_TRANSFER: '일반이체',
            ScenarioType.LARGE_TRANSFER: '대량이체',
            ScenarioType.LIQUIDITY_ADD: '유동성추가',
            ScenarioType.BATCH_PAYMENT: '배치결제',
            ScenarioType.NORMAL_MINT: '정상민트',
            ScenarioType.NORMAL_FLASH_LOAN: '정상플래시론',
        }
        ALL_TYPES = {**ATTACK_TYPES, **NORMAL_TYPES}
        
        # 시나리오별 엔진 점수 수집
        from collections import defaultdict
        type_scores = defaultdict(lambda: {'e1': [], 'e2': [], 'e3': [], 'ensemble': [], 'detected': []})
        
        for s in st.session_state.opt_dataset:
            stype = s.scenario_type
            if stype not in ALL_TYPES:
                continue
                
            features = extract_features(s)
            e1 = scorer.score(features)
            e2 = system._check_pattern_match(s, features)
            e3 = system._check_houston_invariant(s)
            
            # 앙상블 최종 (현재 설정 가중치)
            tw = w1 + w2 + w3
            if tw > 0:
                nw1, nw2, nw3 = w1/tw, w2/tw, w3/tw
            else:
                nw1, nw2, nw3 = 0.33, 0.33, 0.34
            ens = e1*nw1 + e2*nw2 + e3*nw3
            
            # 2계층 시스템 판정
            prediction, _ = system.detect(s)
            detected = prediction == 'ATTACK'
            
            type_scores[stype]['e1'].append(e1)
            type_scores[stype]['e2'].append(e2)
            type_scores[stype]['e3'].append(e3)
            type_scores[stype]['ensemble'].append(ens)
            type_scores[stype]['detected'].append(detected)
        
        # 결과 DataFrame
        rows = []
        for stype, label in ALL_TYPES.items():
            if stype not in type_scores:
                continue
            d = type_scores[stype]
            n = len(d['e1'])
            is_attack = stype in ATTACK_TYPES
            det_count = sum(d['detected'])
            det_rate = det_count / n if n > 0 else 0
            rows.append({
                '유형': label,
                '분류': '🔴 공격' if is_attack else '🟢 정상',
                'n': n,
                'E1 평균': np.mean(d['e1']),
                'E2 평균': np.mean(d['e2']),
                'E3 평균': np.mean(d['e3']),
                '앙상블 평균': np.mean(d['ensemble']),
                '탐지수': det_count,
                '탐지율': det_rate,
                # 엔진별 단독 탐지 가능 여부 (임계값 0.48 기준)
                'E1 탐지율': np.mean([1 if v > 0.48 else 0 for v in d['e1']]),
                'E2 탐지율': np.mean([1 if v > 0.48 else 0 for v in d['e2']]),
                'E3 탐지율': np.mean([1 if v > 0.48 else 0 for v in d['e3']]),
            })
        
        analysis_df = pd.DataFrame(rows)
        st.session_state.opt_engine_analysis = analysis_df
        st.session_state.opt_engine_analysis_weights = (nw1, nw2, nw3)
        
        # --- 추가: 현재 가중치에 대한 Override 최적값 ---
        ov_results = []
        ov_candidates = np.arange(0.10, 1.01, 0.01)
        for ov_cand in ov_candidates:
            res = run_experiment(
                st.session_state.opt_dataset,
                (nw1, nw2, nw3),
                round(ov_cand, 2),
                macro_decision_threshold,
                seed=random_seed
            )
            res['Override_Threshold'] = round(ov_cand, 2)
            ov_results.append(res)
        st.session_state.opt_engine_analysis_ov = pd.DataFrame(ov_results)
        
    st.success("✅ 엔진별 공격유형 분석 및 최적 Override 탐색 완료!")


# ── 엔진별 분석 결과 렌더링 ──────────────────────────────────────────────────
if st.session_state.opt_engine_analysis is not None:
    adf = st.session_state.opt_engine_analysis
    
    st.divider()
    st.header("🔬 엔진별 공격유형 탐지 분석")
    
    # ── 3-A. 공격유형별 엔진 점수 테이블 ──────────────────────────────────────
    st.subheader("① 공격유형별 각 엔진 평균 점수")
    st.dataframe(
        adf[['유형', '분류', 'n', 'E1 평균', 'E2 평균', 'E3 평균', '앙상블 평균', '탐지율']].style
            .background_gradient(subset=['E1 평균', 'E2 평균', 'E3 평균', '앙상블 평균'], cmap='YlOrRd')
            .format({
                'E1 평균': '{:.3f}', 'E2 평균': '{:.3f}', 'E3 평균': '{:.3f}',
                '앙상블 평균': '{:.3f}', '탐지율': '{:.1%}',
            }),
        use_container_width=True, hide_index=True
    )
    
    # ── 3-B. 공격 유형만 필터 — 히트맵 ────────────────────────────────────────
    atk_df = adf[adf['분류'] == '🔴 공격'].copy()
    
    if not atk_df.empty:
        st.subheader("② 공격유형 × 엔진 탐지율 히트맵")
        
        # 엔진별 단독 탐지율 히트맵 데이터
        heat_data = atk_df[['유형', 'E1 탐지율', 'E2 탐지율', 'E3 탐지율']].set_index('유형')
        heat_data.columns = ['E1 (이상탐지)', 'E2 (패턴매칭)', 'E3 (HoustonLite)']
        
        fig_heat = go.Figure(data=go.Heatmap(
            z=heat_data.values,
            x=heat_data.columns.tolist(),
            y=heat_data.index.tolist(),
            colorscale='RdYlGn',
            zmin=0, zmax=1,
            text=[[f"{v:.0%}" for v in row] for row in heat_data.values],
            texttemplate='%{text}',
            textfont=dict(size=14, color='black'),
            colorbar_title='탐지율',
        ))
        fig_heat.update_layout(
            title='공격유형별 엔진 단독 탐지율 (score > 0.48 기준)',
            height=max(350, len(atk_df) * 50 + 150),
            xaxis_title='탐지 엔진',
            yaxis_title='공격 유형',
            yaxis=dict(autorange='reversed'),
        )
        st.plotly_chart(fig_heat, use_container_width=True)
        
        # ── 3-C. 공격유형별 엔진 점수 비교 막대 차트 ──────────────────────────
        st.subheader("③ 공격유형별 엔진 평균 점수 비교")
        
        fig_bar = go.Figure()
        colors = {'E1 평균': '#3498db', 'E2 평균': '#e74c3c', 'E3 평균': '#2ecc71'}
        labels = {'E1 평균': 'E1 (이상탐지)', 'E2 평균': 'E2 (패턴매칭)', 'E3 평균': 'E3 (금액규칙)'}
        
        for col in ['E1 평균', 'E2 평균', 'E3 평균']:
            fig_bar.add_trace(go.Bar(
                x=atk_df['유형'],
                y=atk_df[col],
                name=labels[col],
                marker_color=colors[col],
            ))
        
        fig_bar.add_hline(y=0.48, line_dash='dash', line_color='gray',
                         annotation_text='Macro 판정 임계값 (0.48)')
        fig_bar.update_layout(
            barmode='group',
            title='공격유형별 각 엔진이 부여하는 평균 점수',
            xaxis_title='공격 유형',
            yaxis_title='평균 점수',
            height=450,
            yaxis=dict(range=[0, 1]),
            plot_bgcolor='rgba(245,250,255,1)',
        )
        st.plotly_chart(fig_bar, use_container_width=True)
        
        # ── 3-D. 정상 거래 오탐률 ────────────────────────────────────────────
        nrm_df = adf[adf['분류'] == '🟢 정상'].copy()
        if not nrm_df.empty:
            st.subheader("④ 정상유형별 엔진 오탐 점수")
            
            fig_nrm = go.Figure()
            for col in ['E1 평균', 'E2 평균', 'E3 평균']:
                fig_nrm.add_trace(go.Bar(
                    x=nrm_df['유형'],
                    y=nrm_df[col],
                    name=labels[col],
                    marker_color=colors[col],
                ))
            fig_nrm.add_hline(y=0.48, line_dash='dash', line_color='gray',
                             annotation_text='Macro 판정 임계값 (0.48)')
            fig_nrm.update_layout(
                barmode='group',
                title='정상유형별 각 엔진이 부여하는 평균 점수 (낮을수록 좋음)',
                xaxis_title='정상 유형',
                yaxis_title='평균 점수',
                height=400,
                yaxis=dict(range=[0, 1]),
                plot_bgcolor='rgba(245,255,245,1)',
            )
            st.plotly_chart(fig_nrm, use_container_width=True)
        
        # ── 3-E. 엔진별 강점/약점 요약 ───────────────────────────────────────
        st.subheader("⑤ 엔진별 강점/약점 요약")
        
        for eng_col, eng_name in [('E1 탐지율', 'E1 (이상탐지 — SequenceAnomaly)'),
                                   ('E2 탐지율', 'E2 (패턴매칭 — FlashLoanRule)'),
                                   ('E3 탐지율', 'E3 (불변성규칙 — HoustonLite)')]:
            best = atk_df.nlargest(2, eng_col)
            worst = atk_df.nsmallest(2, eng_col)
            st.markdown(f"**{eng_name}**")
            best_str = ", ".join([f"{r['유형']} ({r[eng_col]:.0%})" for _, r in best.iterrows()])
            worst_str = ", ".join([f"{r['유형']} ({r[eng_col]:.0%})" for _, r in worst.iterrows()])
            st.markdown(f"- 🟢 강점: {best_str}")
            st.markdown(f"- 🔴 약점: {worst_str}")

        # ── 3-F. 최적 Override Threshold ─────────────────────────────────────
        if 'opt_engine_analysis_ov' in st.session_state and st.session_state.opt_engine_analysis_ov is not None:
            ov_df = st.session_state.opt_engine_analysis_ov
            nw_vals = st.session_state.get('opt_engine_analysis_weights', (0.33, 0.33, 0.34))
            
            best_f1 = ov_df.loc[ov_df['F1'].idxmax()]
            best_sec = ov_df.loc[ov_df['SecurityScore'].idxmax()]
            
            st.divider()
            st.subheader("⑥ 현재 가중치 기반 최적 Override Threshold")
            st.markdown(f"설정된 가중치 조합(**E1**={nw_vals[0]:.2f}, **E2**={nw_vals[1]:.2f}, **E3**={nw_vals[2]:.2f}) 하에서 오버라이드 임계값(`override_Threshold`)을 0.10~1.00 범위 내에서 테스트한 결과입니다.")
            
            col_o1, col_o2, col_o3 = st.columns(3)
            col_o1.metric("🥇 F1 기준 최적 Override", f"{best_f1['Override_Threshold']:.2f}", f"F1: {best_f1['F1']:.4f}", delta_color="off")
            col_o2.metric("🛡️ 보안점수 기준 최적 Override", f"{best_sec['Override_Threshold']:.2f}", f"보안점수: {best_sec['SecurityScore']:.4f}", delta_color="off")
            
            # 꺾은선 그래프
            fig_ov_line = go.Figure()
            fig_ov_line.add_trace(go.Scatter(x=ov_df['Override_Threshold'], y=ov_df['F1'], mode='lines+markers', name='F1-Score', line=dict(color='#3498db')))
            fig_ov_line.add_trace(go.Scatter(x=ov_df['Override_Threshold'], y=ov_df['SecurityScore'], mode='lines+markers', name='보안점수', line=dict(color='#2ecc71')))
            fig_ov_line.update_layout(
                title='Override Threshold 변동에 따른 성능 변화',
                xaxis_title='Override Threshold',
                yaxis_title='Score',
                height=350,
                plot_bgcolor='rgba(240,248,255,1)'
            )
            st.plotly_chart(fig_ov_line, use_container_width=True)
            
            st.dataframe(
                ov_df[['Override_Threshold', 'F1', 'SecurityScore']].style
                    .highlight_max(subset=['F1', 'SecurityScore'], color='#d4edda')
                    .format({'F1': '{:.4f}', 'SecurityScore': '{:.4f}'}),
                use_container_width=True, hide_index=True
            )


# ── 실험 전 안내 ─────────────────────────────────────────────────────────────
if (st.session_state.opt_manual_results is None
    and st.session_state.opt_grid_results is None
    and st.session_state.opt_engine_analysis is None):
    st.divider()
    st.info("👈 사이드바에서 파라미터를 설정한 뒤 **수동 실험**, **Grid Search**, 또는 **🔬 엔진분석** 버튼을 눌러주세요.")
    
    with st.expander("📖 실험 가이드"):
        st.markdown("""
### 수동 실험
- 사이드바에서 Engine 1/2/3 가중치와 오버라이드 임계값을 직접 설정하고 **▶️ 수동** 클릭
- 한 번의 실험으로 해당 설정의 F1, Precision, Recall, FPR, 보안점수를 즉시 확인

### Grid Search
- **🔍 Grid** 클릭 시 가중치 조합을 자동으로 탐색
- 탐색 단위(step)를 작게 설정할수록 더 세밀하지만 시간이 오래 걸림

### 🔬 엔진별 공격유형 분석
- 공격유형(무한발행/준비금탈취/플래시론/시빌어택 등)별로 각 엔진이 어떤 탐지율을 보이는지 분석
- 히트맵, 막대 차트, 강점/약점 요약 제공

### 엔진 역할
| 엔진 | 역할 | 강점 | 약점 |
|------|------|------|------|
| **E1 (SequenceAnomaly)** | 피처 분포 기반 이상 탐지 | 미지 공격 탐지 | FP 높음 |
| **E2 (FlashLoanRule)** | 메서드 패턴 + 규칙 기반 | 알려진 공격 정확 탐지 | 신종 공격 미탐 |
| **E3 (HoustonLite)** | 금액 임계값 + 불변량 검사 | 대형 공격 확실 탐지 | 소액 분산 공격 취약 |
        """)
