# 2-Layer Payment Token Security Experiment Walkthrough

This guide explains how to run the simulation comparing **Model A (Single Token)** and **Model B (2-Layer Token)**.

## 1. Prerequisites
Ensure the local blockchain is running and contracts are deployed.
```bash
# Terminal 1: Start Node
npx hardhat node

# Terminal 2: Deploy Contracts
npx hardhat run scripts/deploy_2layer.ts --network localhost
```

## 2. Running the Experiment UI
Start the Streamlit dashboard:
```bash
streamlit run watchtower/app.py
```
*Navigate to the **"Two Layer Experiment"** page from the sidebar.*

## 3. Experiment Scenarios

### Scenario A: Normal Traffic (Base Case)
1. Click **"Run Normal Traffic (5 Tx)"** in the sidebar.
2. Observe both models processing transactions.
    - **Model A**: Mixed traffic on one token.
    - **Model B**: Separates traffic into Micro (Direct) and Macro (Signed) layers.

### Scenario B: Macro Dump Attack (Stolen Key)
1. Click **"Hacker: Huge Dump"** in the sidebar.
2. Observe the results:
    - **Model A**: The system may crash or fail to stop it (existing model weakness), or if it stops, *everything* stops.
    - **Model B**: The **Macro Layer** automatically Pauses (Circuit Breaker) due to volume limits.
    - **Critical Observation**: Even though Macro Layer is paused, **Micro Layer is still active**. Run "Normal Traffic" again to verify Micro txs still succeed.

### Scenario C: Micro Siphon Attack
1. Click **"Hacker: Micro Siphon"**.
2. This executes small, non-alerting thefts.
3. This highlights the need for *post-audit blacklisting* (future work/manual admin action) rather than real-time blocking, keeping the system usable.

## 4. Key Takeaway
The 2-Layer model demonstrates **higher system availability**. A security incident in the high-value layer does not impact the everyday low-value payment network.
