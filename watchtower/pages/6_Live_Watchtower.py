"""
6_Live_Watchtower.py — 실시간 Watchtower 데모 페이지

3개 탐지 엔진 파이프라인 시각화:
  - 공격 시나리오 선택 → 엔진 분석 → 앙상블 집계 → 대응 시각화
  - 각 엔진의 결과를 실시간으로 표시
  - ThreatSignal JSON 출력
  - On-chain 자동 방어 실행 (Hardhat 연결 시)
"""

import streamlit as st
import time
import json
import pandas as pd

# ── 엔진 임포트 ──
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.engines.base import ThreatLevel, ThreatSignal
from lib.engines.sequence_anomaly import SequenceAnomalyEngine
from lib.engines.flash_loan_rule import FlashLoanRuleEngine
from lib.engines.houston_lite import HoustonLiteInvariantChecker
from lib.engines.aggregator import ThreatAggregator

# ── 페이지 설정 ──
st.set_page_config(page_title="Live Watchtower Demo", layout="wide", page_icon="🔭")

st.title("🔭 Live Watchtower — Multi-Engine Detection Demo")
st.caption(
    "3개 이종 탐지 엔진 (BERT4ETH·FlashGuard·HOUSTON 참조) + "
    "ThreatAggregator 앙상블 → On-chain Circuit Breaker 연동"
)

# ══════════════════════════════════════════════════════════════════════════
# Session State 초기화
# ══════════════════════════════════════════════════════════════════════════
if "wt_engines" not in st.session_state:
    st.session_state.wt_engines = {
        "seq": SequenceAnomalyEngine(),
        "flash": FlashLoanRuleEngine(),
        "houston": HoustonLiteInvariantChecker(),
    }
    st.session_state.wt_aggregator = ThreatAggregator()
    st.session_state.wt_history = []

engines = st.session_state.wt_engines
aggregator = st.session_state.wt_aggregator

# ══════════════════════════════════════════════════════════════════════════
# 사이드바: 엔진 정보 + 가중치 조정
# ══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ Engine Configuration")

    st.subheader("Engine Weights")
    w1 = st.slider("Engine 1 (Sequence) [PLACEHOLDER]", 0.0, 1.0, 0.20, 0.05)
    w2 = st.slider("Engine 2 (FlashLoan) [LITE]", 0.0, 1.0, 0.45, 0.05)
    w3 = st.slider("Engine 3 (Invariant) [LITE]", 0.0, 1.0, 0.35, 0.05)

    aggregator.update_weights({
        "SequenceAnomalyEngine": w1,
        "FlashLoanRuleEngine": w2,
        "HoustonLiteInvariantChecker": w3,
    })

    st.divider()
    st.subheader("Action Thresholds")
    t_pause = st.slider("Pause Threshold", 0.0, 1.0, 0.65, 0.05)
    t_blacklist = st.slider("Blacklist Threshold", 0.0, 1.0, 0.45, 0.05)
    aggregator.update_thresholds({
        "pause_macro": t_pause,
        "blacklist_address": t_blacklist,
    })

    st.divider()
    st.subheader("📋 Engine Info")
    for key, engine in engines.items():
        info = engine.get_engine_info()
        tag = "🟡 PLACEHOLDER" if info["status"] == "placeholder" else "🟢 LITE"
        with st.expander(f"{tag} {info['name']}"):
            st.write(f"**Reference:** {info['reference']}")
            st.write(f"**Status:** {info['status']}")
            st.caption(info.get("description", ""))

# ══════════════════════════════════════════════════════════════════════════
# 메인: 시나리오 선택 + 분석
# ══════════════════════════════════════════════════════════════════════════

