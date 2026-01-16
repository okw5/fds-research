import streamlit as st
import pandas as pd
import time
import random
from lib.utils import load_contracts, get_web3, send_defense_tx, get_accounts

st.set_page_config(page_title="실험 자동화 (Experiment Runner)", page_icon="🧪", layout="wide")
st.title("🧪 실험 자동화 및 몬테카를로 시뮬레이션")
st.markdown("""
이 도구는 **하이브리드 FDS**의 견고성을 검증하기 위해 공격 시뮬레이션을 자동화합니다.
FDS의 탐지 정책(Threshold)과 공격자의 행동 패턴을 변경해가며 다양한 시나리오를 테스트할 수 있습니다.
""")

w3 = get_web3()
contracts = load_contracts()
accs = get_accounts()

if "exp_results" not in st.session_state:
    st.session_state.exp_results = []

# --------------------------------------------------------------------------
# 1. Experiment Configuration
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 실험 설정 (Settings)")
    
    # A. Scenarios
    st.info("**1. 시나리오 선택**")
    exp_type = st.selectbox("공격 유형", ["Infinite Mint", "Vault Drain", "Flash Loan Depeg"])
    
    # B. FDS Rules (Detection)
    st.info("**2. FDS 탐지 정책 (Rules)**")
    fds_threshold = 0.0
    
    if exp_type == "Infinite Mint":
        fds_threshold = st.number_input("발행량 임계값 (Mint Threshold)", min_value=1000, value=50000, step=1000, help="이 값 이상의 토큰이 한 번에 발행되면 차단합니다.")
    elif exp_type == "Vault Drain":
        fds_threshold = st.number_input("인출 비율 임계값 (Drain %)", min_value=1.0, value=10.0, step=1.0, help="Vault 잔고의 n% 이상이 한 번에 빠져나가면 차단합니다.")
    else:
        fds_threshold = st.number_input("가격 괴리 임계값 (Spread %)", min_value=0.1, value=5.0, step=0.1, help="오라클 가격 대비 DEX 가격 괴리가 n% 이상이면 차단합니다.")

    # C. Attacker Profile
    st.info("**3. 공격자 프로필 (Attacker)**")
    attack_range = st.slider(
        f"공격 규모 범위 ({'FDS' if exp_type == 'Infinite Mint' else '$'})", 
        min_value=10000, max_value=1000000, value=(40000, 150000), 
        help="공격자가 시도할 공격 물량의 최소~최대 범위입니다. 임계값보다 작게 공격하여 탐지를 회피할 수도 있습니다."
    )
    
    st.divider()
    
    # D. Environment
    st.info("**4. 네트워크 환경 (Env)**")
    iterations = st.slider("반복 횟수 (Iterations)", 1, 50, 5)
    gas_volatility = st.slider("가스비 변동성 (%)", 0, 100, 20)
    delay_range = st.slider("지연 시간 (Latency ms)", 0, 2000, (100, 500))

    # E. Actions
    st.info("**5. 대응 조치 (Action)**")
    defense_action = st.selectbox(
        "탐지 시 실행할 방어 로직", 
        ["🚫 FDS 코인 전체 일시정지 (System Pause)", 
         "🧊 해커 지갑 동결 (Wallet Freeze)", 
         "🏦 준비금 컨트랙트 보호 (Vault Safe Mode)"]
    )
    
    with st.expander("💡 더 나은 방어 전략 제안 (Ideas)"):
        st.markdown("""
        **1. 동적 수수료 (Dynamic Fee)**: 의심스러운 거래에 대해 수수료를 100%로 인상하여 공격 비용을 극대화합니다.
        **2. 허니팟 (Honeypot)**: 공격 자금을 차단하지 않고, 별도의 화이트햇 금고로 리다이렉트시킵니다.
        **3. 플래시론 역추적**: 플래시론을 이용한 공격 감지 시, 대출 상환을 강제로 실패하게 하여 공격을 원천 무효화합니다.
        """)


