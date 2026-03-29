import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 1. 手機版版面優化設定 ---
st.set_page_config(page_title="金虎南行動版", layout="wide")
st.title("🐯 金虎南行動掃描器")

# --- 2. 參數設定 (同步 333/111 邏輯) ---
stock_id = st.text_input("輸入台股代號 (如: 2382.TW)", "2382.TW")
ma_short_days = 21   # 短均
ma_long_days = 152   # 長均

# --- 3. 抓取數據 ---
df = yf.download(stock_id, period="1y")

if not df.empty:
    # 計算均線並四捨五入
    df['MA_S'] = df['Close'].rolling(window=ma_short_days).mean().round(2)
    df['MA_L'] = df['Close'].rolling(window=ma_long_days).mean().round(2)
    
    # --- 4. 繪製全中文黑底互動圖表 ---
    fig = go.Figure()

    # K線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'], name='K線'
    ))

    # 短均 (黃線)
    fig.add_trace(go.Scatter(
        x=df.index, y=df['MA_S'], name=f'短均({ma_short_days}MA)',
        line=dict(color='yellow', width=2)
    ))

    # 長均 (紅線)
    fig.add_trace(go.Scatter(
        x=df.index, y=df['MA_L'], name=f'長均({ma_long_days}MA)',
        line=dict(color='red', width=2)
    ))

    # 成交量
    fig.add_trace(go.Bar(
        x=df.index, y=df['Volume'], name='成交量',
        yaxis='y2', marker=dict(color='gray', opacity=0.3)
    ))

    # --- 5. 關鍵修正：強制黑底與中文座標 ---
    fig.update_layout(
        template="plotly_dark", # 讓手機背景變黑色
        height=700,             # 增加高度，手機滑動更清楚
        xaxis_title="日期",
        yaxis_title="價格 (台幣)",
        yaxis2=dict(overlaying='y', side='right', showgrid=False),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        margin=dict(l=5, r=5, t=10, b=10), # 縮小邊距讓圖表填滿手機螢幕
    )

    # 顯示圖表
    st.plotly_chart(fig, use_container_width=True)
    
    # 顯示 F 欄位簡單訊號 (範例)
    last_price = df['Close'].iloc[-1].values[0] if hasattr(df['Close'].iloc[-1], 'values') else df['Close'].iloc[-1]
    st.write(f"當前價格：{round(float(last_price), 2)}")
else:
    st.error("找不到股票數據")