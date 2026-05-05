import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-精密訊號監控")

# 試算表設定
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
GIDS = ["0", "1241939414", "534437042", "1019044698"]

def run_scan():
    all_targets = []
    
    # --- 步驟 1: 讀取 Google Sheets 標的 ---
    for gid in GIDS:
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code != 200: continue
            raw_df = pd.read_csv(io.StringIO(res.text))
            
            for _, row in raw_df.iterrows():
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue
                
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                
                all_targets.append({
                    "sid": sid_full,
                    "name": row.iloc[1] if pd.notna(row.iloc[1]) else "未命名",
                    "s_ma_p": pd.to_numeric(row.iloc[2], errors='coerce'),
                    "l_ma_p": pd.to_numeric(row.iloc[3], errors='coerce')
                })
        except Exception: continue

    if not all_targets: return []

    # --- 步驟 2: 批次下載數據 ---
    tickers = list(set([t['sid'] for t in all_targets]))
    full_data = yf.download(tickers, period="200d", progress=False, group_by='ticker')

    results = []
    for item in all_targets:
        try:
            sid = item['sid']
            if len(tickers) > 1:
                stock = full_data[sid].copy()
            else:
                stock = full_data.copy()
                
            stock.dropna(subset=['Close'], inplace=True)
            if stock.empty: continue

            # --- 均線計算 ---
            s_val = item.get('s_ma_p')
            l_val = item.get('l_ma_p')
            if pd.isna(s_val): continue 
            
            s_day = int(s_val)
            stock['MA_S'] = stock['Close'].rolling(window=s_day).mean()

            if pd.notna(l_val):
                l_day = int(l_val)
                stock['MA_L'] = stock['Close'].rolling(window=l_day).mean()
            else:
                l_day = "未設定"
                stock['MA_L'] = None

            # --- 訊號判定 ---
            if len(stock) < 2 or pd.isna(stock['MA_S'].iloc[-1]) or pd.isna(stock['MA_S'].iloc[-2]): 
                continue
                
            curr_p = float(stock['Close'].iloc[-1])
            prev_p = float(stock['Close'].iloc[-2])
            curr_ma_s = float(stock['MA_S'].iloc[-1])
            prev_ma_s = float(stock['MA_S'].iloc[-2])
            
            is_break_above = (prev_p <= prev_ma_s) and (curr_p > curr_ma_s)
            is_break_below = (prev_p >= prev_ma_s) and (curr_p < curr_ma_s)
            
            if not (is_break_above or is_break_below):
                continue

            # --- 狀態封裝 ---
            bias = ((curr_p - curr_ma_s) / curr_ma_s) * 100
            ma_trend = "⤴️" if curr_ma_s > prev_ma_s else "⤵️"
            sign_icon = "🚀" if is_break_above else "🚨"
            status = f"{sign_icon} {s_day}MA({ma_trend}) 現:{curr_p:.1f} 偏:{bias:.1f}%"

            # --- 箱型計算 ---
            view_df = stock.tail(60)
            best_box = None
            idx = 0
            while idx < len(view_df) - 2:
                w = view_df.iloc[idx:idx+3]
                w_max, w_min = w['High'].max(), w['Low'].min()
                if w_min > 0 and (w_max - w_min) / w_min <= 0.03:
                    c_i = idx + 1
                    while c_i < len(view_df):
                        nr = view_df.iloc[c_i]
                        if nr['Low'] < w_min * 0.985 or nr['High'] > w_max * 1.015: break
                        c_i += 1
                    best_box = {'start': view_df.index[idx], 'end': view_df.index[c_i-1], 'top': w_max, 'bottom': w_min}
                    idx = c_i
                else: idx += 1

            item.update({"price": curr_p, "df": stock, "box": best_box, "sign": status, "l_day": l_day})
            results.append(item)
            
        except Exception: continue
    return results

# --- 3. UI 呈現 ---
if "data" not in st.session_state:
    with st.spinner('掃描中...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-訊號監控")
with col_b:
    if st.button("🔄 刷新"):
        del st.session_state["data"]
        st.rerun()

if not data_list:
    st.info("尚無訊號。")
else:
    for i, item in enumerate(data_list):
        df = item['df']
        t_len = len(df)
        # 把標題也縮短一點，適合小圖面
        with st.expander(f"{item['sid']} {item['name']} | {item['sign']}", expanded=True):
            fig = go.Figure()
            
            if item['box']:
                b = item['box']
                fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                             line=dict(width=0), fillcolor="rgba(128,128,128,0.2)")
            
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                                       increasing_line_color='#E63946', decreasing_line_color='#2A9D8F', name="K"))
            
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], name="S", line=dict(color='#0055CC', width=1.5)))
            if item['l_day'] != "未設定":
                fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], name="L", line=dict(color='#888888', width=1, dash='dot')))

            # --- 高度縮小至 150 ---
            fig.update_layout(
                height=150, 
                margin=dict(l=10, r=10, t=10, b=10), # 縮小邊距
                showlegend=False, 
                template="plotly_white", 
                xaxis_rangeslider_visible=False,
                xaxis=dict(type='category', range=[max(0, t_len - 60), t_len - 0.5], showticklabels=False),
                yaxis=dict(side='right', tickfont=dict(size=9)) # 縮小字體
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}, key=f"ch_{i}")