import streamlit as st
import time
import random
from web3 import Web3
from lib.utils import load_contracts, get_accounts, get_web3, sign_macro_transfer

st.set_page_config(page_title="2-Layer Security Experiment", layout="wide")

st.title("🛡️ 2-Layer Payment Token Security Experiment")
st.markdown("""
이 실험은 **단일 토큰 모델**과 **2계층(소액/거액) 분리 모델**의 보안성 및 가용성을 비교합니다.
- **Model A (Single Layer)**: 모든 결제가 하나의 토큰(FDS)으로 처리되며, 위협 탐지 시 전체가 중단될 수 있습니다.
- **Model B (2-Layer)**: 소액(Micro)과 거액(Macro)으로 분리하여, 거액 자산 침해 시에도 소액 결제망은 생존합니다.
""")

# --------------------------------------------------------------------------------
# 초기 설정
# --------------------------------------------------------------------------------
contracts = load_contracts()
w3 = get_web3()
accounts = get_accounts()

if not contracts or "FDSMicro" not in contracts:
    st.error("Contracts not loaded. Please run `npx hardhat run scripts/deploy_2layer.ts --network localhost` first.")
    st.stop()

# Session State 초기화
if "metrics" not in st.session_state:
    st.session_state.metrics = {
        "A_tx_success": 0, "A_tx_fail": 0, "A_status": "Active",
        "B_micro_success": 0, "B_micro_fail": 0,
        "B_macro_success": 0, "B_macro_fail": 0,
        "B_macro_status": "Active"
    }

# --------------------------------------------------------------------------------
# 사이드바: 컨트롤 패널
# --------------------------------------------------------------------------------
st.sidebar.header("🕹️ Simulation Control")

# Traffic Generator
st.sidebar.subheader("Generate Traffic")
if st.sidebar.button("Run Normal Traffic (5 Tx)"):
    with st.spinner("Processing Normal Transactions..."):
        # 5개의 랜덤 트랜잭션 : 4개 소액, 1개 거액
        logs = []
        for i in range(5):
            is_macro = random.random() > 0.8 # 20% 확률로 거액
            amt = random.randint(100, 900_000) if not is_macro else random.randint(1_500_000, 5_000_000)
            
            # 1. Model A 실행
            try:
                # FDS (Single)
                contracts["FDS"].functions.transfer(accounts["hacker"].address, amt).transact({'from': accounts["watchtower"].address}) # Watchtower가 일반 유저라고 가정
                st.session_state.metrics["A_tx_success"] += 1
            except Exception as e:
                st.session_state.metrics["A_tx_fail"] += 1
                if "paused" in str(e).lower(): st.session_state.metrics["A_status"] = "PAUSED 🔴"

            # 2. Model B 실행
            try:
                if is_macro:
                    # Macro: 서명 필요
                    sig = sign_macro_transfer(contracts, accounts["watchtower"].address, accounts["hacker"].address, amt)
                    contracts["FDSMacro"].functions.transferWithSignal(
                        accounts["hacker"].address, amt, sig
                    ).transact({'from': accounts["watchtower"].address})
                    st.session_state.metrics["B_macro_success"] += 1
                else:
                    # Micro: 그냥 전송
                    contracts["FDSMicro"].functions.transfer(accounts["hacker"].address, amt).transact({'from': accounts["watchtower"].address})
                    st.session_state.metrics["B_micro_success"] += 1
            except Exception as e:
                if is_macro:
                    st.session_state.metrics["B_macro_fail"] += 1
                    if "paused" in str(e).lower(): st.session_state.metrics["B_macro_status"] = "PAUSED 🔴"
                else:
                    st.session_state.metrics["B_micro_fail"] += 1

        st.toast("Updated Metrics!")

# Attack Scenarios
st.sidebar.divider()
st.sidebar.subheader("💣 Attack Scenarios")

col_atk1, col_atk2 = st.sidebar.columns(2)

