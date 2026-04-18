import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-純淨均線版")

MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    base_url = MY_SHEET_URL.split('/edit')[0]
    csv_url = f"{base_url}/export?format=csv&gid=0"
    try:
        res = requests.get(csv_url, timeout=15)
        res.encoding = 'utf-8'
        if res.status_code != 200: return []
        raw_df = pd.read_csv(io.StringIO(res.text))
    except Exception: return []

    temp_rows = []
    all_sids = []
    for i, row in raw_df.iterrows():
        if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
        sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
        if sign == "": continue 
        
        sid_raw = str(row.iloc[0]).split('.')[0].strip()
        sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
        all_sids.append(sid_full)
        temp_rows.append({'sid_full': sid_full, 'row': row, 'sign': sign})

    if not all_sids: return []

    # 一次下載所有數據
    all_data = yf.download(all_sids, period="120d", progress=False, group_by='ticker')
    
    results = []
    for item in temp_rows:
        try:
            sid_full = item['sid_full']
            row = item['row']
            sign = item['sign']
            
            if len(all_sids) > 1:
                stock = all_data[sid_full].copy()
            else:
                stock = all_data.copy()
            
            if isinstance(stock.columns, pd.MultiIndex):
                stock.columns = stock.columns.get_level_values(0)
            
            if stock.empty or 'Close' not in stock.columns: continue

            # --- 只做均線運算 ---
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma_v = int(pd.to_numeric(row.iloc[2], errors='coerce')) if pd.notna(pd.to_numeric(row.iloc[2], errors='coerce')) else 20
            l_ma_v = int(pd.to_numeric(row.iloc[3], errors='coerce')) if pd.notna(pd.to_numeric(row.iloc[3], errors='coerce')) else 60
            
            stock['MA_S'] = stock['Close'].rolling(window=s_ma_v).mean()
            stock['MA_L'] = stock['Close'].rolling(window=l_ma_v).mean()

            # --- 徹底移除所有與 Box / 區間 / 盤整有關的邏輯 ---

            latest_p = float(stock['Close'].iloc[-1])
            results.append({
                "sid": sid_full, "name": name, "price": latest_p,
                "sign": sign, "df": stock
            })
        except Exception: continue
    return results

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-訊號監控")
with col_b:
    if st.button("🔄 刷新"):
        if "data" in st.session_state: del st.session_state["data"]
        st.rerun()

if not data_list:
    st.info("目前無訊號。")
else:
    for item in data_list:
        df = item['df']
        total_len = len(df)
        header = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}"
        
        with st.expander(header, expanded=True):
            fig = go.Figure()

            # 1. K 線圖
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F'
            ))
            
            # 2. 短均線與長均線
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#0055CC', width=2), name="短均"))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#888888', width=1, dash='dot'), name="長均"))

            # --- 佈局強制清空 ---
            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False,
                margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[total_len - 42, total_len - 0.5], showticklabels=False),
                yaxis=dict(side='right', tickfont=dict(size=11)),
                hovermode=False,
                shapes=[], # 這裡確保不會畫出任何區間
                annotations=[]
            )
            st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False})