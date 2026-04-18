import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-監控版")

MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    base_url = MY_SHEET_URL.split('/edit')[0]
    csv_url = f"{base_url}/export?format=csv&gid=0"
    try:
        res = requests.get(csv_url, timeout=15)
        res.encoding = 'utf-8'
        raw_df = pd.read_csv(io.StringIO(res.text))
    except: return []

    results = []
    for _, row in raw_df.iterrows():
        sid_raw = str(row.iloc[0]).split('.')[0].strip()
        if not sid_raw or sid_raw == "nan": continue
        
        # 只檢查 F 欄位是否有標註訊號
        sign = str(row.iloc[5]).strip() if len(row) > 5 else ""
        if sign == "nan" or sign == "": continue
        
        sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
        
        try:
            # 下載數據
            stock = yf.download(sid_full, period="120d", progress=False)
            if stock.empty: continue
            
            # 確保資料格式正確並計算均線
            df_close = stock['Close'].squeeze()
            s_ma_val = int(pd.to_numeric(row.iloc[2], errors='coerce')) or 20
            l_ma_val = int(pd.to_numeric(row.iloc[3], errors='coerce')) or 60
            
            ma_s = df_close.rolling(window=s_ma_val).mean()
            ma_l = df_close.rolling(window=l_ma_val).mean()
            
            results.append({
                "sid": sid_full,
                "name": row.iloc[1],
                "price": float(df_close.iloc[-1]),
                "sign": sign,
                "df": stock,
                "ma_s": ma_s,
                "ma_l": ma_l
            })
        except: continue
    return results

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    st.session_state["data"] = run_scan()

data_list = st.session_state["data"]

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-訊號監控")
with col_b:
    if st.button("🔄 刷新"):
        st.session_state.clear()
        st.rerun()

if not data_list:
    st.info("目前無訊號標註。")
else:
    for item in data_list:
        df = item['df']
        header = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}"
        
        with st.expander(header, expanded=True):
            fig = go.Figure()

            # 繪製 K 線
            fig.add_trace(go.Candlestick(
                x=df.index, 
                open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', decreasing_line_color='#2A9D8F',
                name="K線"
            ))
            
            # 繪製均線
            fig.add_trace(go.Scatter(x=df.index, y=item['ma_s'], line=dict(color='#0055CC', width=2), name="短均"))
            fig.add_trace(go.Scatter(x=df.index, y=item['ma_l'], line=dict(color='#888888', width=1, dash='dot'), name="長均"))

            # 佈局設定：徹底停用所有形狀與註解
            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False,
                margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
                yaxis=dict(side='right', fixedrange=True),
                shapes=[],      # 確保無任何方框
                annotations=[], # 確保無任何文字
                hovermode=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})