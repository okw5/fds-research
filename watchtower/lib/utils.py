import streamlit as st
import json
import os
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
import time

# --------------------------------------------------------------------------
# 상수 및 설정
# --------------------------------------------------------------------------
RPC_URL = "http://127.0.0.1:8545"
WATCHTOWER_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d" # Account #1
HACKER_PK = "0xdf57089febbacf7ba0bc227dafbffa9fc08a93fdc68e1e42411a14efcf23656e"     # Account #19

# --------------------------------------------------------------------------
# Singleton Web3 연결
# --------------------------------------------------------------------------
@st.cache_resource
def get_web3():
    return Web3(Web3.HTTPProvider(RPC_URL))

# --------------------------------------------------------------------------
# 리소스 로드 (주소/ABI)
# --------------------------------------------------------------------------
@st.cache_resource
def load_contracts():
    w3 = get_web3()
    
    # 루트 디렉토리 찾기 (watchtower/lib/.. -> watchtower/.. -> root)
    # 현재 실행 위치가 root라고 가정 (streamlit run watchtower/app.py)
    # 하지만 import 위치에 따라 다를 수 있으므로 절대 경로 사용 권장
    # 여기서는 간단히 상대경로 시도 후 실패시 절대경로 처리 등 로직이 필요하나
    # 사용자 환경(fds-research)에 맞춰 하드코딩된 경로 사용 가능
    
    base_path = "."
    address_path = os.path.join(base_path, "watchtower", "addresses.json")
    if not os.path.exists(address_path):
         # 만약 streamlit을 watchtower 폴더 안에서 실행했다면
         address_path = "addresses.json"
         base_path = "."
    else:
         base_path = "watchtower"

    try:
        with open(os.path.join(base_path, "addresses.json")) as f:
            addrs = json.load(f)
        
        abis = {}
        with open(os.path.join(base_path, "FDSStablecoin.json")) as f: abis["FDS"] = json.load(f)["abi"]
        with open(os.path.join(base_path, "MockVault.json")) as f: abis["Vault"] = json.load(f)["abi"]
        with open(os.path.join(base_path, "MockDEX.json")) as f: abis["DEX"] = json.load(f)["abi"]
        
        abis["Oracle"] = [{"inputs":[],"name":"getLatestPrice","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
        abis["USDT"] = [
            {"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"balanceOf","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
            {"inputs":[],"name":"totalSupply","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
        ]
        
        contracts = {
            "FDS": w3.eth.contract(address=addrs["FDS"], abi=abis["FDS"]),
            "Vault": w3.eth.contract(address=addrs["Vault"], abi=abis["Vault"]),
            "DEX": w3.eth.contract(address=addrs["DEX"], abi=abis["DEX"]),
            "Oracle": w3.eth.contract(address=addrs["Oracle"], abi=abis["Oracle"]),
            "USDT": w3.eth.contract(address=addrs["USDT"], abi=abis["USDT"]),
            "ADDRS": addrs,
            "ABIS": abis
        }
        return contracts
    except Exception as e:
        st.error(f"Failed to load contracts: {e}")
        return None

# --------------------------------------------------------------------------
# 계정 객체
# --------------------------------------------------------------------------
def get_accounts():
    return {
        "watchtower": Account.from_key(WATCHTOWER_PK),
        "hacker": Account.from_key(HACKER_PK)
    }

# --------------------------------------------------------------------------
# 방어 트랜잭션 공통 함수
# --------------------------------------------------------------------------
def send_defense_tx(contracts, reason="EMERGENCY"):
    w3 = get_web3()
    accs = get_accounts()
    fds = contracts["FDS"]
    
    start_time = time.time()
    nonce_val = fds.functions.nonces(accs["watchtower"].address).call()
    chain_id = w3.eth.chain_id
    
    # 메시지 서명
    message_hash = w3.solidity_keccak(
        ['string', 'uint256', 'address', 'uint256'],
        ["EMERGENCY_PAUSE", chain_id, contracts["ADDRS"]["FDS"], nonce_val]
    )
    message = encode_defunct(hexstr=message_hash.hex())
    signed_message = w3.eth.account.sign_message(message, private_key=WATCHTOWER_PK)
    
    # TX 전송
    func_call = fds.functions.pauseByWatchtower(signed_message.signature).build_transaction({
        'from': accs["watchtower"].address,
        'nonce': w3.eth.get_transaction_count(accs["watchtower"].address),
        'gas': 300000,
        'gasPrice': int(w3.eth.gas_price * 1.5) # 가스비 증액 (Front-running 시도)
    })
    
    signed_tx = w3.eth.account.sign_transaction(func_call, private_key=WATCHTOWER_PK)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    return receipt, time.time() - start_time
