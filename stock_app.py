import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 設定與資料讀取 ---
st.set_page_config(layout="wide", page_title="技術分析監控")

# 試算表連結
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
SHEET_GIDS = ["0"] # 根據你的連結設定 gid=0

def run_scan():
    all_results = []
    for gid in SHEET_GIDS:
        csv_url = f"{MY_SHEET_URL}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=15)
            res.encoding = 'utf-8'
            if res.status_code != 200: continue
            raw_df = pd.read_csv(io.StringIO(res.text))
        except Exception: continue

        for i, row in raw_df.iterrows():
            try:
                # 檢查第一欄是否有代號
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
                
                # 讀取參數
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
                ma_p = pd.to_numeric(row.iloc[2], errors='coerce') # 短均線參數
                f_signal = str(row.iloc[5]) if len(row) > 5 and pd.notna(row.iloc[5]) else ""

                # 下載數據
                stock = yf.download(sid_full, period="240d", progress=False)
                if stock.empty: continue
                if isinstance(stock.columns, pd.MultiIndex): stock.columns = stock.columns.get_level_values(0)
                
                # 計算均線
                stock['MA_S'] = stock['Close'].rolling(window=int(ma_p)).mean()
                stock['MA_L'] = stock['Close'].rolling(window=60).mean() # 固定長均線 60
                
                # 掃描 2 個月內的箱型 (供目測用)
                view_df = stock.tail(42)
                boxes = []
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
                        boxes.append({'start': view_df.index[start_i], 'end': view_df.index[idx], 'top': w_max, 'bottom': w_min})
                    idx += 1
                
                all_results.append({
                    "sid": sid_full, "name": name, "df": stock, 
                    "f_signal": f_signal, "boxes": boxes, "ma_p": ma_p
                })
            except Exception: continue
    return all_results

# --- 2. 執行並呈現 ---
if "data" not in st.session_state:
    with st.spinner('讀取試算表數據中...'):
        st.session_state["data"] = run_scan()

for item in st.session_state["data"]:
    # 標題僅顯示：代號 名稱 ➔ F欄位訊號
    header = f"{item['sid']} {item['name']} ➔ {item['f_signal']}"
    
    with st.expander(header, expanded=True):
        df = item['df']
        fig = go.Figure()
        
        # 畫灰色箱型 (僅畫框，不畫紅線)
        for b in item['boxes']:
            fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                          line=dict(width=0), fillcolor="gray", opacity=0.25)

        # 畫 K 線
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                                     increasing_line_color='#d62728', decreasing_line_color='#2ca02c', name='K線'))
        
        # 畫 均線
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#1f77b4', width=2), name=f'{item["ma_p"]}MA'))
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#ff7f0e', width=1.5), name='60MA'))

        # 圖表佈局：固定 2 個月，移除下方拉升條 (rangeslider)
        fig.update_layout(
            xaxis=dict(
                type='category', 
                range=[len(df)-42, len(df)-0.5], 
                showticklabels=False,
                rangeslider=dict(visible=False) # 移除拉升條
            ),
            yaxis=dict(side='right'),
            height=350, 
            margin=dict(l=5, r=5, t=5, b=5), 
            template="plotly_white", 
            showlegend=False
        )

        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})