SCENARIOS = {
    "T1: 정상 소액 이체": {
        "from": "0xUser1234...abcd", "to": "0xReceiver...ef01",
        "amount": 500, "type": "transfer",
        "call_sequence": ["transfer"],
        "state_before": {"total_supply": 1_000_000, "initial_supply": 1_000_000,
                         "reserve": 500_000, "price": 1.0, "mint_limit": 500_000},
        "state_after": {"total_supply": 1_000_000, "reserve": 500_000,
                        "price": 1.0, "period_mint_amount": 0},
    },
    "T2: 대량 정상 유동성 공급": {
        "from": "0xLiqProvider...1234", "to": "0xDEXPool...5678",
        "amount": 50_000, "type": "liquidity_add",
        "call_sequence": ["approve", "addLiquidity"],
        "state_before": {"total_supply": 1_000_000, "initial_supply": 1_000_000,
                         "reserve": 500_000, "price": 1.0, "mint_limit": 500_000},
        "state_after": {"total_supply": 1_000_000, "reserve": 550_000,
                        "price": 1.0, "period_mint_amount": 0},
    },
    "T3: 🔴 대량 무한 민트 공격": {
        "from": "0xAttacker...dead", "to": "0xAttacker...dead",
        "amount": 5_000_000, "type": "exploit_mint",
        "call_sequence": ["mint", "mint", "transfer"],
        "state_before": {"total_supply": 1_000_000, "initial_supply": 1_000_000,
                         "reserve": 500_000, "price": 1.0, "mint_limit": 500_000},
        "state_after": {"total_supply": 6_000_000, "reserve": 500_000,
                        "price": 0.6, "period_mint_amount": 5_000_000},
    },
    "T4: 🔴 Flash Loan 공격": {
        "from": "0xAttacker...beef", "to": "0xDeFiProtocol...cafe",
        "amount": 10_000_000, "type": "flash_loan",
        "call_sequence": ["flashLoan", "swap", "manipulate", "repay"],
        "state_before": {"total_supply": 1_000_000, "initial_supply": 1_000_000,
                         "reserve": 500_000, "price": 1.0, "mint_limit": 500_000},
        "state_after": {"total_supply": 1_000_000, "reserve": 100_000,
                        "price": 0.3, "period_mint_amount": 0},
    },
    "T5: 🟡 점진적 증가 공격": {
        "from": "0xSneaky...1111", "to": "0xSneaky...2222",
        "amount": 16_000, "type": "transfer",
        "call_sequence": ["transfer"],
        "state_before": {"total_supply": 1_000_000, "initial_supply": 1_000_000,
                         "reserve": 500_000, "price": 1.0, "mint_limit": 500_000},
        "state_after": {"total_supply": 1_000_000, "reserve": 484_000,
                        "price": 0.98, "period_mint_amount": 0},
    },
    "T6: 🔴 Reentrancy 공격": {
        "from": "0xReentrant...aaaa", "to": "0xVulnerable...bbbb",
        "amount": 200_000, "type": "exploit",
        "call_sequence": ["withdraw", "fallback", "withdraw"],
        "state_before": {"total_supply": 1_000_000, "initial_supply": 1_000_000,
                         "reserve": 500_000, "price": 1.0, "mint_limit": 500_000},
        "state_after": {"total_supply": 1_000_000, "reserve": 300_000,
                        "price": 0.85, "period_mint_amount": 0},
    },
    "T7: 🔴 Reserve Drain 공격": {
        "from": "0xDrainer...cccc", "to": "0xDrainer...dddd",
        "amount": 400_000, "type": "drain",
        "call_sequence": ["approve", "transferFrom"],
        "state_before": {"total_supply": 1_000_000, "initial_supply": 1_000_000,
                         "reserve": 500_000, "price": 1.0, "mint_limit": 500_000},
        "state_after": {"total_supply": 1_000_000, "reserve": 50_000,
                        "price": 0.7, "period_mint_amount": 0},
    },
}

st.subheader("📋 Scenario Selection")
selected = st.selectbox("시나리오 선택", list(SCENARIOS.keys()))
tx_data = SCENARIOS[selected]

# TX 데이터 미리보기
with st.expander("📦 Transaction Data", expanded=False):
    st.json(tx_data)

