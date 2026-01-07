import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(page_title="Research Metrics", page_icon="📈", layout="wide")
st.title("📈 Research Data Analysis")

if "exp_results" not in st.session_state or not st.session_state.exp_results:
    st.info("No experiment data found. Please run simulations in the 'Experiment Runner' page first.")
    
    # 셈플 데이터 생성 버튼 (테스트용)
    if st.button("Generate Sample Data"):
        data = [
            {"Iteration": i, "GasPrice_Gwei": 20 + (i%5), "Latency_Sec": 0.1 * i, "Success": i%2==0, "BlockDiff": -1 if i%2==0 else 0} 
            for i in range(10)
        ]
        st.session_state.exp_results = data
        st.rerun()
    st.stop()

df = pd.DataFrame(st.session_state.exp_results)

# --------------------------------------------------------------------------
# 1. High Level Summary
# --------------------------------------------------------------------------
total = len(df)
success = df["Success"].sum()
fail = total - success

col1, col2, col3 = st.columns(3)
col1.metric("Total Experiments", total)
col2.metric("Successful Prevented", success, f"{(success/total)*100:.1f}%")
col3.metric("Failed (Too Late)", fail, delta_color="inverse")

# --------------------------------------------------------------------------
# 2. Detailed Charts
# --------------------------------------------------------------------------
st.divider()

c1, c2 = st.columns(2)

with c1:
    st.subheader("Gas Price vs Block Difference")
    # 차트: 가스비가 높을수록 Block Diff가 낮아지는가? (음수 = 선제 방어)
    chart1 = alt.Chart(df).mark_circle(size=60).encode(
        x='GasPrice_Gwei',
        y='BlockDiff',
        color='Success',
        tooltip=['Iteration', 'GasPrice_Gwei', 'BlockDiff', 'Latency_Sec']
    ).interactive()
    st.altair_chart(chart1, use_container_width=True)

with c2:
    st.subheader("Latency Impact Distribution")
    # 차트: 지연시간에 따른 성공 여부
    chart2 = alt.Chart(df).mark_bar().encode(
        x=alt.X('Latency_Sec', bin=True),
        y='count()',
        color='Success'
    )
    st.altair_chart(chart2, use_container_width=True)

# --------------------------------------------------------------------------
# 3. Raw Data Export
# --------------------------------------------------------------------------
st.subheader("💾 Export Data")
csv = df.to_csv(index=False).encode('utf-8')
st.download_button(
    "Download CSV for Paper",
    csv,
    "experiment_results.csv",
    "text/csv",
    key='download-csv'
)

st.dataframe(df)