# --------------------------------------------------------------------------
# 2. Automation Logic
# --------------------------------------------------------------------------
def run_simulation(idx):
    placeholder = st.empty()
    logs = []
    
    try:
        # Step 0: Initial State
        start_block = w3.eth.block_number
        base_fee = w3.eth.gas_price
        
        # Randomize Environment
        random_gas_mult = 1 + (random.uniform(-gas_volatility, gas_volatility) / 100)
        sim_gas_price = int(base_fee * random_gas_mult)
        sim_delay = random.uniform(delay_range[0], delay_range[1]) / 1000.0
        
        logs.append(f"⏱️ [Iter {idx}] 환경: Gas {sim_gas_price/1e9:.2f} Gwei | Latency {sim_delay*1000:.0f}ms")

        # Scenario Details Logging
        if exp_type == "Infinite Mint":
            logs.append(f"🎯 타겟 코인: FDS ({contracts['ADDRS']['FDS']})")
            logs.append(f"👾 해커 주소: {accs['hacker'].address}") # Infinite Mint also implies hacker action
        elif exp_type == "Vault Drain":
            logs.append(f"🏦 준비금 컨트랙트: Vault ({contracts['ADDRS']['Vault']})")
            logs.append(f"👾 해커 주소: {accs['hacker'].address}")
        elif exp_type == "Flash Loan Depeg":
            logs.append(f"📉 DEX 컨트랙트: {contracts['ADDRS']['DEX']}")
            logs.append(f"👾 해커 주소: {accs['hacker'].address}")
        
        # Generate Attack Amount
        attack_amount_float = random.uniform(attack_range[0], attack_range[1])
        attack_amount_wei = w3.to_wei(attack_amount_float, 'ether')
        logs.append(f"⚔️ 공격 시도: {attack_amount_float:,.0f} (Rule: {fds_threshold:,.1f})")
        
        placeholder.code("\n".join(logs))

        # Check Logic: Does this trigger FDS?
        triggered = False
        if exp_type == "Infinite Mint":
            if attack_amount_float >= fds_threshold: triggered = True
        elif exp_type == "Vault Drain":
            # Need to know current vault balance to calculate %? 
            # For sim simplicity, assume Vault has 1,000,000 USDT (initial state)
            # Or fetch real state? Real state is better.
            vault_bal = contracts["USDT"].functions.balanceOf(contracts["ADDRS"]["Vault"]).call()
            vault_bal_float = float(w3.from_wei(vault_bal, 'ether'))
            if vault_bal_float > 0:
                drain_pct = (attack_amount_float / vault_bal_float) * 100
                if drain_pct >= fds_threshold: triggered = True
                logs.append(f"   - 예상 인출: {drain_pct:.2f}% (Limit: {fds_threshold}%)")
            
        elif exp_type == "Flash Loan Depeg":
            # Approximating spread impact is complex without executing.
            # Simple assumption: 100k dump causes ~5% slippage in 500k pool.
            # Impact ~= (Amount / PoolSize) * 100 ??
            # Let's use linear approx for simulation controls
            pool_size = 500000 # Initial FDS
            impact_pct = (attack_amount_float / pool_size) * 100
            if impact_pct >= fds_threshold: triggered = True
            logs.append(f"   - 예상 괴리: {impact_pct:.2f}% (Limit: {fds_threshold}%)")

        # Step 1: Execute Attack (Simulated latency)
        time.sleep(sim_delay)
        
        attack_tx_hash = None
        
        # Send Attack TX
        if exp_type == "Infinite Mint":
            tx = contracts["FDS"].functions.exploitMint(attack_amount_wei).build_transaction({
                'from': accs['hacker'].address, 'nonce': w3.eth.get_transaction_count(accs['hacker'].address), 'gasPrice': sim_gas_price
            })
            signed_tx = w3.eth.account.sign_transaction(tx, accs['hacker'].key)
            attack_tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        elif exp_type == "Vault Drain":
             tx = contracts["Vault"].functions.exploitDrain(attack_amount_wei).build_transaction({
                'from': accs['hacker'].address, 'nonce': w3.eth.get_transaction_count(accs['hacker'].address), 'gasPrice': sim_gas_price
            })
             signed_tx = w3.eth.account.sign_transaction(tx, accs['hacker'].key)
             attack_tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
             
        elif exp_type == "Flash Loan Depeg":
             # Fix: Flash Loan should NOT mint new tokens (keeps supply constant).
             # Instead, we "Borrow" from a liquidity provider (Deployer/Account0) and "Repay".
             deployer_acc = w3.eth.accounts[0]
             
             # 1. Borrow (Transfer from Deployer -> Hacker)
             # Note: logic assumes Deployer has enough funds (starts with 500k+).
             funding_tx = contracts["FDS"].functions.transfer(accs['hacker'].address, attack_amount_wei).build_transaction({
                 'from': deployer_acc,
                 'nonce': w3.eth.get_transaction_count(deployer_acc),
                 'gasPrice': sim_gas_price
             })
             w3.eth.send_transaction(funding_tx) # Account 0 is unlocked
             time.sleep(0.1) # Wait for propagation
             
             # Prepare Nonce
             hacker_nonce = w3.eth.get_transaction_count(accs['hacker'].address)

             # 2. Dump (Attack)
             tx = contracts["DEX"].functions.simulateDump(attack_amount_wei).build_transaction({
                'from': accs['hacker'].address, 
                'nonce': hacker_nonce,
                'gasPrice': sim_gas_price
             })
             signed_tx = w3.eth.account.sign_transaction(tx, accs['hacker'].key)
             attack_tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
             
             # 3. Repay (Return funds to Deployer to simulate Flash Loan atomicity)
             repay_tx = contracts["FDS"].functions.transfer(deployer_acc, attack_amount_wei).build_transaction({
                 'from': accs['hacker'].address,
                 'nonce': hacker_nonce + 1,
                 'gasPrice': sim_gas_price
             })
             signed_repay = w3.eth.account.sign_transaction(repay_tx, accs['hacker'].key)
             w3.eth.send_raw_transaction(signed_repay.raw_transaction)

        # Step 2: Defense Logic
        receipt = None
        defense_latency = 0
        defense_block = 999999999 # Default high
        defense_gas = 0
        
        if triggered:

            logs.append(f"🚨 탐지 성공! 대응 조치 실행: **{defense_action.split('(')[0].strip()}**")
            
            # Logic Branch based on Action
            # Note: In this prototype, FDSStablecoin only supports 'System Pause'. 
            # Other actions will simulate the effect or fall back to System Pause with a log note.
            
            if "Wallet Freeze" in defense_action:
                logs.append("   👉 해커 지갑(Blacklist) 동결 트랜잭션 실행 중...")
                
                # Execute Blacklist Transaction (as Owner)
                try:
                    owner_acc = w3.eth.accounts[0]
                    # We use Owner only for this specific action in simulation 
                    # (In production, Watchtower might need a specific delegated function like pauseByWatchtower)
                    defense_func = contracts["FDS"].functions.blacklistAccount(accs['hacker'].address)
                    tx = defense_func.build_transaction({
                        'from': owner_acc,
                        'nonce': w3.eth.get_transaction_count(owner_acc),
                        'gasPrice': int(w3.eth.gas_price * 1.5)
                    })
                    # In Hardhat node, we can send from unlocked accounts directly or sign if we have PK.
                    # Assuming Hardhat Node #0 is unlocked:
                    tx_hash = w3.eth.send_transaction(tx)
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                    defense_latency = 0.5 # Simulating processing time
                    defense_block = receipt['blockNumber']
                    defense_gas = receipt['gasUsed']
                    
                    logs.append("   ✅ 해커 지갑 동결 완료 (Blacklisted)")
                    
                except Exception as e:
                    logs.append(f"   ❌ 동결 실패: {e}")
                    # Fallback to Pause if blacklist fails?
                    receipt, defense_latency = send_defense_tx(contracts, f"Auto-Defense (Fallback): {defense_action}")
                    defense_block = receipt['blockNumber']
                    defense_gas = receipt['gasUsed']

            elif "Vault Safe Mode" in defense_action:
                logs.append("   👉 (Simulated) Vault 인출 제한 모드 전환 중...")
                logs.append("   ⚠️ 현재 Vault는 Pausable 미지원 -> FDS System Pause로 대체 실행")
                # Still fallback to Pause for Vault
                receipt, defense_latency = send_defense_tx(contracts, f"Auto-Defense: {defense_action}")
                defense_block = receipt['blockNumber']
                defense_gas = receipt['gasUsed']
            else:
                # System Pause (Default)
                receipt, defense_latency = send_defense_tx(contracts, f"Auto-Defense: {defense_action}")
                defense_block = receipt['blockNumber']
                defense_gas = receipt['gasUsed']
        else:
             logs.append("⚠️ 탐지 실패 (임계값 미달) - 방어 건너뜀")
        
        # Wait for Attack Confirmation
        attack_receipt = w3.eth.wait_for_transaction_receipt(attack_tx_hash)
        attack_block = attack_receipt['blockNumber']
        
        # Step 3: Result Analysis
        success = False
        status_msg = ""
        
        if not triggered:
            status_msg = "❌ 미탐지 (Threshold Underrun)"
            if attack_receipt['status'] == 1:
                status_msg += " - 공격 성공함"
            else:
                 # Check if reverted by Rate Limit
                 status_msg += " - 공격 실패 (Revert됨: On-chain Backstop)"
                 # This counts as a form of success for the SYSTEM, but maybe not the Watchtower FRONT-RUNNING.
                 # Let's mark it as partial success or distinct category.
                 success = True # System protected
        else:
            if defense_block < attack_block:
                status_msg = "✅ 방어 성공 (Front-run)"
                success = True
            elif defense_block == attack_block:
                if receipt['transactionIndex'] < attack_receipt['transactionIndex']:
                    status_msg = "✅ 방어 성공 (우선순위 승리)"
                    success = True
                else:
                    status_msg = "❌ 방어 실패 (우선순위 패배)"
            else:
                 # Even if Watchtower was late, did the On-chain Backstop catch it?
                 if attack_receipt['status'] == 0:
                     status_msg = "✅ 방어 성공 (Watchtower 지연됐으나 On-chain Backstop이 차단)"
                     success = True
                 else:
                    status_msg = "❌ 방어 실패 (지연됨)"

        logs.append(f"⚔️ 공격 블록: {attack_block} | 🛡️ 방어 블록: {defense_block if triggered else 'N/A'}")
        logs.append(f"결과: {status_msg}")
        placeholder.code("\n".join(logs))
        
        # Resume System
        owner = w3.eth.accounts[0]
        try:
            contracts["FDS"].functions.resumeService().transact({'from': owner})
        except:
            pass
        
        return {
            "Iteration": idx,
            "Type": exp_type,
            "AttackAmt": attack_amount_float,
            "Threshold": fds_threshold,
            "Triggered": triggered,
            "Success": success,
            "BlockDiff": (defense_block - attack_block) if triggered else None,
            "DefenseCost_Gas": defense_gas,
            "Status": status_msg
        }

    except Exception as e:
        error_str = str(e)
        if "Rate limit exceeded" in error_str or "System Paused" in error_str:
            # This is an On-chain Backstop trigger!
            logs.append("🛡️ On-chain Backstop 발동! (Rate Limit Exceeded)")
            logs.append("결과: ✅ 방어 성공 (스마트 컨트랙트 자동 차단)")
            placeholder.code("\n".join(logs))
            
            # Resume needed? Yes, system is paused.
            time.sleep(1)
            owner = w3.eth.accounts[0]
            try:
                contracts["FDS"].functions.resumeService().transact({'from': owner})
            except:
                pass

            return {
                "Iteration": idx,
                "Type": exp_type,
                "AttackAmt": -1, # Unknown or from context
                "Threshold": fds_threshold,
                "Triggered": True, # Backstop triggered
                "Success": True,
                "BlockDiff": 0,
                "DefenseCost_Gas": 0, # No watchtower gas used
                "Status": "✅ 방어 성공 (On-chain Backstop)"
            }
        else:
            placeholder.error(f"Error: {e}")
            return None

