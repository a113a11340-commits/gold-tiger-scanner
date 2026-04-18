import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-區間延展版")

# 設定試算表基礎網址與三個分頁 GID
MY_SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
SHEET_GIDS = ["0", "534437042", "1241939414"] 

def run_scan():
    all_sids_info = [] 
    sids_to_download = set() 

    # 確保網址乾淨，切除 /edit 以後的內容
    clean_base = MY_SHEET_BASE.split('/edit')[0]

    # 遍歷三個分頁抓取代號
    for gid in SHEET_GIDS:
        csv_url = f"{clean_base}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=15)
            res.encoding = 'utf-8'
            if res.status_code != 200 or res.text.strip().startswith("<!DOCTYPE"):
                continue
            
            raw_df = pd.read_csv(io.StringIO(res.text))
            
            for i, row in raw_df.iterrows():
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
                
                # F 欄位 (index 5) 有文字才監控
                sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                if sign == "": continue 
                
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                
                sids_to_download.add(sid_full)
                all_sids_info.append({
                    "sid_full": sid_full,
                    "row": row,
                    "sign": sign
                })
        except Exception:
            continue

    if not sids_to_download: return []

    # 一次性批量下載
    download_list = list(sids_to_download)
    all_data = yf.download(download_list, period="120d", progress=False, group_by='ticker')

    results = []
    for item in all_sids_info:
        try:
            sid_full = item['sid_full']
            if len(download_list) > 1:
                stock = all_data[sid_full].copy()
            else:
                stock = all_data.copy()

            if isinstance(stock.columns, pd.MultiIndex):
                stock.columns = stock.columns.get_level_values(0)
            
            if stock.empty or 'Close' not in stock.columns: continue

            # 計算均線
            row = item['row']
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma_val = int(pd.to_numeric(row.iloc[2], errors='coerce')) if pd.notna(pd.to_numeric(row.iloc[2], errors='coerce')) else 20
            l_ma_val = int(pd.to_numeric(row.iloc[3], errors='coerce')) if pd.notna(pd.to_numeric(row.iloc[3], errors='coerce')) else 60
            
            stock['MA_S'] = stock['Close'].rolling(window=s_ma_val).mean()
            stock['MA_L'] = stock['Close'].rolling(window=l_ma_val).mean()
            
            # 尋找箱型 (靈敏度稍微調升至 3.5%)
            view_df = stock.tail(42)
            best_box = None
            idx = 0
            while idx <= len(view_df) - 3:
                w = view_df.iloc[idx:idx+3]
                w_max, w_min = w['High'].max(), w['Low'].min()
                if (w_max - w_min) / w_min <= 0.035:
                    start_i = idx
                    end_i = idx + 2
                    for j in range(idx + 3, len(view_df)):
                        nr = view_df.iloc[j]
                        if nr['Low'] >= w_min * 0.985 and nr['High'] <= w_max * 1.015:
                            end_i = j
                        else:
                            break
                    best_box = {'start': view_df.index[start_i], 'end': view_df.index[end_i], 'top': w_max, 'bottom': w_min}
                    idx = end_i
                idx += 1

            results.append({
                "sid": sid_full, "name": name, "price": float(stock['Close'].iloc[-1]),
                "sign": item['sign'], "df": stock, "box": best_box 
            })
        except Exception:
            continue
    return results

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    with st.spinner('讀取中...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-區間延展版")
with col_b:
    if st.button("🔄 刷新"):
        del st.session_state["data"]
        st.rerun()

for i, item in enumerate(data_list):
    df = item['df']
    with st.expander(f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}", expanded=True):
        fig = go.Figure()
        
        # 畫灰色箱型 (改為延展到今天)
        if item['box']:
            b = item['box']
            fig.add_shape(
                type="rect", 
                x0=b['start'], 
                x1=df.index[-1], # <--- 這裡改為延展到最後一根 K 棒
                y0=b['bottom'], 
                y1=b['top'],
                line=dict(width=0), 
                fillcolor="gray", 
                opacity=0.3
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
            xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
            yaxis=dict(side='right', tickfont=dict(size=11), fixedrange=True),
            hovermode=False
        )
        st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False}, key=f"p_{item['sid']}_{i}")