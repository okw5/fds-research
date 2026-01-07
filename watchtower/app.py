import streamlit as st
import time
import pandas as pd
from lib.utils import load_contracts, get_web3, send_defense_tx

# --------------------------------------------------------------------------
# Page Config & Title
# --------------------------------------------------------------------------
st.set_page_config(
    page_title="FDS Research Control Tower",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🛡️ FDS Research: Adaptive Hybrid Defense")
st.markdown("### System Overview and Real-time Monitoring")

# --------------------------------------------------------------------------
# Load Resources
# --------------------------------------------------------------------------
contracts = load_contracts()
if not contracts:
    st.stop()

w3 = get_web3()
fds = contracts["FDS"]
vault = contracts["Vault"]
oracle = contracts["Oracle"]
dex = contracts["DEX"]

# --------------------------------------------------------------------------
# Sidebar & Status
# --------------------------------------------------------------------------
st.sidebar.header("System Control")
auto_defense = st.sidebar.toggle("Auto Defense Mode", value=True)

is_paused = fds.functions.paused().call()
status_color = "🔴 PAUSED" if is_paused else "🟢 NORMAL"
st.sidebar.metric("System Status", status_color)

if st.sidebar.button("Resume Service (Unpause)"):
    if is_paused:
        try:
            owner = w3.eth.accounts[0] # Hardhat Account #0
            tx = fds.functions.resumeService().transact({'from': owner})
            st.toast("Service Resumed", icon="✅")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")

# --------------------------------------------------------------------------
# Real-time Metrics (Summary)
# --------------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)

# 1. Total Supply
supply = float(w3.from_wei(fds.functions.totalSupply().call(), 'ether'))
col1.metric("FDS Total Supply", f"{supply:,.0f}")

# 2. Vault Balance
vault_bal = float(w3.from_wei(contracts["USDT"].functions.balanceOf(contracts["ADDRS"]["Vault"]).call(), 'ether'))
col2.metric("Vault Reserves (USDT)", f"${vault_bal:,.0f}")

# 3. Price Spread
oracle_p = float(w3.from_wei(oracle.functions.getLatestPrice().call(), 'ether'))
pool_fds = float(w3.from_wei(dex.functions.reserveFDS().call(), 'ether'))
pool_usdt = float(w3.from_wei(dex.functions.reserveUSDT().call(), 'ether'))
dex_p = (pool_usdt / pool_fds) if pool_fds > 0 else 0
spread = abs(oracle_p - dex_p) / oracle_p * 100 if oracle_p > 0 else 0

col3.metric("Price Spread", f"{spread:.2f}%", delta=f"{dex_p:.4f} (DEX)")

# 4. Rate Limit Status (New)
try:
    period_mint = float(w3.from_wei(fds.functions.currentPeriodMintAmount().call(), 'ether'))
    limit = float(w3.from_wei(fds.functions.mintLimitPerPeriod().call(), 'ether'))
    usage_pct = (period_mint / limit) * 100
    col4.metric("Rate Limit Usage", f"{usage_pct:.1f}%", f"{period_mint:,.0f} / {limit:,.0f}")
except:
    col4.metric("Rate Limit", "N/A")

st.divider()

# --------------------------------------------------------------------------
# Simple Anomaly Monitor (Legacy Logic)
# --------------------------------------------------------------------------
st.subheader("⚠️ Live Anomaly Monitor")

if not is_paused:
    alerts = []
    
    # Check 1: Rate Limit Warning
    if period_mint > limit * 0.8:
        alerts.append(f"🔥 High Mint Volume: {period_mint:,.0f} FDS (Limit: {limit:,.0f})")
    
    # Check 2: Drain Warning
    THRESHOLD_VAULT = 2000000 # Initial logic reference
    if vault_bal < THRESHOLD_VAULT * 0.9: 
         alerts.append(f"💧 Reserve Low: ${vault_bal:,.0f}")

    # Check 3: Depeg
    if spread > 5.0:
        alerts.append(f"📉 Severe Depeg: {spread:.2f}%")

    if alerts:
        for alert in alerts:
            st.error(alert)
        
        if auto_defense and spread > 5.0: # Auto trigger for depeg example
            r, l = send_defense_tx(contracts, "Depeg detected Main")
            st.success(f"🛡️ Auto-Defense Triggered! (Initial Block: {r['blockNumber']})")
            time.sleep(2)
            st.rerun()
    else:
        st.info("No active anomalies detected. System is healthy.")

else:
    st.warning("System is currently PAUSED by Circuit Breaker or Admin.")
