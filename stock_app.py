import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-精密訊號監控")

SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
GIDS = ["0", "1241939414", "534437042", "1019044698"]

def run_scan():
    all_targets = []
    # --- 步驟 1: 讀取標的 ---
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
                all_targets.append({
                    "sid": f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw,
                    "name": row.iloc[1] if pd.notna(row.iloc[1]) else "未命名",
                    "s_ma_p": pd.to_numeric(row.iloc[2], errors='coerce'),
                    "l_ma_p": pd.to_numeric(row.iloc[3], errors='coerce')
                })
        except: continue

    if not all_targets: return []

    # --- 步驟 2: 批次下載數據 ---
    tickers = list(set([t['sid'] for t in all_targets]))
    full_data = yf.download(tickers, period="150d", progress=False, group_by='ticker')

    results = []
    for item in all_targets:
        try:
            sid = item['sid']
            stock = full_data[sid].copy() if len(tickers) > 1 else full_data.copy()
            stock.dropna(subset=['Close'], inplace=True)
            if stock.empty: continue

            # --- 核心計算 (無預設值) ---
            s_val = item.get('s_ma_p')
            if pd.isna(s_val): continue # 沒填短均線直接跳過
            
            s_day = int(s_val)
            stock['MA_S'] = stock['Close'].rolling(window=s_day).mean()

            l_val = item.get('l_ma_p')
            if pd.notna(l_val):
                stock['MA_L'] = stock['Close'].rolling(window=int(l_val)).mean()
            else:
                stock['MA_L'] = None

            # --- 訊號判定 (今日突破) ---
            if len(stock) < 2 or pd.isna(stock['MA_S'].iloc[-1]) or pd.isna(stock['MA_S'].iloc[-2]):
                continue

            curr_p = float(stock['Close'].iloc[-1])
            prev_p = float(stock['Close'].iloc[-2])
            curr_ma = float(stock['MA_S'].iloc[-1])
            prev_ma = float(stock['MA_S'].iloc[-2])

            is_break_above = (prev_p <= prev_ma) and (curr_p > curr_ma)
            is_break_below = (prev_p >= prev_ma) and (curr_p < curr_ma)

            if is_break_above or is_break_below:
                bias = ((curr_p - curr_ma) / curr_ma) * 100
                trend = "⤴️上揚" if curr_ma > prev_ma else "⤵️下彎"
                icon = "🚀 剛突破" if is_break_above else "🚨 剛跌破"
                
                item.update({
                    "df": stock,
                    "sign": f"{icon} {s_day}MA ({trend}) | 現價: {curr_p:.2f} | {s_day}MA: {curr_ma:.2f} | 乖離: {bias:.2f}%",
                })
                results.append(item)
        except: continue
    return results

# --- 3. 介面呈現 ---
if "data" not in st.session_state:
    with st.spinner('訊號掃描中...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-精密訊號過濾系統")
with col_b:
    if st.button("🔄 重新掃描"):
        del st.session_state["data"]
        st.rerun()

if not data_list:
    st.success("目前尚無符合「今日剛突破/跌破」的訊號。")
else:
    for i, item in enumerate(data_list):
        df = item['df']
        with st.expander(f"{item['sid']} {item['name']} ➔ {item['sign']}", expanded=True):
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F',
                line=dict(width=1.2)
            ))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], name="短期均線", line=dict(color='#0055CC', width=2.5)))
            if item['df']['MA_L'] is not None:
                fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], name="長期均線", line=dict(color='#888888', width=1, dash='dot')))

            t_len = len(df)
            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[t_len - 42, t_len - 0.5], showticklabels=False, fixedrange=True),
                yaxis=dict(side='right', tickfont=dict(size=11), fixedrange=True),
                hovermode=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}, key=f"ch_{item['sid']}_{i}")