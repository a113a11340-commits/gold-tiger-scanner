import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-區間監控版")

MY_SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
GIDS = ["0", "1241939414", "534437042"]

def run_scan():
    all_raw_rows = []
    for gid in GIDS:
        csv_url = f"{MY_SHEET_BASE}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=15)
            res.encoding = 'utf-8'
            if res.status_code == 200:
                df_part = pd.read_csv(io.StringIO(res.text))
                all_raw_rows.append(df_part)
        except Exception: continue

    if not all_raw_rows: return []
    raw_df = pd.concat(all_raw_rows, ignore_index=True)

    temp_rows = []
    all_sids_set = set()
    for i, row in raw_df.iterrows():
        if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
        sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
        if sign == "": continue 
        
        sid_raw = str(row.iloc[0]).split('.')[0].strip()
        sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
        all_sids_set.add(sid_full)
        temp_rows.append({'sid_full': sid_full, 'row': row, 'sign': sign})

    if not temp_rows: return []

    download_list = list(all_sids_set)
    # 下載 200 天確保長均線有足夠數據計算
    all_data = yf.download(download_list, period="200d", progress=False, group_by='ticker')
    
    results = []
    for item in temp_rows:
        try:
            sid_full = item['sid_full']
            row = item['row']
            sign = item['sign']
            
            stock = all_data[sid_full].copy() if len(download_list) > 1 else all_data.copy()
            if isinstance(stock.columns, pd.MultiIndex):
                stock.columns = stock.columns.get_level_values(0)
            
            stock.dropna(subset=['Close'], inplace=True)
            if stock.empty: continue

            # 均線處理：若試算表空白則不顯示
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_val = pd.to_numeric(row.iloc[2], errors='coerce')
            l_val = pd.to_numeric(row.iloc[3], errors='coerce')
            
            if pd.notna(s_val): stock['MA_S'] = stock['Close'].rolling(window=int(s_val)).mean()
            if pd.notna(l_val): stock['MA_L'] = stock['Close'].rolling(window=int(l_val)).mean()
            
            # 箱型偵測邏輯：尋找最新的一個符合連續 3 天 3% 內的區間
            view_df = stock.tail(42)
            best_box = None
            if len(view_df) >= 3:
                idx = 0
                while idx < len(view_df) - 2:
                    w = view_df.iloc[idx:idx+3]
                    w_max, w_min = w['High'].max(), w['Low'].min()
                    # 判斷是否連續 3 天波動在 3% 內
                    if (w_max - w_min) / (w_min if w_min > 0 else 1) <= 0.03:
                        start_i = idx
                        # 往右延伸，直到股價離開原本 3 天定義的範圍 (加上 1.5% 寬容度)
                        while idx < len(view_df) - 1:
                            nr = view_df.iloc[idx+1]
                            if nr['Low'] >= w_min * 0.985 and nr['High'] <= w_max * 1.015:
                                idx += 1
                            else:
                                break
                        # 儲存箱型區間
                        best_box = {
                            'start': view_df.index[start_i], 
                            'end': view_df.index[idx], # 這就是「往右延伸但離開區間就停止」的點
                            'top': w_max, 
                            'bottom': w_min
                        }
                    idx += 1

            latest_p = float(stock['Close'].iloc[-1])
            results.append({
                "sid": sid_full, "name": name, "price": latest_p, "sign": sign, "df": stock, "box": best_box 
            })
        except Exception: continue
    return results

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    with st.spinner('讀取訊號中...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-訊號監控")
with col_b:
    if st.button("🔄 刷新"):
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
            
            # --- 箱型：僅畫出偵測到的區間，不延生至最新根 ---
            if item['box']:
                b = item['box']
                fig.add_shape(
                    type="rect", 
                    x0=b['start'], 
                    x1=b['end'], # 僅延伸到盤整結束的那一天，不再往左或無止盡往右
                    y0=b['bottom'], 
                    y1=b['top'],
                    line=dict(color="gray", width=1), 
                    fillcolor="gray", 
                    opacity=0.3,
                    layer="below"
                )

            # K線圖
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F',
                line=dict(width=1.2)
            ))
            
            # 均線繪製 (欄位存在才畫)
            if 'MA_S' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#0055CC', width=2.5), name="短均"))
            if 'MA_L' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#888888', width=1, dash='dot'), name="長均"))

            # 修正 X 軸範圍以防空白圖表
            display_start = max(0, total_len - 42)
            
            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False,
                margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[display_start, total_len - 0.5], showticklabels=False, fixedrange=True),
                yaxis=dict(side='right', tickfont=dict(size=11), fixedrange=True),
                hovermode=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False})