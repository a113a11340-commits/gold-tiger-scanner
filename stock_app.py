import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

st.set_page_config(layout="wide", page_title="金虎南-訊號監控")

SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/export?format=csv&gid=0"

def fetch_data():
    try:
        res = requests.get(SHEET_URL, timeout=15)
        res.encoding = 'utf-8'
        df_sheet = pd.read_csv(io.StringIO(res.text))
    except:
        return []

    results = []
    for _, row in df_sheet.iterrows():
        sid_raw = str(row.iloc[0]).split('.')[0].strip()
        if not sid_raw or sid_raw == "nan": continue
        
        sign = str(row.iloc[5]).strip() if len(row) > 5 else ""
        if not sign or sign == "nan": continue
        
        sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
        name = str(row.iloc[1])
        
        try:
            # 取得均線參數
            ma_s_val = int(pd.to_numeric(row.iloc[2], errors='coerce')) if pd.notna(pd.to_numeric(row.iloc[2], errors='coerce')) else 20
            ma_l_val = int(pd.to_numeric(row.iloc[3], errors='coerce')) if pd.notna(pd.to_numeric(row.iloc[3], errors='coerce')) else 60
            
            # 下載數據
            stock = yf.download(sid_full, period="120d", progress=False)
            if stock.empty: continue
            
            close_px = stock['Close'].squeeze()
            
            results.append({
                "sid": sid_full,
                "name": name,
                "price": float(close_px.iloc[-1]),
                "sign": sign,
                "df": stock,
                "ma_s": close_px.rolling(window=ma_s_val).mean(),
                "ma_l": close_px.rolling(window=ma_l_val).mean()
            })
        except:
            continue
    return results

col1, col2 = st.columns([8, 2])
with col1: st.subheader("🐯 金虎南-訊號監控")
with col2:
    if st.button("🔄 刷新 (強制清除暫存)"):
        st.cache_data.clear()
        if "scan_data" in st.session_state:
            del st.session_state["scan_data"]
        st.rerun()

if "scan_data" not in st.session_state:
    with st.spinner("讀取中..."):
        st.session_state["scan_data"] = fetch_data()

data_list = st.session_state["scan_data"]

if not data_list:
    st.info("目前無訊號標註。")
else:
    for item in data_list:
        df = item['df']
        title = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}"
        
        with st.expander(title, expanded=True):
            fig = go.Figure()

            # 只繪製 K線
            fig.add_trace(go.Candlestick(
                x=df.index, 
                open=df['Open'].squeeze(), 
                high=df['High'].squeeze(), 
                low=df['Low'].squeeze(), 
                close=df['Close'].squeeze(),
                increasing_line_color='#E63946', 
                decreasing_line_color='#2A9D8F'
            ))
            
            # 只繪製 短均、長均
            fig.add_trace(go.Scatter(x=df.index, y=item['ma_s'], line=dict(color='#0055CC', width=2)))
            fig.add_trace(go.Scatter(x=df.index, y=item['ma_l'], line=dict(color='#888888', width=1, dash='dot')))

            # 強制清空版面設定的任何裝飾
            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
                yaxis=dict(side='right', fixedrange=True),
                shapes=[], 
                annotations=[]
            )
            
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})