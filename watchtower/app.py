import streamlit as st
import pandas as pd
import time
import json
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct

# --------------------------------------------------------------------------
# 1. 설정 및 연결 (Configuration)
# --------------------------------------------------------------------------
st.set_page_config(page_title="FDS Watchtower Dashboard", layout="wide")

# Hardhat 로컬 네트워크 연결
RPC_URL = "http://127.0.0.1:8545"
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# 계정 설정 (Hardhat 기본 계정)
# Account 0: Deployer (Owner)
# Account 1: Watchtower (우리가 지정한 감시자)
# Account 19: Hacker (공격자 시뮬레이션용)
WATCHTOWER_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d" # Hardhat Account #1
HACKER_PK = "0xdf57089febbacf7ba0bc227dafbffa9fc08a93fdc68e1e42411a14efcf23656e" # Hardhat Account #19

watchtower_acc = Account.from_key(WATCHTOWER_PK)
hacker_acc = Account.from_key(HACKER_PK)

# 컨트랙트 정보 로드 (복사해온 json 파일 필요)
try:
    with open("FDSStablecoin.json") as f:
        contract_json = json.load(f)
        ABI = contract_json["abi"]
except FileNotFoundError:
    st.error("❌ 'FDSStablecoin.json' 파일을 찾을 수 없습니다. artifacts 폴더에서 복사해오세요.")
    st.stop()

# --------------------------------------------------------------------------
# 2. 사이드바 컨트롤 (Parameters)
# --------------------------------------------------------------------------
st.sidebar.title("🛡️ FDS Control Panel")

# [입력] 컨트랙트 주소 (배포 후 터미널에 뜬 주소를 여기에 입력하세요)
contract_address = st.sidebar.text_input(
    "Contract Address", 
    value="0xa45583B27beAc8a0091A25588e64a0f49De6D61e" # 아까 배포된 주소 (다르면 수정 필요)
)

if not w3.is_connected():
    st.sidebar.error("❌ Blockchain Disconnected")
    st.stop()
else:
    st.sidebar.success("✅ Blockchain Connected")

contract = w3.eth.contract(address=contract_address, abi=ABI)

# 시뮬레이션 파라미터
st.sidebar.header("Detection Parameters")
threshold = st.sidebar.slider("이상 거래 임계값 (FDS Tokens)", 10, 1000, 100)
auto_defense = st.sidebar.checkbox("자동 방어 모드 (Auto Defense)", value=True)

# --------------------------------------------------------------------------
# 3. 함수 정의 (Logic)
# --------------------------------------------------------------------------

def get_balance(address):
    """지갑의 FDS 토큰 잔액 조회"""
    try:
        raw = contract.functions.balanceOf(address).call()
        return w3.from_wei(raw, 'ether')
    except:
        return 0

def check_pause_status():
    """현재 시스템이 멈췄는지 확인"""
    return contract.functions.paused().call()

def send_defense_tx(nonce_val):
    """서명 생성 및 차단 트랜잭션 전송"""
    start_time = time.time()
    
    # 1. 서명 생성 (ECDSA) - Raw Bytes 방식
    chain_id = w3.eth.chain_id
    message_hash = w3.solidity_keccak(
        ['string', 'uint256', 'address', 'uint256'],
        ["EMERGENCY_PAUSE", chain_id, contract_address, nonce_val]
    )
    # EIP-191 표준 메시지 헤더 추가
    message = encode_defunct(hexstr=message_hash.hex())
    
    # 서명 객체 자체를 받습니다.
    signed_message = w3.eth.account.sign_message(message, private_key=WATCHTOWER_PK)
    
    # .signature 속성은 바로 'bytes' 타입입니다. (hex 변환 X)
    signature_bytes = signed_message.signature
    
    # 2. 트랜잭션 구성
    func_call = contract.functions.pauseByWatchtower(signature_bytes).build_transaction({
        'from': watchtower_acc.address,
        'nonce': w3.eth.get_transaction_count(watchtower_acc.address),
        'gas': 200000,
        'gasPrice': w3.eth.gas_price
    })
    
    # 3. 서명 및 전송
    signed_tx = w3.eth.account.sign_transaction(func_call, private_key=WATCHTOWER_PK)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    # 4. 블록 포함 대기
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    end_time = time.time()
    
    return receipt, end_time - start_time
    
# --------------------------------------------------------------------------
# 4. 메인 화면 구성 (UI)
# --------------------------------------------------------------------------
st.title("FDS Research Dashboard 📊")

# 상태 표시줄
col1, col2, col3 = st.columns(3) 
is_paused = check_pause_status()
col1.metric("Block Height", w3.eth.block_number)
col2.metric("System Status", "🔴 PAUSED (Danger)" if is_paused else "🟢 NORMAL (Safe)")
col3.metric("Detect Threshold", f"{threshold} FDS")