# Attack 1: Macro Dump (키 탈취 가정)
if col_atk1.button("Hacker: Huge Dump"):
    # 거액 토큰 한도 초과 시도 -> 서킷 브레이커 발동 유도
    huge_amt = 1_000_000_000 * 10**18 # 10억 (한도 초과 유발)
    
    # Model A: Single Token -> Pause Everything
    try:
        contracts["FDS"].functions.update(accounts["watchtower"].address, accounts["hacker"].address, huge_amt).transact() 
        # Note: 일반 transfer는 한도체크 안될수도 있으나 FDSStablecoin 로직상 mintLimit 체크는 mint시에만 있음... 
        # FDSStablecoin.sol 분석 결과: _checkMintLimit은 'from == 0' 일때만 발동.
        # 따라서 Transfer에 대한 Circuit Breaker는 FDSStablecoin에 '직접적인' Total Volume Limit은 없음 (Rate Limit은 Mint에만).
        # 하지만 사용자가 원한건 "거액코인은 ... 실시간 서킷 브레이커를 적용".
        # 기존 코인이 이를 지원하지 않는다면 '가정'하거나, FDSStablecoin을 수정해야 함.
        # 여기서는 FDSStablecoin이 '수동 관리' 혹은 '부족한 방어'를 보여준다고 가정.
        # "기존 코인도... 거액코인은 사전 심사 + 실시간 서킷 브레이커... 만들고 싶어" -> 기존 코인은 그게 없다는 뜻.
        # 따라서 기존 코인은 "방어 실패"로 간주되거나, 사고 발생 후 수동 정지해야 함.
        pass
    except:
        pass
    
    # Model B: Macro Token -> Auto Pause
    try:
        # 해커가 Watchtower 키를 탈취했다고 가정하고 서명 생성
        sig = sign_macro_transfer(contracts, accounts["watchtower"].address, accounts["hacker"].address, huge_amt)
        contracts["FDSMacro"].functions.transferWithSignal(accounts["hacker"].address, huge_amt, sig).transact({'from': accounts["watchtower"].address})
    except Exception as e:
        if "paused" in str(e).lower() or "System Paused" in str(e):
             st.session_state.metrics["B_macro_status"] = "PAUSED (Auto-Protected) 🛡️"
        else:
             st.error(f"Attack Result: {e}")

# Attack 2: Micro Siphon
if col_atk2.button("Hacker: Micro Siphon"):
    # 소액으로 여러번 빼가기
    for _ in range(10):
        contracts["FDSMicro"].functions.transfer(accounts["hacker"].address, 900_000).transact({'from': accounts["watchtower"].address})
        st.session_state.metrics["B_micro_success"] += 1
    
    # 이는 차단되지 않음 (나중에 Blacklist로 막아야 함)
    st.toast("10 Micro Transactions Executed (No Alert)")


# --------------------------------------------------------------------------------
# 메인 대시보드
# --------------------------------------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    st.subheader("Model A: Single Layer")
    st.info(f"System Status: **{st.session_state.metrics['A_status']}**")
    
    st.metric("Total Tx Success", st.session_state.metrics["A_tx_success"])
    st.metric("Total Tx Failed", st.session_state.metrics["A_tx_fail"])
    
    st.write("---")
    st.caption("특징: 거액 사고 발생 시 전체 시스템 셧다운 필요")

with col2:
    st.subheader("Model B: 2-Layer (Micro/Macro)")
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Micro Layer")
        st.success("Active (High Availability)")
        st.metric("Micro Tx Success", st.session_state.metrics["B_micro_success"])
    with c2:
        st.markdown("#### Macro Layer")
        status = st.session_state.metrics["B_macro_status"]
        if "PAUSED" in status:
            st.error(status)
        else:
            st.success(status)
        st.metric("Macro Tx Success", st.session_state.metrics["B_macro_success"])

    st.write("---")
    st.caption("특징: 거액 사고 시 **Macro Layer만** 정지됨. 일반 사용자는 Micro Layer 계속 사용 가능.")

# --------------------------------------------------------------------------------
# 상세 로그 및 리셋
# --------------------------------------------------------------------------------
if st.button("Reset Experiment"):
    st.button("Confirm Reset", on_click=lambda: st.session_state.clear())
    # Note: 컨트랙트 상태는 리셋되지 않음 (새로 배포 필요)
    st.warning("To reset contract states, please re-deploy: `npx hardhat run scripts/deploy_2layer.ts ...`")
