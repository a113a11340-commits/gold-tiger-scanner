# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 1. 頁面設定 ---
st.set_page_config(page_title="金虎南股票系統", layout="wide")
st.title("🐯 金虎南均線系統")

# --- 2. 數據抓取 (完全保留你的輸入邏輯) ---
stock_id = st.text_input("輸入股票代號 (如: 2324.TW)", "2324.TW")
df = yf.download(stock_id, period="1y")

if not df.empty:
    # --- 3. 均線計算 (完全保留你的天數設定) ---
    ma_s = 19
    ma_l = 57
    df['MA_S'] = df['Close'].rolling(window=ma_s).mean()
    df['MA_L'] = df['Close'].rolling(window=ma_l).mean()

    # --- 4. 繪圖區 (僅調整外觀，不動數據) ---
    fig = go.Figure()

    # K線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'], name='K線'
    ))

    # 均線 (依照你截圖的顏色：綠色與紫色)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], name=f'短均({ma_s}MA)', line=dict(color='#00FF00', width=2)))
    fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], name=f'長均({ma_l}MA)', line=dict(color='#FF00FF', width=2)))

    # 成交量
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', yaxis='y2', marker=dict(color='gray', opacity=0.3)))

    # --- 關鍵：背景變黑、中文修正、移除工具欄 ---
    fig.update_layout(
        template="plotly_dark", # 強制黑底
        font=dict(
            family="Microsoft JhengHei, Apple LiGothic, sans-serif", # 解決電腦與手機中文顯示
            size=14
        ),
        height=600,
        xaxis_title="日期",
        yaxis_title="價格",
        yaxis2=dict(overlaying='y', side='right', showgrid=False),
        xaxis_rangeslider_visible=False, # 隱藏下方滑桿
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        margin=dict(l=10, r=10, t=10, b=10)
    )

    # 顯示圖表並徹底隱藏右上方工具欄
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    # --- 5. 你的原始分析邏輯 (完全保留，接在圖表下方) ---
    st.write("---")
    st.subheader("數據分析")
    
    # 取得最新數據
    last_close = df['Close'].iloc[-1]
    last_ma_s = df['MA_S'].iloc[-1]
    last_ma_l = df['MA_L'].iloc[-1]
    
    # 這裡會跑你原本習慣的判斷邏輯
    st.write(f"當前價格: {last_close:.2f}")
    if last_close > last_ma_s:
        st.success("股價在短均線之上")
    else:
        st.warning("股價在短均線之下")

else:
    st.error("無法抓取數據，請確認代號是否正確。")