# 데이터 저장소 (Session State)
if 'history' not in st.session_state:
    st.session_state.history = pd.DataFrame(columns=['Time', 'Hacker Balance'])
if 'latency_log' not in st.session_state:
    st.session_state.latency_log = []


# -----------------------------------------------------------
# [추가됨] 시스템 복구 버튼 (Admin Only)
# -----------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Admin Controls")

if st.sidebar.button("🟢 시스템 정상화 (Resume Service)"):
    if not is_paused:
        st.sidebar.warning("이미 정상 상태입니다.")
    else:
        try:
            # Owner(Account 0) 권한으로 resumeService 호출
            # Hardhat 로컬 노드에서는 accounts[0]이 자동으로 Unlock 되어 있어 바로 전송 가능
            owner_addr = w3.eth.accounts[0]
            
            tx_hash = contract.functions.resumeService().transact({
                'from': owner_addr,
                'gas': 200000
            })
            hacker_balance_wei = contract.functions.balanceOf(hacker_acc.address).call()
            if hacker_balance_wei > 0:
                    # 해커가 스스로 돈을 뱉어내게 만듭니다 (web3 unlocked account 활용)
                    # 실제 메인넷에선 불가능하지만, 로컬 포크 환경이라 가능합니다.
                    refund_tx = contract.functions.transfer(owner_addr, hacker_balance_wei).transact({
                        'from': hacker_acc.address, # 해커 지갑에서
                        'gas': 200000
                    })
                    w3.eth.wait_for_transaction_receipt(refund_tx)
                    st.toast("🧹 Hacker's funds have been confiscated!", icon="💸")   
            # 블록 처리 대기
            w3.eth.wait_for_transaction_receipt(tx_hash)
            
            st.sidebar.success("✅ 시스템이 정상화되었습니다!")
            time.sleep(1)
            st.rerun() # 화면 새로고침
            
        except Exception as e:
            st.sidebar.error(f"복구 실패: {str(e)}")




# --------------------------------------------------------------------------
# 5. 공격 시뮬레이션 버튼
# --------------------------------------------------------------------------
st.markdown("---")
st.subheader("⚔️ Attack Simulation")
if st.button("Simulate Attack (Transfer 500 FDS to Hacker)"):
    try:
        # Owner -> Hacker 500 전송 시도
        # (주의: 실제로는 Owner 지갑이 잠겨있지 않아야 함. 여기선 Hardhat 기본 Owner 사용)
        owner_addr = w3.eth.accounts[0] # Hardhat 0번 계정
        
        # UI 상에서는 Owner의 서명을 흉내낼 수 없으므로,
        # 편의상 '개발자 모드'로 간주하고 web3의 unlocked account 기능 사용
        # (로컬 포크 환경이므로 가능)
        tx_hash = contract.functions.transfer(hacker_acc.address, w3.to_wei(500, 'ether')).transact({
            'from': owner_addr
        })
        st.success(f"Attack Transaction Sent! Hash: {tx_hash.hex()[:10]}...")
    except Exception as e:
        st.error(f"Attack Failed: {str(e)}")

# --------------------------------------------------------------------------
# 6. 실시간 모니터링 루프 (Watchtower Logic)
# --------------------------------------------------------------------------
placeholder = st.empty()

# 해커 잔고 확인
hacker_bal = get_balance(hacker_acc.address)

# [핵심] FDS 탐지 로직
if not is_paused and hacker_bal >= threshold:
    st.toast(f"🚨 ANOMALY DETECTED! Hacker Balance: {hacker_bal} FDS", icon="⚠️")
    
    if auto_defense:
        # 서킷 브레이커 발동
        nonce = contract.functions.nonces(watchtower_acc.address).call()
        try:
            receipt, latency = send_defense_tx(nonce)
            st.session_state.latency_log.append({
                'Block': receipt['blockNumber'],
                'Latency (sec)': latency,
                'Type': 'Auto-Defense'
            })
            st.success(f"✅ Threat Neutralized! Latency: {latency:.4f}s")
            st.rerun() # 상태 업데이트를 위해 새로고침
        except Exception as e:
            st.error(f"Defense Failed: {e}")

# 차트 업데이트
new_row = pd.DataFrame({'Time': [pd.Timestamp.now()], 'Hacker Balance': [float(hacker_bal)]})
st.session_state.history = pd.concat([st.session_state.history, new_row], ignore_index=True)

# 화면 그리기
with placeholder.container():
    # 1. 잔고 그래프
    st.subheader("📈 Real-time Hacker Balance")
    st.line_chart(st.session_state.history.set_index('Time'))
    
    # 2. 반응 속도 로그
    if st.session_state.latency_log:
        st.subheader("⚡ Defense Latency Log")
        st.dataframe(pd.DataFrame(st.session_state.latency_log))

# 자동 새로고침 (Polling)
time.sleep(1) 
st.rerun()
