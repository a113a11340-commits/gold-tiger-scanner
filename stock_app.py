import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io
import datetime

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南手機版")

# 你的 Google Sheet 網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    """讀取試算表並進行訊號過濾 (維持原本穩定結構)"""
    csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv&gid=0'
    try:
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        if res.status_code != 200:
            return []
    except Exception:
        return []

    raw_df = pd.read_csv(io.StringIO(res.text))
    results = []

    for i, row in raw_df.iterrows():
        try:
            if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "":
                continue 
            
            # F 欄訊號檢查
            sign = row.iloc[5] if pd.notna(row.iloc[5]) else ""
            if str(sign).strip() == "":
                continue 

            sid_raw = str(row.iloc[0]).split('.')[0].strip()
            sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma = pd.to_numeric(row.iloc[3], errors='coerce')
            
            # G 欄量能
            vol = row.iloc[6] if pd.notna(row.iloc[6]) else ""

            # 下載資料
            stock = yf.download(sid_full, period="250d", progress=False)
            
            if not stock.empty:
                if isinstance(stock.columns, pd.MultiIndex):
                    stock.columns = stock.columns.get_level_values(0)
                
                # 強制格式化現價為兩位小數
                latest_price_raw = float(stock['Close'].dropna().iloc[-1])
                formatted_price = f"{latest_price_raw:.2f}"
                
                results.append({
                    "sid": sid_full, "name": name, "price": formatted_price,
                    "s_ma": s_ma, "l_ma": l_ma, "sign": sign, "vol": vol, "df": stock
                })
        except Exception:
            continue
    return results

# --- 2. 執行與快取 ---
if "data" not in st.session_state:
    with st.spinner('連線中...'):
        st.session_state["data"] = run_scan()

# --- 3. 畫面顯示 (已移除上方表格) ---
if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    # 標題列
    col_t, col_b = st.columns([8, 2])
    with col_t:
        st.subheader("🐯 金虎南訊號")
    with col_b:
        if st.button("🔄 更新"):
            del st.session_state["data"]
            st.rerun()

    if not data_list:
        st.write("目前無訊號")
    else:
        # --- 這裡已移除表格代碼 ---

        # 顯示 K 線圖清單
        for item in data_list:
            # 組合標題：包含量能 (G欄)
            title_text = f"{item['sid']} {item['name']} ({item['price']}) ➔ {item['sign']} [量能:{item['vol']}]"
            
            with st.expander(title_text, expanded=True):
                fig = go.Figure()
                
                # K 線
                fig.add_trace(go.Candlestick(
                    x=item['df'].index, 
                    open=item['df']['Open'], high=item['df']['High'], 
                    low=item['df']['Low'], close=item['df']['Close']
                ))
                
                # 均線
                close_prices = item['df']['Close']
                if pd.notna(item['s_ma']):
                    ma_s = close_prices.rolling(window=int(item['s_ma'])).mean()
                    fig.add_trace(go.Scatter(x=item['df'].index, y=ma_s, line=dict(color='SpringGreen', width=1)))
                
                if pd.notna(item['l_ma']):
                    ma_l = close_prices.rolling(window=int(item['l_ma'])).mean()
                    fig.add_trace(go.Scatter(x=item['df'].index, y=ma_l, line=dict(color='Magenta', width=1)))
                
                # 計算一個月範圍
                end_dt = item['df'].index[-1]
                start_dt = end_dt - pd.DateOffset(months=1)

                # 圖表佈局設定
                fig.update_layout(
                    height=150, # 高度 150
                    showlegend=False, # 移除均線與 K 線按鈕 (圖例)
                    template="plotly_dark",
                    xaxis_rangeslider_visible=False,
                    xaxis=dict(
                        range=[start_dt, end_dt], # 只顯示一個月
                        rangebreaks=[dict(bounds=["sat", "mon"])],
                        tickfont=dict(size=8)
                    ),
                    yaxis=dict(
                        side='right', 
                        tickfont=dict(size=8),
                        showgrid=True, gridcolor='rgba(128,128,128,0.2)'
                    ),
                    margin=dict(l=5, r=5, t=5, b=5),
                )
                
                # 移除工具箱配置
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})