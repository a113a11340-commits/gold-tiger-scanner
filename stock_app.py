import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-精密訊號監控")

# 這裡請確認你的網址與分頁 GID 是否正確
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
GIDS = ["0", "1241939414", "534437042", "1019044698"]

def run_scan():
    all_targets = []
    
    # --- 步驟 1: 讀取所有分頁標的 ---
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
    # 抓取 120 天數據以確保均線計算正確
    full_data = yf.download(tickers, period="120d", progress=False, group_by='ticker')

    results = []
    for item in all_targets:
        try:
            sid = item['sid']
            stock = full_data[sid].copy() if len(tickers) > 1 else full_data.copy()
            stock.dropna(subset=['Close'], inplace=True)
            
            if not stock.empty:
# --- 修改後的均線計算區塊 ---
if not stock.empty:
    # 1. 讀取設定，不設預設值
    s_val = item.get('s_ma_p')
    l_val = item.get('l_ma_p')

    # 2. 核心邏輯：如果沒填短均線，就無法判斷突破，直接跳過這檔
    if pd.isna(s_val): 
        continue 
    
    s_day = int(s_val)
    stock['MA_S'] = stock['Close'].rolling(window=s_day).mean()

    # 3. 長均線有填才計，沒填就給 None (不影響突破判斷)
    if pd.notna(l_val):
        l_day = int(l_val)
        stock['MA_L'] = stock['Close'].rolling(window=l_day).mean()
    else:
        l_day = "未設定"
        stock['MA_L'] = None

    # --- 均線精密數據與過濾邏輯 ---
    curr_p = float(stock['Close'].iloc[-1])
    prev_p = float(stock['Close'].iloc[-2])
    ma_s = stock['MA_S']
    
    # 檢查是否有足夠數據計算均線
    if len(ma_s) < 2 or pd.isna(ma_s.iloc[-1]) or pd.isna(ma_s.iloc[-2]): 
        continue
    
    curr_ma_s = float(ma_s.iloc[-1])
    prev_ma_s = float(ma_s.iloc[-2])
    
    # ... (後續 is_break_above 邏輯維持不變)
                
                # --- 均線精密數據與過濾邏輯 ---
                curr_p = float(stock['Close'].iloc[-1])
                prev_p = float(stock['Close'].iloc[-2])
                ma_s = stock['MA_S']
                
                if pd.isna(ma_s.iloc[-1]) or pd.isna(ma_s.iloc[-2]): continue
                
                curr_ma_s = float(ma_s.iloc[-1])
                prev_ma_s = float(ma_s.iloc[-2])
                
                # --- 核心過濾：只抓「突破」或「跌破」的瞬間 ---
                is_break_above = (prev_p <= prev_ma_s) and (curr_p > curr_ma_s)
                is_break_below = (prev_p >= prev_ma_s) and (curr_p < curr_ma_s)
                
                # 若無訊號則跳過，不存入結果清單
                if not (is_break_above or is_break_below):
                    continue

                # 1. 計算乖離率
                bias = ((curr_p - curr_ma_s) / curr_ma_s) * 100
                
                # 2. 判定均線方向
                ma_trend = "⤴️上揚" if curr_ma_s > prev_ma_s else "⤵️下彎"
                
                # 3. 決定狀態字串
                sign_icon = "🚀 剛突破" if is_break_above else "🚨 剛跌破"
                status = (
                    f"{sign_icon} {s_day}MA ({ma_trend}) | "
                    f"現價: {curr_p:.2f} | "
                    f"{s_day}MA價: {curr_ma_s:.2f} | "
                    f"乖離: {bias:.2f}%"
                )
                
                # --- 箱型演算法 ---
                view_df = stock.tail(42)
                best_box = None
                idx = 0
                while idx < len(view_df) - 2:
                    w = view_df.iloc[idx:idx+3]
                    w_max, w_min = w['High'].max(), w['Low'].min()
                    if (w_max - w_min) / w_min <= 0.03:
                        c_i = idx + 1
                        while c_i < len(view_df):
                            nr = view_df.iloc[c_i]
                            if nr['Low'] < w_min * 0.985 or nr['High'] > w_max * 1.015: break
                            c_i += 1
                        best_box = {'start': view_df.index[idx], 'end': view_df.index[c_i-1], 'top': w_max, 'bottom': w_min}
                        idx = c_i
                    else: idx += 1

                item.update({"price": curr_p, "df": stock, "box": best_box, "sign": status})
                results.append(item)
        except Exception: continue
    return results

# --- 3. 介面呈現 ---
if "data" not in st.session_state:
    with st.spinner('正在掃描具備進出訊號的標的...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-精密訊號過濾系統")
with col_b:
    if st.button("🔄 重新掃描訊號"):
        del st.session_state["data"]
        st.rerun()

if not data_list:
    st.success("目前所有監控標的均在趨勢中，尚無「剛突破」或「剛跌破」的即時訊號。")
else:
    st.warning(f"偵測到 {len(data_list)} 檔標的出現進出訊號！")
    for i, item in enumerate(data_list):
        df = item['df']
        t_len = len(df)
        header = f"{item['sid']} {item['name']} ➔ {item['sign']}"
        
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
            
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], name="短期均線", line=dict(color='#0055CC', width=2.5)))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], name="長期均線", line=dict(color='#888888', width=1, dash='dot')))

            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[t_len - 42, t_len - 0.5], showticklabels=False, fixedrange=True),
                yaxis=dict(side='right', tickfont=dict(size=11), fixedrange=True),
                hovermode=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}, key=f"ch_{item['sid']}_{i}")