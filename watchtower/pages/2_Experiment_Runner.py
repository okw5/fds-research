import streamlit as st
import pandas as pd
import time
import random
from lib.utils import load_contracts, get_web3, send_defense_tx, get_accounts

st.set_page_config(page_title="실험 자동화 (Experiment Runner)", page_icon="🧪", layout="wide")
st.title("🧪 FDS 연구 실험 자동화 (2계층 vs 단일 토큰)")
st.markdown("""
이 도구는 **2계층 토큰 보안 모델**의 유효성을 검증하기 위해 공격 시뮬레이션을 자동화합니다.
실험설계 문서에 따라 3가지 공격 유형과 3가지 시스템 구성을 비교할 수 있습니다.
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
    st.header("⚙️ 실험 설정 (Experiment Configuration)")
    
    # ====================================
    # A. 모델 선택 (System Configuration)
    # ====================================
    st.info("**📊 1. 시스템 모델 선택**")
    system_model = st.selectbox(
        "비교 모델",
        [
            "수동 거버넌스 (Manual Governance)",
            "FDS 단일 토큰 (Single Layer)",
            "FDS 2계층 토큰 (Two Layer)"
        ],
        help="실험설계 문서의 3가지 시스템 구성 중 선택하세요."
    )
    
    with st.expander("💡 모델 설명"):
        st.markdown("""
        **수동 거버넌스**: 전통적 방식. 공격 발견 → 커뮤니티 투표 → 조치 (평균 45분 소요)
        
        **FDS 단일 토큰**: FDSStablecoin. 실시간 자동 탐지 및 전체 시스템 일시정지
        
        **FDS 2계층 토큰**: FDSMicro + FDSMacro. 차등 보안 및 선택적 차단으로 가용성 유지
        """)
    
    # ====================================
    # B. 공격 시나리오 선택
    # ====================================
    st.info("**🎯 2. 공격 시나리오 선택**")
    
    # 공격 타입
    attack_type = st.selectbox(
        "공격 유형",
        [
            "무한 발행 공격 (Infinite Minting)",
            "준비금 탈취 (Reserve Drain)",
            "플래시 론 공격 (Flash Loan Depeg)"
        ]
    )
    
    # 시나리오 (A, B, C)
    scenario = st.selectbox(
        "시나리오 복잡도",
        [
            "A - 단순 공격 (정상 네트워크)",
            "B - 분산 공격 (정상 네트워크)",
            "C - 극한 공격 (네트워크 혼잡)"
        ],
        help="A: 기본 공격, B: 임계값 우회 시도, C: 네트워크 혼잡 + 대량 공격"
    )
    
    scenario_key = scenario[0]  # 'A', 'B', 'C'
    
    # ====================================
    # C. 실험 파라미터 (자동 설정 + 수동 조정 가능)
    # ====================================
    st.info("**⚙️ 3. 실험 파라미터**")
    
    # 시나리오별 기본값 설정
    if attack_type == "무한 발행 공격 (Infinite Minting)":
        if scenario_key == 'A':
            default_attack = 50000
            default_threshold_single = 10000
            default_threshold_micro = 5000
            default_threshold_macro = 1000
            default_gas = 50
            network_desc = "정상 (50 Gwei)"
        elif scenario_key == 'B':
            default_attack = 8000  # 블록당
            default_threshold_single = 10000
            default_threshold_micro = 5000
            default_threshold_macro = 1000
            default_gas = 50
            network_desc = "정상 (50 Gwei)"
        else:  # C
            default_attack = 500000
            default_threshold_single = 10000
            default_threshold_micro = 5000
            default_threshold_macro = 1000
            default_gas = 300
            network_desc = "혼잡 (300 Gwei)"
            
    elif attack_type == "준비금 탈취 (Reserve Drain)":
        if scenario_key == 'A':
            default_attack = 1500  # ETH
            default_threshold_single = 10.0  # %
            default_threshold_micro = 10.0
            default_threshold_macro = 5.0
            default_gas = 50
            network_desc = "정상 (50 Gwei)"
        elif scenario_key == 'B':
            default_attack = 700  # 첫 블록
            default_threshold_single = 10.0
            default_threshold_micro = 10.0
            default_threshold_macro = 5.0
            default_gas = 50
            network_desc = "정상 (50 Gwei)"
        else:  # C
            default_attack = 5000
            default_threshold_single = 10.0
            default_threshold_micro = 10.0
            default_threshold_macro = 5.0
            default_gas = 400
            network_desc = "극심한 혼잡 (400 Gwei)"
            
    else:  # Flash Loan
        if scenario_key == 'A':
            default_attack = 10000000  # USDC
            default_threshold_single = 5.0  # %
            default_threshold_micro = 5.0
            default_threshold_macro = 3.0
            default_gas = 60
            network_desc = "정상 (60 Gwei)"
        elif scenario_key == 'B':
            default_attack = 50000000
            default_threshold_single = 5.0
            default_threshold_micro = 5.0
            default_threshold_macro = 3.0
            default_gas = 60
            network_desc = "정상 (60 Gwei)"
        else:  # C
            default_attack = 100000000
            default_threshold_single = 5.0
            default_threshold_micro = 5.0
            default_threshold_macro = 3.0
            default_gas = 500
            network_desc = "극심한 혼잡 (500 Gwei)"
    
    st.caption(f"🌐 네트워크 상태: {network_desc}")
    
    # 공격 규모
    attack_amount = st.number_input(
        f"공격 규모 ({'토큰' if 'Minting' in attack_type else 'ETH' if 'Drain' in attack_type else 'USDC'})",
        min_value=1000,
        value=default_attack,
        step=1000,
        help="실험설계 문서 시나리오에 맞춰 자동 설정됨. 수동 조정 가능."
    )
    
    # 탐지 임계값 (모델에 따라 다름)
    if "Minting" in attack_type:
        if "단일" in system_model:
            fds_threshold = st.number_input(
                "탐지 임계값 (토큰 수)",
                min_value=1000,
                value=default_threshold_single,
                step=1000
            )
        elif "2계층" in system_model:
            col_a, col_b = st.columns(2)
            with col_a:
                threshold_micro = st.number_input("Micro 임계값", value=default_threshold_micro, step=500)
            with col_b:
                threshold_macro = st.number_input("Macro 임계값", value=default_threshold_macro, step=100)
            fds_threshold = threshold_macro  # 더 strict한 값 사용
        else:
            fds_threshold = 999999999  # 수동 거버넌스는 실시간 탐지 없음
            
    elif "Drain" in attack_type:
        if "단일" in system_model:
            fds_threshold = st.number_input(
                "탐지 임계값 (%)",
                min_value=1.0,
                value=default_threshold_single,
                step=1.0
            )
        elif "2계층" in system_model:
            col_a, col_b = st.columns(2)
            with col_a:
                threshold_micro = st.number_input("Micro 임계값 (%)", value=default_threshold_micro, step=1.0)
            with col_b:
                threshold_macro = st.number_input("Macro 임계값 (%)", value=default_threshold_macro, step=1.0)
            fds_threshold = threshold_macro
        else:
            fds_threshold = 999999999
            
    else:  # Flash Loan
        if "단일" in system_model:
            fds_threshold = st.number_input(
                "가격 괴리 임계값 (%)",
                min_value=0.1,
                value=default_threshold_single,
                step=0.1
            )
        elif "2계층" in system_model:
            col_a, col_b = st.columns(2)
            with col_a:
                threshold_micro = st.number_input("Micro 괴리 (%)", value=default_threshold_micro, step=0.5)
            with col_b:
                threshold_macro = st.number_input("Macro 괴리 (%)", value=default_threshold_macro, step=0.5)
            fds_threshold = threshold_macro
        else:
            fds_threshold = 999999999
    
    # 네트워크 환경
    gas_price = st.slider(
        "Gas Price (Gwei)",
        min_value=10,
        max_value=600,
        value=default_gas,
        help="시나리오에 따라 자동 설정됨"
    )
    
    # ====================================
    # D. 실험 반복 설정
    # ====================================
    st.info("**🔄 4. 실험 반복 설정**")
    iterations = st.slider("반복 횟수", 1, 20, 5, help="통계적 신뢰도를 위해 여러 번 반복합니다.")
    
    # ====================================
    # E. 방어 조치
    # ====================================
    st.info("**🛡️ 5. 방어 조치**")
    
    if "수동" in system_model:
        st.warning("⚠️ 수동 거버넌스 모드: 자동 방어 없음 (150~400블록 지연)")
        defense_action = "Manual (No Auto-Defense)"
    elif "단일" in system_model:
        defense_action = st.selectbox(
            "탐지 시 실행할 방어",
            [
                "🚫 전체 시스템 일시정지 (System Pause)",
                "🧊 해커 지갑 동결 (Blacklist)"
            ]
        )
    else:  # 2계층
        defense_action = st.selectbox(
            "탐지 시 실행할 방어",
            [
                "🛡️ Macro 계층만 차단 (Selective Pause)",
                "🧊 해커 지갑 동결 (Blacklist)",
                "🚫 전체 시스템 일시정지 (Full Pause)"
            ]
        )

# --------------------------------------------------------------------------
# 2. Automation Logic
# --------------------------------------------------------------------------
def run_simulation(idx):
    """단일 실험 실행"""
    placeholder = st.empty()
    logs = []
    
    try:
        # Step 0: Initial State
        start_block = w3.eth.block_number
        sim_gas_price = w3.to_wei(gas_price, 'gwei')
        
        logs.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logs.append(f"🧪 반복 실험 #{idx}/{iterations}")
        logs.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logs.append(f"📊 모델: {system_model}")
        logs.append(f"🎯 시나리오: {attack_type} - {scenario}")
        logs.append(f"⏱️ 환경: Gas {gas_price} Gwei | Block #{start_block}")
        
        # 사용할 컨트랙트 선택
        if "2계층" in system_model:
            # TODO: 2계층 로직 구현 필요
            token_name = "FDSMacro"
            logs.append(f"🪙 사용 토큰: FDSMacro (거액 계층)")
            if "FDSMacro" not in contracts:
                logs.append("❌ FDSMacro 컨트랙트를 찾을 수 없습니다. deploy_all.ts 실행 필요")
                placeholder.code("\n".join(logs))
                return None
            target_contract = contracts["FDSMacro"]
        elif "단일" in system_model:
            token_name = "FDS"
            logs.append(f"🪙 사용 토큰: FDSStablecoin (단일 토큰)")
            target_contract = contracts["FDS"]
        else:  # 수동
            token_name = "FDS"
            logs.append(f"🪙 사용 토큰: FDSStablecoin (수동 거버넌스)")
            target_contract = contracts["FDS"]
        
        # 공격 정보
        if "Minting" in attack_type:
            logs.append(f"👾 해커 주소: {accs['hacker'].address}")
            logs.append(f"⚔️ 공격 시도: {attack_amount:,.0f} 토큰 발행")
            logs.append(f"🚨 탐지 임계값: {fds_threshold:,.0f} 토큰")
        elif "Drain" in attack_type:
            logs.append(f"🏦 타겟: Vault ({contracts['ADDRS']['Vault']})")
            logs.append(f"👾 해커 주소: {accs['hacker'].address}")
            logs.append(f"⚔️ 공격 시도: {attack_amount:,.0f} ETH 인출")
            logs.append(f"🚨 탐지 임계값: {fds_threshold:.1f}%")
        else:  # Flash Loan
            logs.append(f"📉 타겟: DEX ({contracts['ADDRS']['DEX']})")
            logs.append(f"👾 해커 주소: {accs['hacker'].address}")
            logs.append(f"⚔️ 공격 시도: {attack_amount:,.0f} USDC Flash Loan")
            logs.append(f"🚨 탐지 임계값: {fds_threshold:.1f}% 가격 괴리")
        
        placeholder.code("\n".join(logs))
        
        # Check Logic: Does this trigger FDS?
        triggered = False
        attack_amount_wei = w3.to_wei(attack_amount, 'ether')
        
        if "수동" in system_model:
            # 수동 거버넌스는 자동 탐지 없음
            triggered = False
            logs.append("⚠️ 수동 거버넌스: 자동 탐지 비활성화")
        elif "Minting" in attack_type:
            if attack_amount >= fds_threshold:
                triggered = True
                logs.append(f"✅ 탐지 조건 충족: {attack_amount:,.0f} >= {fds_threshold:,.0f}")
            else:
                logs.append(f"⚠️ 탐지 실패 (임계값 미달): {attack_amount:,.0f} < {fds_threshold:,.0f}")
                
        elif "Drain" in attack_type:
            vault_bal = contracts["USDT"].functions.balanceOf(contracts["ADDRS"]["Vault"]).call()
            vault_bal_float = float(w3.from_wei(vault_bal, 'ether'))
            if vault_bal_float > 0:
                drain_pct = (attack_amount / vault_bal_float) * 100
                logs.append(f"📊 Vault 잔액: {vault_bal_float:,.0f} USDT")
                logs.append(f"📊 예상 인출: {drain_pct:.2f}%")
                if drain_pct >= fds_threshold:
                    triggered = True
                    logs.append(f"✅ 탐지 조건 충족: {drain_pct:.2f}% >= {fds_threshold:.1f}%")
                else:
                    logs.append(f"⚠️ 탐지 실패: {drain_pct:.2f}% < {fds_threshold:.1f}%")
                    
        else:  # Flash Loan
            pool_size = 500000  # Initial FDS in pool
            impact_pct = (attack_amount / pool_size) * 100
            logs.append(f"📊 예상 가격 괴리: {impact_pct:.2f}%")
            if impact_pct >= fds_threshold:
                triggered = True
                logs.append(f"✅ 탐지 조건 충족: {impact_pct:.2f}% >= {fds_threshold:.1f}%")
            else:
                logs.append(f"⚠️ 탐지 실패: {impact_pct:.2f}% < {fds_threshold:.1f}%")
        
        placeholder.code("\n".join(logs))
        time.sleep(0.3)
        
        # ========================================
        # Step 1: 방어 트랜잭션 먼저 전송 (탐지된 경우)
        # ========================================
        defense_tx_hash = None
        defense_block = 999999999
        defense_gas = 0
        response_time = 0
        defense_success = False
        
        if triggered and "수동" not in system_model:
            logs.append("\n🚨 FDS 탐지! 방어 조치를 즉시 실행합니다...")
            logs.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            placeholder.code("\n".join(logs))
            
            defense_start_time = time.time()
            
            try:
                owner_acc = w3.eth.accounts[0]
                high_priority_gas = int(sim_gas_price * 2.0)  # 2배 Gas로 우선 처리
                
                if "Blacklist" in defense_action or "동결" in defense_action:
                    # Blacklist 공격자
                    if "2계층" in system_model and "FDSMacro" in contracts:
                        # FDSMacro에는 blacklistAccount가 없으므로 emergencyPause 사용
                        defense_func = contracts["FDSMacro"].functions.emergencyPause()
                        action_desc = "Macro 계층 일시정지 (blacklist 미지원)"
                    else:
                        # FDSStablecoin은 blacklistAccount 지원
                        defense_func = target_contract.functions.blacklistAccount(accs['hacker'].address)
                        action_desc = "해커 지갑 동결"
                    
                    tx = defense_func.build_transaction({
                        'from': owner_acc,
                        'nonce': w3.eth.get_transaction_count(owner_acc),
                        'gasPrice': high_priority_gas
                    })
                    defense_tx_hash = w3.eth.send_transaction(tx)
                    logs.append(f"   🛡️ 방어 TX 전송: {defense_tx_hash.hex()}")
                    logs.append(f"   💰 Gas Price: {high_priority_gas/1e9:.1f} Gwei (우선순위 높음)")
                    logs.append(f"   🎯 조치: {action_desc}")
                    
                elif "Selective" in defense_action or "계층만" in defense_action:
                    # 2계층: Macro만 일시정지
                    if "FDSMacro" in contracts:
                        defense_func = contracts["FDSMacro"].functions.emergencyPause()
                        tx = defense_func.build_transaction({
                            'from': owner_acc,
                            'nonce': w3.eth.get_transaction_count(owner_acc),
                            'gasPrice': high_priority_gas
                        })
                        defense_tx_hash = w3.eth.send_transaction(tx)
                        logs.append(f"   🛡️ 방어 TX 전송: {defense_tx_hash.hex()}")
                        logs.append(f"   💰 Gas Price: {high_priority_gas/1e9:.1f} Gwei")
                        logs.append(f"   🎯 조치: Macro 계층만 일시정지 (Micro는 정상 작동)")
                    
                else:
                    # System Pause - 컨트랙트별 함수명이 다름!
                    if "2계층" in system_model and "FDSMacro" in contracts:
                        # FDSMacro 사용
                        defense_func = contracts["FDSMacro"].functions.emergencyPause()
                    else:
                        # FDSStablecoin 사용
                        defense_func = target_contract.functions.circuitBreakerTrigger()
                    
                    tx = defense_func.build_transaction({
                        'from': owner_acc,
                        'nonce': w3.eth.get_transaction_count(owner_acc),
                        'gasPrice': high_priority_gas
                    })
                    defense_tx_hash = w3.eth.send_transaction(tx)
                    logs.append(f"   🛡️ 방어 TX 전송: {defense_tx_hash.hex()}")
                    logs.append(f"   💰 Gas Price: {high_priority_gas/1e9:.1f} Gwei")
                    logs.append(f"   🎯 조치: 전체 시스템 일시정지")
                
                # 방어 트랜잭션 확인 대기
                defense_receipt = w3.eth.wait_for_transaction_receipt(defense_tx_hash, timeout=120)
                defense_block = defense_receipt['blockNumber']
                defense_gas = defense_receipt['gasUsed']
                defense_success = (defense_receipt['status'] == 1)
                response_time = time.time() - defense_start_time
                
                if defense_success:
                    logs.append(f"   ✅ 방어 성공! Block #{defense_block}, TxIndex: {defense_receipt['transactionIndex']}")
                else:
                    logs.append(f"   ❌ 방어 트랜잭션 실패! (Reverted)")
                
                placeholder.code("\n".join(logs))
                time.sleep(0.2)
                
            except Exception as e:
                logs.append(f"   ❌ 방어 트랜잭션 오류: {str(e)}")
                placeholder.code("\n".join(logs))
        
        # ========================================
        # Step 2: 공격 트랜잭션 전송 (방어 후)
        # ========================================
        logs.append("\n⚔️ 공격 트랜잭션 실행 중...")
        logs.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        placeholder.code("\n".join(logs))
        
        attack_tx_hash = None
        attack_start_time = time.time()
        attack_error = None
        
        try:
            if "Minting" in attack_type:
                tx = target_contract.functions.exploitMint(attack_amount_wei).build_transaction({
                    'from': accs['hacker'].address,
                    'nonce': w3.eth.get_transaction_count(accs['hacker'].address),
                    'gasPrice': sim_gas_price
                })
                signed_tx = w3.eth.account.sign_transaction(tx, accs['hacker'].key)
                attack_tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                logs.append(f"   ⚔️ 공격 TX 전송: {attack_tx_hash.hex()}")
                logs.append(f"   💰 Gas Price: {sim_gas_price/1e9:.1f} Gwei")
                
            elif "Drain" in attack_type:
                tx = contracts["Vault"].functions.exploitDrain(attack_amount_wei).build_transaction({
                    'from': accs['hacker'].address,
                    'nonce': w3.eth.get_transaction_count(accs['hacker'].address),
                    'gasPrice': sim_gas_price
                })
                signed_tx = w3.eth.account.sign_transaction(tx, accs['hacker'].key)
                attack_tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                logs.append(f"   ⚔️ 공격 TX 전송: {attack_tx_hash.hex()}")
                logs.append(f"   💰 Gas Price: {sim_gas_price/1e9:.1f} Gwei")
                
            else:  # Flash Loan
                # Flash Loan 시뮬레이션
                deployer_acc = w3.eth.accounts[0]
                
                # 1. Borrow funds
                funding_tx = contracts["FDS"].functions.transfer(
                    accs['hacker'].address, 
                    attack_amount_wei
                ).build_transaction({
                    'from': deployer_acc,
                    'nonce': w3.eth.get_transaction_count(deployer_acc),
                    'gasPrice': sim_gas_price
                })
                w3.eth.send_transaction(funding_tx)
                time.sleep(0.1)
                
                # 2. Dump attack
                hacker_nonce = w3.eth.get_transaction_count(accs['hacker'].address)
                tx = contracts["DEX"].functions.simulateDump(attack_amount_wei).build_transaction({
                    'from': accs['hacker'].address,
                    'nonce': hacker_nonce,
                    'gasPrice': sim_gas_price
                })
                signed_tx = w3.eth.account.sign_transaction(tx, accs['hacker'].key)
                attack_tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                logs.append(f"   ⚔️ 공격 TX 전송: {attack_tx_hash.hex()}")
                logs.append(f"   💰 Gas Price: {sim_gas_price/1e9:.1f} Gwei")
                
                # 3. Repay
                repay_tx = contracts["FDS"].functions.transfer(
                    deployer_acc, 
                    attack_amount_wei
                ).build_transaction({
                    'from': accs['hacker'].address,
                    'nonce': hacker_nonce + 1,
                    'gasPrice': sim_gas_price
                })
                signed_repay = w3.eth.account.sign_transaction(repay_tx, accs['hacker'].key)
                w3.eth.send_raw_transaction(signed_repay.raw_transaction)
            
            placeholder.code("\n".join(logs))
            
        except Exception as e:
            attack_error = str(e)
            logs.append(f"   ❌ 공격 트랜잭션 전송 실패: {attack_error}")
            placeholder.code("\n".join(logs))
            
            # On-chain backstop 또는 방어에 의한 차단
            if "Rate limit" in attack_error or "Paused" in attack_error or "blacklist" in attack_error.lower():
                logs.append("   🛡️ 컨트랙트 레벨에서 차단됨! (On-chain Protection)")
                placeholder.code("\n".join(logs))
                
                # 시스템 복구
                try:
                    owner = w3.eth.accounts[0]
                    if "2계층" in system_model and "FDSMacro" in contracts:
                        contracts["FDSMacro"].functions.resumeService().transact({'from': owner})
                    else:
                        target_contract.functions.resumeService().transact({'from': owner})
                except:
                    pass
                
                return {
                    "Iteration": idx,
                    "Model": system_model,
                    "Scenario": scenario,
                    "Type": attack_type,
                    "AttackAmt": attack_amount,
                    "Threshold": fds_threshold,
                    "Triggered": triggered,
                    "Success": True,
                    "ResponseTime": response_time,
                    "BlockDiff": 0,
                    "DefenseGas": defense_gas,
                    "Status": "✅ 방어 성공 (트랜잭션 차단됨)"
                }
            return None
        
        # ========================================
        # Step 3: 트랜잭션 결과 확인 및 분석
        # ========================================
        attack_receipt = None
        attack_block = 999999999
        attack_success = False
        
        if attack_tx_hash:
            try:
                attack_receipt = w3.eth.wait_for_transaction_receipt(attack_tx_hash, timeout=120)
                attack_block = attack_receipt['blockNumber']
                attack_success = (attack_receipt['status'] == 1)
                
                logs.append(f"\n   📊 공격 결과:")
                logs.append(f"      - Block: #{attack_block}")
                logs.append(f"      - TxIndex: {attack_receipt['transactionIndex']}")
                logs.append(f"      - Status: {'✅ 성공 (exploited!)' if attack_success else '❌ 실패 (reverted)'}")
                logs.append(f"      - Gas Used: {attack_receipt['gasUsed']:,}")
                
            except Exception as e:
                logs.append(f"   ⚠️ 공격 트랜잭션 확인 실패: {str(e)}")
                attack_success = False
        
        placeholder.code("\n".join(logs))
        
        # ========================================
        # Step 4: 결과 분석 및 판정
        # ========================================
        success = False
        status_msg = ""
        
        logs.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logs.append("📊 실험 결과 분석")
        logs.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        if "수동" in system_model:
            # 수동 거버넌스: 항상 실패 (지연)
            simulated_response_blocks = random.randint(150, 400)  # 실험설계 문서 참조
            status_msg = f"❌ 방어 실패 (수동 거버넌스: ~{simulated_response_blocks}블록 지연)"
            success = False
            response_time = simulated_response_blocks * 12  # 초 단위
            logs.append(f"   - 수동 거버넌스: 커뮤니티 투표 대기 중...")
            logs.append(f"   - 예상 대응 시간: {simulated_response_blocks}블록 ({response_time/60:.1f}분)")
            
        elif not triggered:
            # 탐지 안됨
            if attack_success:
                status_msg = "❌ 미탐지 (임계값 미달) → 공격 성공"
                success = False
                logs.append(f"   ⚠️ FDS 탐지 실패: 공격량이 임계값 미달")
                logs.append(f"   ❌ 공격 성공: 해커가 {attack_amount:,.0f} 탈취")
            else:
                status_msg = "⚠️ 미탐지했지만 On-chain Backstop이 차단"
                success = True
                logs.append(f"   ⚠️ FDS 탐지 실패: 공격량이 임계값 미달")
                logs.append(f"   ✅ 하지만 On-chain Backstop이 차단!")
                
        else:
            # FDS가 탐지함
            logs.append(f"   ✅ FDS 탐지 성공!")
            
            # 방어 트랜잭션이 전송되었는지 확인
            if defense_tx_hash and defense_success:
                logs.append(f"   ✅ 방어 트랜잭션 성공: Block #{defense_block}")
                
                # 공격 트랜잭션 결과 확인
                if not attack_success:
                    # 공격이 Revert됨 = 방어 성공
                    status_msg = "✅ 방어 성공 (공격 트랜잭션 차단됨)"
                    success = True
                    logs.append(f"   ✅ 공격 차단: 트랜잭션이 Revert됨")
                    
                elif defense_block < attack_block:
                    # 방어가 더 빠른 블록에 포함됨
                    status_msg = "✅ 방어 성공 (Front-run: 방어가 먼저 실행)"
                    success = True
                    logs.append(f"   ✅ 방어가 먼저 실행됨: Block #{defense_block} < #{attack_block}")
                    
                elif defense_block == attack_block:
                    # 같은 블록에 포함됨
                    defense_idx = defense_receipt['transactionIndex']
                    attack_idx = attack_receipt['transactionIndex']
                    
                    if defense_idx < attack_idx:
                        status_msg = "✅ 방어 성공 (같은 블록, 방어 우선 실행)"
                        success = True
                        logs.append(f"   ✅ 같은 블록 내 방어 우선: TxIndex {defense_idx} < {attack_idx}")
                    else:
                        status_msg = "❌ 방어 실패 (같은 블록, 공격 먼저 실행)"
                        success = False
                        logs.append(f"   ❌ 같은 블록 내 공격 우선: TxIndex {attack_idx} < {defense_idx}")
                else:
                    # 방어가 늦음
                    status_msg = "❌ 방어 실패 (방어 트랜잭션 지연)"
                    success = False
                    logs.append(f"   ❌ 방어 지연: Block #{defense_block} > #{attack_block}")
                    logs.append(f"   ❌ 공격 성공: 해커가 먼저 실행함")
                    
            elif defense_tx_hash and not defense_success:
                # 방어 트랜잭션이 실패함
                status_msg = "❌ 방어 실패 (방어 트랜잭션 Revert)"
                success = False
                logs.append(f"   ❌ 방어 트랜잭션이 Revert됨")
                
            else:
                # 방어 트랜잭션을 전송하지 못함
                if not attack_success:
                    status_msg = "✅ On-chain Backstop이 차단 (방어 TX 없음)"
                    success = True
                    logs.append(f"   ⚠️ 방어 트랜잭션 없음")
                    logs.append(f"   ✅ On-chain Backstop이 공격 차단")
                else:
                    status_msg = "❌ 방어 실패 (방어 TX 전송 실패)"
                    success = False
                    logs.append(f"   ❌ 방어 트랜잭션 전송 실패")
                    logs.append(f"   ❌ 공격 성공")
        
        # 최종 요약
        logs.append("")
        logs.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logs.append("📋 최종 결과")
        logs.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        if defense_tx_hash:
            logs.append(f"🛡️ 방어 TX: {defense_tx_hash.hex()}")
            logs.append(f"   - Block: #{defense_block}, Gas: {defense_gas:,}")
        else:
            logs.append(f"🛡️ 방어 TX: 없음")
            
        if attack_tx_hash:
            logs.append(f"⚔️ 공격 TX: {attack_tx_hash.hex()}")
            logs.append(f"   - Block: #{attack_block}")
            logs.append(f"   - 결과: {'성공 (해킹됨!)' if attack_success else '실패 (차단됨)'}")
        else:
            logs.append(f"⚔️ 공격 TX: 전송 실패")
        
        logs.append("")
        logs.append(f"⏱️ 대응 시간: {response_time:.2f}초")
        logs.append(f"📊 블록 차이: {(defense_block - attack_block) if defense_tx_hash and attack_tx_hash else 'N/A'}")
        logs.append("")
        logs.append(f"🏆 {status_msg}")
        
        placeholder.code("\n".join(logs))
        
        # 시스템 복구
        try:
            owner = w3.eth.accounts[0]
            if "2계층" in system_model and "FDSMacro" in contracts:
                contracts["FDSMacro"].functions.resumeService().transact({'from': owner})
            else:
                target_contract.functions.resumeService().transact({'from': owner})
        except:
            pass
        
        return {
            "Iteration": idx,
            "Model": system_model,
            "Scenario": scenario,
            "Type": attack_type,
            "AttackAmt": attack_amount,
            "Threshold": fds_threshold,
            "Triggered": triggered,
            "Success": success,
            "AttackSuccess": attack_success,
            "DefenseSuccess": defense_success if defense_tx_hash else False,
            "ResponseTime": response_time,
            "BlockDiff": (defense_block - attack_block) if (defense_tx_hash and attack_tx_hash and defense_block != 999999999 and attack_block != 999999999) else None,
            "DefenseGas": defense_gas,
            "Status": status_msg
        }
        
    except Exception as e:
        placeholder.error(f"실험 오류: {str(e)}")
        return None

# --------------------------------------------------------------------------
# 3. Main Control
# --------------------------------------------------------------------------

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("🚀 실험 제어")
    st.markdown("""
    실험설계 문서의 시나리오를 자동으로 실행합니다.
    - 각 시나리오는 10회 반복 권장 (통계적 신뢰도)
    - 결과는 실시간으로 업데이트됩니다
    """)
    
    if st.button("▶️ 실험 시작", type="primary", use_container_width=True):
        st.session_state.exp_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i in range(iterations):
            status_text.text(f"🧪 실험 진행 중... {i+1}/{iterations}")
            with st.container(border=True):
                st.write(f"**반복 #{i+1}**")
                res = run_simulation(i+1)
                if res:
                    st.session_state.exp_results.append(res)
            progress_bar.progress((i + 1) / iterations)
            time.sleep(0.5)

        status_text.text("✅ 실험 완료!")
        st.success("모든 실험이 종료되었습니다.")

with col2:
    st.subheader("📊 실험 결과 및 통계")
    
    if st.session_state.exp_results:
        df = pd.DataFrame(st.session_state.exp_results)
        
        with st.expander("ℹ️ 결과 지표 해석", expanded=False):
            st.markdown("""
            **Triggered**: FDS 탐지 여부 (공격량이 임계값 초과)
            
            **Success**: 방어 성공 여부 (공격 차단 성공)
            
            **ResponseTime**: 탐지 후 방어까지 걸린 시간 (초)
            
            **BlockDiff**: 방어 블록 - 공격 블록 (음수면 Front-run 성공)
            """)
        
        # 핵심 지표
        total = len(df)
        triggered_cnt = df["Triggered"].sum()
        success_cnt = df["Success"].sum()
        attack_blocked = (~df["AttackSuccess"]).sum()  # 공격 차단된 수
        avg_response = df["ResponseTime"].mean() if len(df) > 0 else 0
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🎯 실험 횟수", f"{total}회")
        m2.metric("🚨 탐지율", f"{(triggered_cnt/total)*100:.1f}%", f"{triggered_cnt}/{total}")
        m3.metric("✅ 방어 성공률", f"{(success_cnt/total)*100:.1f}%", f"{success_cnt}/{total}")
        m4.metric("🛡️ 공격 차단율", f"{(attack_blocked/total)*100:.1f}%", f"{attack_blocked}/{total}")
        
        st.metric("⏱️ 평균 대응시간", f"{avg_response:.2f}초")
        
        # 상세 결과 테이블
        st.markdown("### 📋 상세 실험 결과")
        
        # 테이블 표시용 데이터 준비
        display_df = df[[
            "Iteration", "Model", "Scenario", "Type", 
            "AttackAmt", "Triggered", "DefenseSuccess", "AttackSuccess", 
            "Success", "ResponseTime", "Status"
        ]].copy()
        
        # 컬럼명 한글화
        display_df.columns = [
            "반복", "모델", "시나리오", "공격유형",
            "공격규모", "탐지", "방어성공", "공격성공",
            "최종방어", "대응시간(초)", "상태"
        ]
        
        # 스타일링 함수
        def highlight_results(row):
            if row['공격성공']:
                return ['background-color: #5c1a1a'] * len(row)  # 빨강: 공격 성공 (나쁨)
            elif row['최종방어']:
                return ['background-color: #1a472a'] * len(row)  # 초록: 방어 성공 (좋음)
            else:
                return ['background-color: #3a3a1a'] * len(row)  # 노랑: 애매한 경우
        
        st.dataframe(
            display_df.style.apply(highlight_results, axis=1),
            use_container_width=True,
            height=400
        )
        
        # 추가 통계
        st.markdown("### 📈 성능 분석")
        col_a, col_b = st.columns(2)
        
        with col_a:
            st.markdown("**탐지 vs 미탐지**")
            detect_stats = pd.DataFrame({
                '구분': ['탐지됨', '미탐지'],
                '횟수': [triggered_cnt, total - triggered_cnt]
            })
            st.bar_chart(detect_stats.set_index('구분'))
        
        with col_b:
            st.markdown("**방어 결과**")
            result_stats = pd.DataFrame({
                '구분': ['방어 성공', '방어 실패'],
                '횟수': [success_cnt, total - success_cnt]
            })
            st.bar_chart(result_stats.set_index('구분'))
        
        # CSV 다운로드
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 결과 다운로드 (CSV)",
            data=csv,
            file_name=f"fds_experiment_{system_model.split()[0]}_{scenario_key}.csv",
            mime="text/csv",
            use_container_width=True
        )
        
    else:
        st.info("🔬 실험을 시작하면 여기에 결과가 표시됩니다.")
        st.markdown("""
        **실험 가이드**:
        1. 왼쪽 사이드바에서 모델과 시나리오 선택
        2. 파라미터는 실험설계 문서에 맞춰 자동 설정됨
        3. '실험 시작' 버튼 클릭
        4. 결과를 CSV로 다운로드하여 분석
        """)
