import streamlit as st
import pandas as pd
import time
from lib.utils import load_contracts, get_web3

st.set_page_config(page_title="Block Explorer", page_icon="🔍", layout="wide")
st.title("🔍 Block Analysis & Explorer")

w3 = get_web3()
contracts = load_contracts()

if not contracts:
    st.stop()

# --------------------------------------------------------------------------
# 1. Latest Blocks Visualization
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 1. Latest Blocks Visualization (Real-time)
# --------------------------------------------------------------------------
st.subheader("⛓️ 실시간 블록 생성 현황 (Live Blocks)")

# CSS for Block Cards & Animation
st.markdown("""
<style>
@keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0.4); }
    70% { box-shadow: 0 0 0 10px rgba(255, 75, 75, 0); }
    100% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0); }
}
.block-card {
    background-color: #262730;
    padding: 15px;
    border-radius: 10px;
    border: 1px solid #444;
    text-align: center;
    transition: all 0.3s ease;
}
.block-card:hover {
    transform: translateY(-5px);
    border-color: #ff4b4b;
}
.latest-block {
    border-color: #ff4b4b;
    animation: pulse 2s infinite;
}
</style>
""", unsafe_allow_html=True)

# Auto-refresh Control
col_ctrl, col_status = st.columns([3, 7])
with col_ctrl:
    # Toggle for real-time updates
    is_live = st.toggle("🔴 실시간 감시 (Live Mode)", value=st.session_state.get("auto_refresh", False))
    st.session_state["auto_refresh"] = is_live

with col_status:
    if st.button("🔄 즉시 새로고침"):
        st.rerun()

latest_block_num = w3.eth.block_number
block_data = []

# Fetch last 5 blocks
for i in range(latest_block_num, max(0, latest_block_num - 5), -1):
    blk = w3.eth.get_block(i, full_transactions=True)
    tx_hashes = [tx['hash'].hex() for tx in blk['transactions']]
    
    block_data.append({
        "Height": blk['number'],
        "Timestamp": pd.to_datetime(blk['timestamp'], unit='s'),
        "GasUsed": f"{blk['gasUsed']:,}",
        "TX Count": len(blk['transactions']),
        "TXs": tx_hashes,
        "IsLatest": (i == latest_block_num)
    })

# 1-A. Visual Stack (Horizontal Cards)
st.markdown("##### 🧱 최근 생성된 블록 (Latest 5 Blocks)")
cols = st.columns(5)

for idx, b in enumerate(block_data):
    if idx < 5:
        with cols[idx]:
            # Apply 'latest-block' class to the first item
            css_class = "block-card latest-block" if b['IsLatest'] else "block-card"
            
            st.markdown(f"""
            <div class="{css_class}">
                <div style="font-size: 1.2rem; font-weight: bold; color: #fff;">#{b['Height']}</div>
                <div style="font-size: 0.8rem; color: #aaa; margin-bottom: 8px;">{b['Timestamp'].strftime('%H:%M:%S')}</div>
                <div style="background-color: #333; border-radius: 5px; padding: 4px; margin-bottom: 4px;">
                    <span style="color: #ff4b4b; font-weight: bold;">{b['TX Count']}</span> <span style="font-size: 0.8rem;">TXs</span>
                </div>
                <div style="font-size: 0.7rem; color: #888;">Gas: {b['GasUsed']}</div>
            </div>
            """, unsafe_allow_html=True)

# 1-B. Detailed List (Expanders)
st.markdown("##### 📋 블록 상세 데이터")
for b in block_data:
    with st.expander(f"Block #{b['Height']} ({b['TX Count']} txs) - {b['Timestamp']}"):
        c1, c2 = st.columns([1, 3])
        c1.metric("Gas Used", b['GasUsed'])
        
        if b['TXs']:
            c2.markdown("**Transactions:**")
            for tx in b['TXs']:
                c2.code(tx, language=None)
        else:
            c2.info("No transactions in this block")



# --------------------------------------------------------------------------
# 2. Transaction Inspector
# --------------------------------------------------------------------------
st.divider()
col_tx, col_addr = st.columns(2)