# ── 분석 실행 ──
if st.button("🔍 Run Detection Pipeline", type="primary", use_container_width=True):

    # 이력 쌓기 (엔진1용)
    if "정상" in selected or "유동성" in selected:
        for _ in range(5):
            engines["seq"].analyze({"from": tx_data["from"], "amount": 500, "type": "transfer"})

    pipeline_start = time.time()

    # 1) 3개 엔진 분석
    results = []
    for engine in [engines["seq"], engines["flash"], engines["houston"]]:
        r = engine.analyze(tx_data)
        results.append(r)

    # 2) 집계
    signal = aggregator.aggregate(results, tx_data)
    pipeline_ms = (time.time() - pipeline_start) * 1000

    # 이력 저장
    entry = signal.to_dict()
    entry["scenario"] = selected
    entry["pipeline_latency_ms"] = round(pipeline_ms, 2)
    st.session_state.wt_history.append(entry)

    # ── 시각화 ──
    st.divider()
    st.subheader("📊 Detection Results")

    # 상단: 최종 판정
    score = signal.final_score
    action = signal.recommended_action

    if score >= 0.65:
        st.error(f"🚨 **THREAT DETECTED** — Score: {score:.3f} — Action: `{action}`")
    elif score >= 0.35:
        st.warning(f"⚠️ **SUSPICIOUS** — Score: {score:.3f} — Action: `{action}`")
    else:
        st.success(f"✅ **NORMAL** — Score: {score:.3f} — Action: `{action}`")

    # 엔진별 결과
    cols = st.columns(3)
    threat_colors = {
        "none": "🟢", "low": "🔵", "medium": "🟡", "high": "🟠", "critical": "🔴"
    }

    for i, (result, col) in enumerate(zip(results, cols)):
        info = [engines["seq"], engines["flash"], engines["houston"]][i].get_engine_info()
        tag = "[PLACEHOLDER]" if info["status"] == "placeholder" else "[LITE]"

        with col:
            icon = threat_colors.get(result.threat_level.value, "⚪")
            st.markdown(f"### {icon} Engine {i+1} {tag}")
            st.caption(info["reference"])

            st.metric("Threat Level", result.threat_level.value.upper())
            st.metric("Confidence", f"{result.confidence:.1%}")
            st.metric("Latency", f"{result.latency_ms:.2f} ms")

            with st.expander("Details"):
                st.json(result.details)

    # 앙상블 시각화
    st.divider()
    col_agg, col_json = st.columns([1, 1])

    with col_agg:
        st.subheader("🎯 Aggregation Breakdown")
        df_data = []
        for r in results:
            w = aggregator.weights.get(r.engine_name, 0.33)
            from lib.engines.base import THREAT_LEVEL_SCORES
            level_score = THREAT_LEVEL_SCORES[r.threat_level]
            weighted = level_score * r.confidence * w
            df_data.append({
                "Engine": r.engine_name.replace("Engine", ""),
                "Level": r.threat_level.value,
                "Confidence": f"{r.confidence:.2f}",
                "Weight": f"{w:.2f}",
                "Weighted Score": f"{weighted:.4f}",
            })
        st.dataframe(pd.DataFrame(df_data), use_container_width=True, hide_index=True)

        st.metric("Final Score", f"{score:.4f}")
        st.metric("Pipeline Latency", f"{pipeline_ms:.2f} ms")

    with col_json:
        st.subheader("📄 ThreatSignal JSON")
        st.json(signal.to_dict())

# ══════════════════════════════════════════════════════════════════════════
# 하단: 이력 테이블
# ══════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("📜 Detection History")

if st.session_state.wt_history:
    hist_df = pd.DataFrame([
        {
            "Scenario": h["scenario"],
            "Threat": h["threat_level"],
            "Score": h["final_score"],
            "Action": h["recommended_action"],
            "Latency (ms)": h.get("pipeline_latency_ms", 0),
            "Time": time.strftime("%H:%M:%S", time.localtime(h["timestamp"])),
        }
        for h in reversed(st.session_state.wt_history[-20:])
    ])
    st.dataframe(hist_df, use_container_width=True, hide_index=True)

    if st.button("🗑️ Clear History"):
        st.session_state.wt_history.clear()
        st.rerun()
else:
    st.info("아직 분석 이력이 없습니다. 위에서 시나리오를 선택하고 Detection Pipeline을 실행하세요.")

# ── 푸터: 엔진 통계 ──
with st.expander("📊 Engine Statistics"):
    stats = []
    for engine in [engines["seq"], engines["flash"], engines["houston"]]:
        s = engine.get_stats()
        s["status"] = "PLACEHOLDER" if s["is_placeholder"] else "LITE"
        stats.append(s)
    st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)
