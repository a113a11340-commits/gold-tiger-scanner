import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-區間監控版")

# 你的試算表基礎連結
BASE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
# 三個分頁的 GID
GIDS = ["0", "1241939414", "534437042"]

def run_scan():
    all_temp_rows = []
    all_sids = []

    # --- 1. 遍歷所有分頁抓取代號 ---
    for gid in GIDS:
        csv_url = f"{BASE_SHEET_URL}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=15)
            res.encoding = 'utf-8'
            if res.status_code != 200: continue
            raw_df = pd.read_csv(io.StringIO(res.text))
            
            for i, row in raw_df.iterrows():
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
                sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                if sign == "": continue 
                
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                
                # 收集所有代號與對應資訊
                all_temp_rows.append({'sid_full': sid_full, 'row': row, 'sign': sign})
                if sid_full not in all_sids:
                    all_sids.append(sid_full)
        except Exception:
            continue

    if not all_sids: return []

    # --- 2. 一次性批量下載 (即時讀取，不使用 cache) ---
    all_data = yf.download(all_sids, period="120d", progress=False, group_by='ticker', threads=True)
    
    results = []
    for item in all_temp_rows:
        try:
            sid_full = item['sid_full']
            row = item['row']
            sign = item['sign']
            
            # 針對單檔或多檔下載的情況處理 DataFrame
            if len(all_sids) > 1:
                stock = all_data[sid_full].copy()
            else:
                stock = all_data.copy()
            
            if isinstance(stock.columns, pd.MultiIndex):
                stock.columns = stock.columns.get_level_values(0)
            
            if stock.empty or 'Close' not in stock.columns: continue

            # 原有邏輯：計算均線
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma_p = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma_p = pd.to_numeric(row.iloc[3], errors='coerce')
            s_ma_val = int(s_ma_p) if pd.notna(s_ma_p) else 20
            l_ma_val = int(l_ma_p) if pd.notna(l_ma_p) else 60
            stock['MA_S'] = stock['Close'].rolling(window=s_ma_val).mean()
            stock['MA_L'] = stock['Close'].rolling(window=l_ma_val).mean()
            
            # 原有邏輯：尋找箱型
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

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    with st.spinner('讀取即時訊號中...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-訊號監控 (多分頁即時版)")
with col_b:
    if st.button("🔄 刷新"):
        del st.session_state["data"]
        st.rerun()

if not data_list:
    st.info("所選分頁的 F 欄位目前無訊號標註。")
else:
    for item in data_list:
        df = item['df']
        total_len = len(df)
        header = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}"
        
        with st.expander(header, expanded=True):
            fig = go.Figure()
            
            # 箱型區間視覺延展
            if item['box']:
                b = item['box']
                fig.add_shape(
                    type="rect", 
                    x0=b['start'], 
                    x1=df.index[-1],
                    y0=b['bottom'], 
                    y1=b['top'],
                    line=dict(width=0), 
                    fillcolor="gray", 
                    opacity=0.3,
                    layer="below" 
                )

            # K線
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F',
                line=dict(width=1.2)
            ))
            
            # 短/長均線
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