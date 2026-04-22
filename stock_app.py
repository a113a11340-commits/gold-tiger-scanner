import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-區間監控版")

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

    # 1. 先整理出所有需要下載的代碼清單
    symbol_map = {}  # 紀錄 yf 代碼與原始資料的對應
    symbols_to_download = []
    
    for i, row in raw_df.iterrows():
        if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue
        sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
        if sign == "": continue
        
        sid_raw = str(row.iloc[0]).split('.')[0].strip()
        sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
        symbols_to_download.append(sid_full)
        symbol_map[sid_full] = row # 暫存這列資料之後用

    if not symbols_to_download: return []

    # 2. 一次性 API 請求所有股票數據
    # threads=True 加速下載
    all_data = yf.download(symbols_to_download, period="120d", progress=False, group_by='ticker', threads=True)

    results = []
    for sid_full in symbols_to_download:
        try:
            # 從 all_data 中取出該檔股票的數據
            if len(symbols_to_download) > 1:
                stock = all_data[sid_full].copy()
            else:
                stock = all_data.copy() # 如果只有一檔，yf 返回格式略有不同
            
            if stock.empty or stock['Close'].isnull().all(): continue
            
            # 移除 MultiIndex 確保繪圖邏輯正確
            if isinstance(stock.columns, pd.MultiIndex):
                stock.columns = stock.columns.get_level_values(0)

            row = symbol_map[sid_full]
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            sign = str(row.iloc[5]).strip()
            s_ma_p = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma_p = pd.to_numeric(row.iloc[3], errors='coerce')

            # 計算均線
            s_ma_val = int(s_ma_p) if pd.notna(s_ma_p) else 20
            l_ma_val = int(l_ma_p) if pd.notna(l_ma_p) else 60
            stock['MA_S'] = stock['Close'].rolling(window=s_ma_val).mean()
            stock['MA_L'] = stock['Close'].rolling(window=l_ma_val).mean()

            # --- 自動尋找最近的箱型區間 (邏輯不動) ---
            view_df = stock.tail(42)
            best_box = None
            idx = 0
            while idx < len(view_df) - 2:
                w = view_df.iloc[idx:idx+3]
                w_max, w_min = w['High'].max(), w['Low'].min()
                if (w_max - w_min) / w_min <= 0.03:
                    start_i = idx
                    while idx < len(view_df) - 1:
                        nr = view_df.iloc[idx+1]
                        if nr['Low'] >= w_min * 0.985 and nr['High'] <= w_max * 1.015:
                            idx += 1
                        else:
                            break
                    best_box = {'start': view_df.index[start_i], 'end': view_df.index[idx], 'top': w_max, 'bottom': w_min}
                idx += 1

            latest_p = float(stock['Close'].iloc[-1])
            results.append({
                "sid": sid_full, "name": name, "price": latest_p,
                "s_ma_p": s_ma_val, "l_ma_p": l_ma_val, "sign": sign, "df": stock,
                "box": best_box 
            })
        except Exception: continue
    return results

# --- 2. 呈現介面 (完全保持原樣) ---
if "data" not in st.session_state:
    with st.spinner('讀取訊號中...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-訊號監控")
with col_b:
    if st.button("🔄 刷新"):
        if "data" in st.session_state:
            del st.session_state["data"]
        st.rerun()

if not data_list:
    st.info("試算表 F 欄位目前無訊號標註。")
else:
    for item in data_list:
        df = item['df']
        total_len = len(df)
        header = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}"
        
        with st.expander(header, expanded=True):
            fig = go.Figure()
            if item['box']:
                b = item['box']
                fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                              line=dict(width=0), fillcolor="gray", opacity=0.3)

            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F',
                line=dict(width=1.2)
            ))
            
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#0055CC', width=2.5), name="短均"))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#888888', width=1, dash='dot'), name="長均"))

            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False,
                margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[total_len - 42, total_len - 0.5], showticklabels=False, fixedrange=True),
                yaxis=dict(side='right', tickfont=dict(size=11), fixedrange=True),
                hovermode=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False})