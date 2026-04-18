import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-均線接觸監控版")

MY_SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
SHEET_GIDS = ["0", "534437042", "1241939414"] 

def run_scan():
    all_sids_info = [] 
    sids_to_download = set() 
    clean_base = MY_SHEET_BASE.split('/edit')[0]

    for gid in SHEET_GIDS:
        csv_url = f"{clean_base}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=15)
            res.encoding = 'utf-8'
            if res.status_code != 200 or res.text.strip().startswith("<!DOCTYPE"): continue
            raw_df = pd.read_csv(io.StringIO(res.text))
            for i, row in raw_df.iterrows():
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
                sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                if sign == "": continue 
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                sids_to_download.add(sid_full)
                all_sids_info.append({"sid_full": sid_full, "row": row, "sign": sign})
        except Exception: continue

    if not sids_to_download: return []

    # 批量下載
    download_list = list(sids_to_download)
    all_data = yf.download(download_list, period="120d", progress=False, group_by='ticker')

    results = []
    for item in all_sids_info:
        try:
            sid_full = item['sid_full']
            stock = all_data[sid_full].copy() if len(download_list) > 1 else all_data.copy()
            if isinstance(stock.columns, pd.MultiIndex): stock.columns = stock.columns.get_level_values(0)
            if stock.empty or 'Close' not in stock.columns:
                stock = yf.download(sid_full, period="120d", progress=False)
                if isinstance(stock.columns, pd.MultiIndex): stock.columns = stock.columns.get_level_values(0)
            
            if stock.empty: continue
            stock = stock.dropna(subset=['Close', 'High', 'Low', 'Open'])

            row = item['row']
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma_val = int(pd.to_numeric(row.iloc[2], errors='coerce')) if pd.notna(pd.to_numeric(row.iloc[2], errors='coerce')) else 20
            l_ma_val = int(pd.to_numeric(row.iloc[3], errors='coerce')) if pd.notna(pd.to_numeric(row.iloc[3], errors='coerce')) else 60
            
            # 使用自訂的短均線與長均線
            stock['MA_S'] = stock['Close'].rolling(window=s_ma_val).mean()
            stock['MA_L'] = stock['Close'].rolling(window=l_ma_val).mean()
            
            # --- 箱型搜尋邏輯：完全不限制漲跌幅，只看是否連續 3 天碰到均線 ---
            view_df = stock.tail(42)
            best_box = None
            
            # 由後往前搜尋，找最新的觸碰區間
            for idx in range(len(view_df) - 3, -1, -1):
                w = view_df.iloc[idx:idx+3]
                
                # 核心判斷：這 3 天的 [Low, High] 區間是否都包含當天的 MA_S
                all_touch = True
                for j in range(3):
                    day_high = w['High'].iloc[j]
                    day_low = w['Low'].iloc[j]
                    day_ma = w['MA_S'].iloc[j]
                    if not (day_low <= day_ma <= day_high):
                        all_touch = False
                        break
                
                if all_touch:
                    w_max, w_min = w['High'].max(), w['Low'].min()
                    start_i, end_i = idx, idx + 2
                    
                    # 延續性檢查：後續 K 棒是否也繼續觸碰均線或維持在該區間內
                    for k in range(idx + 3, len(view_df)):
                        nr = view_df.iloc[k]
                        # 只要最新 K 棒有碰到均線，就一直延續框框
                        if (nr['Low'] <= nr['MA_S'] <= nr['High']):
                            end_i = k
                            w_max = max(w_max, nr['High'])
                            w_min = min(w_min, nr['Low'])
                        else:
                            break
                    
                    best_box = {'start': view_df.index[start_i], 'end': view_df.index[end_i], 'top': w_max, 'bottom': w_min}
                    break 

            latest_p = float(stock['Close'].iloc[-1])
            touch_msg = ""
            if best_box and (best_box['bottom'] * 0.99 <= latest_p <= best_box['top'] * 1.01):
                touch_msg = " 🔥 股價回測箱型區"

            results.append({
                "sid": sid_full, "name": name, "price": latest_p,
                "sign": item['sign'] + touch_msg, "df": stock, "box": best_box 
            })
        except Exception: continue
    return results

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    with st.spinner('同步最新均線資料中...'): st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-均線接觸監控 (無震幅限制版)")
with col_b:
    if st.button("🔄 刷新"):
        del st.session_state["data"]
        st.rerun()

for i, item in enumerate(data_list):
    df = item['df']
    with st.expander(f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}", expanded=True):
        fig = go.Figure()
        
        # 繪製灰色箱型 (延展至最後一根 K 棒)
        if item['box']:
            b = item['box']
            fig.add_shape(type="rect", x0=b['start'], x1=df.index[-1], y0=b['bottom'], y1=b['top'],
                          line=dict(width=0), fillcolor="gray", opacity=0.3)

        # K線圖 (深色紅綠)
        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            increasing_line_color='#8B0000', increasing_fillcolor='#8B0000', # 深紅
            decreasing_line_color='#004400', decreasing_fillcolor='#004400', # 深綠
            name="K線"
        ))
        
        # 均線設定
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#0044BB', width=2.5), name="短均"))
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#666666', width=1, dash='dot'), name="長均"))

        fig.update_layout(
            height=380, showlegend=False, template="plotly_white", xaxis_rangeslider_visible=False,
            margin=dict(l=5, r=5, t=5, b=5), xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
            yaxis=dict(side='right', fixedrange=True)
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}, key=f"v4_{item['sid']}_{i}")