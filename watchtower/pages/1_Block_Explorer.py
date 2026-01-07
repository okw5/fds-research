import streamlit as st
import pandas as pd
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
st.subheader("⛓️ Latest Blocks")

if st.button("Refresh Chain Data"):
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
        "TXs": tx_hashes # Store list of hashes
    })

# Custom UI for Blocks to show copyable TX hashes
for b in block_data:
    with st.expander(f"Block #{b['Height']} ({b['TX Count']} txs) - {b['Timestamp']}"):
        c1, c2 = st.columns([1, 3])
        c1.metric("Gas Used", b['GasUsed'])
        
        if b['TXs']:
            c2.markdown("**Transactions:**")
            for tx in b['TXs']:
                c2.code(tx, language=None) # Display as code block for easy copy
        else:
            c2.info("No transactions in this block")

# --------------------------------------------------------------------------
# 2. Transaction Inspector
# --------------------------------------------------------------------------
st.divider()
col_tx, col_addr = st.columns(2)

with col_tx:
    st.subheader("📜 Transaction Inspector")
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
            
            # Input Data Decoding (Simple text)
            st.markdown("**Input Data:**")
            st.text_area("Input Hex", tx['input'], height=100)
            
        except Exception as e:
            st.error(f"TX Not Found.")
            st.warning("Tip: If you restarted the Hardhat node, previous transaction hashes are invalid. Please check a valid hash from the 'Latest Blocks' section above.")

# --------------------------------------------------------------------------
# 3. Address & Holder Ranking (Simple Event Indexer)
# --------------------------------------------------------------------------
with col_addr:
    st.subheader("👤 Address & Top Holders")
    
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
