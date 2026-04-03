import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南手機版-半年精準版")

# Google Sheet 網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    """穩定讀取邏輯：下載半年數據以確保長均線計算精準"""
    csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv&gid=0'
    try:
        # 使用 stream=True 確保大檔案讀取穩定
        res = requests.get(csv_url, timeout=10, stream=True)
        res.encoding = 'utf-8'
        if res.status_code != 200:
            return []
    except Exception:
        return []

    raw_df = pd.read_csv(io.StringIO(res.text))
    results = []

    for i, row in raw_df.iterrows():
        try:
            # 1. 檢查代號
            if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "":
                continue 
            
            # 2. 核心邏輯：沒訊號(F欄)不顯示
            sign = row.iloc[5] if pd.notna(row.iloc[5]) else ""
            if str(sign).strip() == "":
                continue 

            sid_raw = str(row.iloc[0]).split('.')[0].strip()
            sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma = pd.to_numeric(row.iloc[3], errors='coerce')
            vol = row.iloc[6] if pd.notna(row.iloc[6]) else ""

            # 【關鍵修改】：下載天數改為 6個月 (180d)，確保長均線計算穩定
            stock = yf.download(sid_full, period="180d", progress=False)
            
            if not stock.empty:
                if isinstance(stock.columns, pd.MultiIndex):
                    stock.columns = stock.columns.get_level_values(0)
                
                # 價格格式化到小數點兩位
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
    with st.spinner('數據同步中...'):
        st.session_state["data"] = run_scan()

# --- 3. 畫面顯示 ---
if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    # 頂部操作區
    col_t, col_b = st.columns([7, 3])
    with col_t:
        st.subheader("🐯 金虎南訊號")
    with col_b:
        if st.button("🔄 更新"):
            del st.session_state["data"]
            st.rerun()

    if not data_list:
        st.write("目前無偵測到訊號")
    else:
        # 直接顯示 Expander 清單
        for item in data_list:
            title_text = f"{item['sid']} {item['name']} ({item['price']}) ➔ {item['sign']} [{item['vol']}]"
            
            with st.expander(title_text, expanded=True):
                fig = go.Figure()
                
                # 繪製 K 線
                fig.add_trace(go.Candlestick(
                    x=item['df'].index, 
                    open=item['df']['Open'], high=item['df']['High'], 
                    low=item['df']['Low'], close=item['df']['Close'],
                    hoverinfo='none'
                ))
                
                # 均線繪圖 (依據半年數據計算)
                close_prices = item['df']['Close']
                if pd.notna(item['s_ma']):
                    ma_s = close_prices.rolling(window=int(item['s_ma'])).mean()
                    fig.add_trace(go.Scatter(x=item['df'].index, y=ma_s, line=dict(color='SpringGreen', width=1), hoverinfo='none'))
                
                if pd.notna(item['l_ma']):
                    ma_l = close_prices.rolling(window=int(item['l_ma'])).mean()
                    fig.add_trace(go.Scatter(x=item['df'].index, y=ma_l, line=dict(color='Magenta', width=1), hoverinfo='none'))
                
                # 圖表顯示範圍固定為最近一個月
                end_dt = item['df'].index[-1]
                start_dt = end_dt - pd.DateOffset(months=1)

                # --- 禁用所有縮放與工具箱，確保手機滑動穩定 ---
                fig.update_layout(
                    height=150,
                    showlegend=False,
                    template="plotly_dark",
                    hovermode=False,
                    dragmode=False,
                    xaxis_rangeslider_visible=False,
                    xaxis=dict(
                        range=[start_dt, end_dt],
                        rangebreaks=[dict(bounds=["sat", "mon"])],
                        tickfont=dict(size=8),
                        fixedrange=True # 禁止 X 軸縮放
                    ),
                    yaxis=dict(
                        side='right', 
                        tickfont=dict(size=8),
                        showgrid=True, gridcolor='rgba(128,128,128,0.1)',
                        fixedrange=True # 禁止 Y 軸縮放
                    ),
                    margin=dict(l=5, r=5, t=5, b=5),
                )
                
                # 以靜態模式邏輯渲染
                st.plotly_chart(fig, use_container_width=True, config={
                    'displayModeBar': False, 
                    'scrollZoom': False
                })