with col_tx:
    st.subheader("📜 트랜잭션 상세 조회 (Transaction Inspector)")
    tx_hash = st.text_input("Enter TX Hash", placeholder="0x...")
    
    if tx_hash:
        try:
            tx = w3.eth.get_transaction(tx_hash)
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            
            st.success("Transaction Found!")
            st.json({
                "from": tx['from'],
                "to": tx['to'],
                "value": str(w3.from_wei(tx['value'], 'ether')) + " ETH",
                "gasPrice": f"{tx['gasPrice'] / 1e9:.2f} Gwei",
                "status": "✅ Success" if receipt['status'] == 1 else "❌ Failed",
                "blockNumber": tx['blockNumber']
            })
            
            # Enhanced Decoding for FDS, USDT, and Contract Interactions
            decoded_info = "Could not decode input data."
            is_erc20_transfer = False
            token_symbol = ""
            
            try:
                # Check if 'to' is a known contract
                contract_obj = None
                if tx['to'] == contracts["ADDRS"]["FDS"]:
                    contract_obj = contracts["FDS"]
                    token_symbol = "FDS"
                elif tx['to'] == contracts["ADDRS"]["USDT"]:
                    contract_obj = contracts["USDT"]
                    token_symbol = "USDT"
                elif tx['to'] == contracts["ADDRS"]["Vault"]:
                    contract_obj = contracts["Vault"]
                    token_symbol = "Vault Action"
                elif tx['to'] == contracts["ADDRS"]["DEX"]:
                    contract_obj = contracts["DEX"]
                    token_symbol = "DEX Action"
                
                if contract_obj:
                    # Try to decode function input
                    func_obj, func_params = contract_obj.decode_function_input(tx['input'])
                    decoded_info = f"**Function:** `{func_obj.fn_name}`\n\n**Args:**\n"
                    for k, v in func_params.items():
                        # Convert Wei to Ether for readability if it looks like a value
                        if "amount" in k.lower() or "value" in k.lower():
                            try:
                                val_fmt = f"{w3.from_wei(v, 'ether'):,.2f}"
                                decoded_info += f"- **{k}**: {val_fmt} (decoded as 1e18)\n"
                            except:
                                decoded_info += f"- **{k}**: {v}\n"
                        else:
                            decoded_info += f"- **{k}**: {v}\n"
                            
                    st.info(f"🦾 Contract Call Detected: **{token_symbol}**")
                    st.markdown(decoded_info)
                else:
                    st.text("General ETH Transfer or Unknown Contract")
                    
            except Exception as decode_err:
                st.warning(f"Decoding failed: {decode_err}")
            
            # Input Data Decoding (Simple text for raw view)
            with st.expander("Show Raw Input Hex"):
                st.text_area("Input Hex", tx['input'], height=100)

        except Exception as e:
            st.error(f"TX Not Found or Error: {e}")
            st.warning("Tip: If you restarted the Hardhat node, previous transaction hashes are invalid. Please check a valid hash from the 'Latest Blocks' section above.")

# --------------------------------------------------------------------------
# 3. Address & Holder Ranking (Simple Event Indexer)
# --------------------------------------------------------------------------
with col_addr:
    st.subheader("👤 주소 및 보유량 순위 (Address & Top Holders)")
    
    # Simple Indexing: Scan Transfer events from Block 0
    # Warning: This is slow for long chains, but fine for testnets/research.
    def get_holders():
        # RPC Error Fix: Alchemy Fork doesn't support get_logs well for local contracts.
        # Instead of scraping logs, we scan known participants in this research environment.
        
        known_addresses = {
            "Vault": contracts["ADDRS"]["Vault"],
            "DEX": contracts["ADDRS"]["DEX"],
            "Hacker": "0xdf57089febbacf7ba0bc227dafbffa9fc08a93fdc68e1e42411a14efcf23656e", # from app.py
            "Watchtower (Owner)": "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d", # from app.py
        }
        
        # Add some default Hardhat accounts that might hold tokens (e.g. Deployer)
        # Note: In Hardhat, Account #0 is usually the deployer.
        # Check Account #0 to #2
        try:
             # Account #0 (Deployer)
             deployer_addr = w3.eth.accounts[0]
             known_addresses["Deployer"] = deployer_addr
        except:
             pass

        holder_list = []
        
        for name, addr in known_addresses.items():
            try:
                bal = contracts["FDS"].functions.balanceOf(addr).call()
                if bal > 0:
                    holder_list.append({
                        "Address": addr,
                        "Alias": name, # New column for readability
                        "Balance": bal / 1e18
                    })
            except Exception as e:
                pass # Ignore invalid addresses
                
        return sorted(holder_list, key=lambda x: x["Balance"], reverse=True)

    holders = get_holders()
    top_holders = pd.DataFrame(holders)
    
    tab_rank, tab_check = st.tabs(["🏆 Top Holders", "🔎 Check Balance"])
    
    with tab_rank:
        st.dataframe(top_holders.head(10), use_container_width=True)
        
    with tab_check:
        addr_input = st.text_input("Enter Address", placeholder="0x...")
        if addr_input:
            try:
                bal_fds = contracts["FDS"].functions.balanceOf(addr_input).call()
                bal_usdt = contracts["USDT"].functions.balanceOf(addr_input).call()
                bal_eth = w3.eth.get_balance(addr_input)
                
                st.write(f"**FDS:** {w3.from_wei(bal_fds, 'ether'):,.2f}")
                st.write(f"**USDT:** {w3.from_wei(bal_usdt, 'ether'):,.2f}")
                st.write(f"**ETH:** {w3.from_wei(bal_eth, 'ether'):,.4f}")
            except:
                st.error("Invalid Address")

# Handle Auto-refresh loop at the very end to ensure full page render
if is_live:
    time.sleep(2) # 2 seconds pull interval
    st.rerun()
