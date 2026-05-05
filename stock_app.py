import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

st.set_page_config(layout="wide", page_title="金虎南-精密訊號監控")

# --- 1. 讀取 Google Sheets 標的 ---
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
GIDS = ["0", "1241939414", "534437042", "1019044698"]

def run_scan():
    all_targets = []
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

    if not all_targets: return [], "讀取 Sheet 失敗"

    results = []
    last_diag = "掃描開始"
    
    # --- 2. 數據抓取與判定 (同步 GAS 邏輯) ---
    for item in all_targets:
        try:
            sid = item['sid']
            tk = yf.Ticker(sid)
            
            # 【關鍵：改用 history(1d) 抓取當前價，避開不穩定的 fast_info】
            today_data = tk.history(period="1d")
            if today_data.empty: continue
            curr_p = float(today_data['Close'].iloc[-1]) # 這就是 GAS 的 regularMarketPrice

            # 抓取 150 天歷史資料算均線
            hist = tk.history(period="150d")
            hist.dropna(subset=['Close'], inplace=True)
            if len(hist) < 2: continue

            s_day = int(item['s_ma_p']) if pd.notna(item['s_ma_p']) else 0
            if s_day <= 0: continue
            
            # 建立 pList：[今日即時價, 昨日收盤, 前日收盤...]
            hist_list = hist['Close'].tolist()
            p_list = [curr_p] + hist_list[::-1][1:] 

            # 均線計算邏輯與 GAS 一致
            def calc_ma(arr, period, offset):
                sub = arr[offset : offset + period]
                return sum(sub) / period if len(sub) == period else 0

            curr_ma = calc_ma(p_list, s_day, 0)
            prev_ma = calc_ma(p_list, s_day, 1)
            prev_p = p_list[1] # 歷史收盤最後一筆

            # 突破判定
            is_break_above = (prev_p <= prev_ma) and (curr_p > curr_ma)
            is_break_below = (prev_p >= prev_ma) and (curr_p < curr_ma)

            if is_break_above or is_break_below:
                # 更新畫圖用的 Dataframe
                hist.iloc[-1, hist.columns.get_loc('Close')] = curr_p
                hist['MA_S'] = hist['Close'].rolling(window=s_day).mean()
                
                l_val = item.get('l_ma_p')
                hist['MA_L'] = hist['Close'].rolling(window=int(l_val)).mean() if pd.notna(l_val) else None

                bias = ((curr_p - curr_ma) / curr_ma) * 100
                trend = "⤴️" if curr_ma > prev_ma else "⤵️"
                item.update({
                    "df": hist,
                    "sign": f"{'🚀突破' if is_break_above else '🚨跌破'} {s_day}MA({trend}) | 即時:{curr_p:.2f} | MA:{curr_ma:.2f} | 乖離:{bias:.2f}%",
                })
                results.append(item)
            
            last_diag = f"最後執行: {sid} 價:{curr_p:.1f}"
        except Exception as e:
            last_diag = f"錯誤: {sid} {str(e)}"
            continue
            
    return results, last_diag

# --- 3. 介面呈現 ---
col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-精密訊號過濾系統")
with col_b:
    if st.button("🔄 重新掃描"):
        if "data" in st.session_state: del st.session_state["data"]
        st.rerun()

if "data" not in st.session_state:
    with st.spinner('數據同步中...'):
        res, diag = run_scan()
        st.session_state["data"] = res
        st.session_state["diag"] = diag

data_list = st.session_state.get("data", [])

if not data_list:
    st.info(f"目前尚無符合訊號。({st.session_state.get('diag', '無診斷資訊')})")
else:
    for i, item in enumerate(data_list):
        df = item['df']
        with st.expander(f"{item['sid']} {item['name']} ➔ {item['sign']}", expanded=True):
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', decreasing_line_color='#2A9D8F'
            ))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], name="短MA", line=dict(color='#0055CC', width=2)))
            
            t_len = len(df)
            fig.update_layout(
                height=380, showlegend=False, xaxis_rangeslider_visible=False,
                margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[t_len-42, t_len-0.5], showticklabels=False, fixedrange=True),
                yaxis=dict(side='right', fixedrange=True),
                hovermode=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}, key=f"ch_{item['sid']}")