# --------------------------------------------------------------------------
# 3. Main Control
# --------------------------------------------------------------------------

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("🚀 실험 제어")
    st.markdown("버튼을 클릭하여 몬테카를로 시뮬레이션을 시작하세요.")
    
    if st.button("▶️ 시뮬레이션 시작", type="primary"):
        st.session_state.exp_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i in range(iterations):
            status_text.text(f"실험 진행 중... 반복 {i+1}/{iterations}")
            with st.container(border=True):
                st.write(f"**반복(Iter) #{i+1}**")
                res = run_simulation(i+1)
                if res:
                    st.session_state.exp_results.append(res)
            progress_bar.progress((i + 1) / iterations)
            time.sleep(0.5)

        status_text.text("✅ 시뮬레이션 완료!")
        st.success("모든 실험이 종료되었습니다.")

with col2:
    st.subheader("📊 실험 결과 및 해석")
    
    if st.session_state.exp_results:
        df = pd.DataFrame(st.session_state.exp_results)
        
        with st.expander("ℹ️ 결과 지표 해석 방법 (가이드)", expanded=False):
            st.markdown("""
            - **Triggered (탐지 여부)**: 공격량이 설정된 Threshold를 넘어서 방어가 시도되었는지 여부.
            - **Success Rate (성공률)**: 방어가 시도된 건 중 실제 차단에 성공한 비율.
            - **미탐지(False Negative)**: 공격량이 적어 FDS가 무시했지만, 실제로는 공격이 수행된 경우.
            """)
        
        total = len(df)
        triggered_cnt = df["Triggered"].sum()
        success = df["Success"].sum()
        
        m1, m2, m3 = st.columns(3)
        m1.metric("🛡️ 탐지율 (Trigger Rate)", f"{(triggered_cnt/total)*100:.1f}%", f"{triggered_cnt}/{total} 건")
        m2.metric("✅ 방어 성공률 (Success)", f"{(success/max(1, triggered_cnt))*100:.1f}%", help="탐지된 공격 중 성공적으로 막은 비율")
        
        if df["DefenseCost_Gas"].sum() > 0:
            avg_gas = df[df["Triggered"]]["DefenseCost_Gas"].mean()
            m3.metric("⛽ 평균 가스 비용", f"{avg_gas:,.0f}")
        else:
            m3.metric("⛽ 평균 가스 비용", "0")
        
        st.dataframe(df.style.map(lambda x: "color: orange" if x == False else "color: white", subset=['Triggered']), use_container_width=True)
    else:
        st.info("실험 결과를 기다리는 중입니다...")

