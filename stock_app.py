import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import plotly.graph_objects as go

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-純均線監控")

# --- 富果 API 設定 ---
FUGLE_KEY = "Mzk5YWVkYmMtYzVhNi00OWRhLWI5NWUtNGNjYzI3NjNjZDYyIDg0NDdhYjVmLThlMTktNDE3MC1hZDZmLThkMDcwNThiYzM1Mw=="

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    /* 強制設定表格樣式，讓手機檢視更友善 */
    table { width: 100% !important; font-size: 14px !important; }
    th { background-color: #f0f2f6 !important; }
    </style>
    """, unsafe_allow_html=True)

# (其餘邏輯與之前相同，略過中間重複的函數定義以節省版面，請直接替換完整檔案)
# ... [fetch_signals, run_scan_for_sheet, run_all_scans 函數維持不變] ...

st.title("🐯 金虎南：轉折監控系統")
update_time = time.strftime("%Y-%m-%d %H:%M:%S")
st.caption(f"最後更新時間：{update_time}")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 同步所有分頁資料", use_container_width=True):
        st.session_state["all_data"] = run_all_scans()
with col2:
    if st.button("🚀 強制刷新即時報價", type="primary", use_container_width=True):
        fetch_signals.clear()
        st.session_state["all_data"] = run_all_scans()

if "all_data" in st.session_state and st.session_state["all_data"]:
    st.subheader(f"📊 綜合監控結果 ({len(st.session_state['all_data'])} 檔)")
    
    # 處理顯示資料
    df_display = pd.DataFrame(st.session_state["all_data"]).drop(columns=["plot_data", "signal_types", "短", "長"], errors="ignore")
    cols = ['來源工作表'] + [col for col in df_display.columns if col != '來源工作表']
    
    # 【關鍵修改】：改用 st.table 確保不出現捲動條，直接一次性完整展開顯示
    st.table(df_display[cols])
    
    st.markdown("---")
    st.subheader("📈 觸發個股 K 線軌道圖")
    
    for item in st.session_state["all_data"]:
        p = item.get("plot_data")
        sig_text = item["訊號"]
        sig_types = item.get("signal_types", [])
        
        if p:
            # 保持原本的摺疊功能，方便您在手機上查看特定個股
            with st.expander(f"🔍 {item['代號']} {item['名稱']} — 【{sig_text}】", expanded=False):
                fig = go.Figure()
                # ... [繪圖邏輯不變] ...
                fig.add_trace(go.Candlestick(
                    x=p["dates"], open=p["opens"], high=p["highs"], low=p["lows"], close=p["closes"],
                    increasing_line_color='#FF3333', decreasing_line_color='#00A600',
                    line_width=1.8, name='K線'
                ))
                # ... [其餘繪圖設定不變] ...
                st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
elif "all_data" in st.session_state:
    st.info("目前無觸發訊號。")