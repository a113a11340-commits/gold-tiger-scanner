# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 1. 頁面設定 ---
st.set_page_config(page_title="金虎南股票掃描器", layout="wide")
st.title("🐯 金虎南股票掃描器")

# --- 2. 原始數據邏輯 (不改動) ---
stock_id = st.text_input("輸入台股代號", "2382.TW")
df = yf.download(stock_id, period="1y")

if not df.empty:
    # 均線計算邏輯
    df['MA19'] = df['Close'].rolling(window=19).mean()
    df['MA57'] = df['Close'].rolling(window=57).mean()

    # --- 3. 畫圖區：加入黑底與中文設定 ---
    fig = go.Figure()

    # K線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'], name='K線'
    ))

    # 均線
    fig.add_trace(go.Scatter(x=df.index, y=df['MA19'], name='短均(19MA)', line=dict(color='#00FF00'))) # 亮綠色
    fig.add_trace(go.Scatter(x=df.index, y=df['MA57'], name='長均(57MA)', line=dict(color='#FF00FF'))) # 桃紅色

    # --- 關鍵修正：背景變黑 + 中文字型 ---
    fig.update_layout(
        template="plotly_dark", # 讓背景變黑
        font=dict(
            family="Microsoft JhengHei, Apple LiGothic, sans-serif", # 修正中文亂碼
            size=14
        ),
        height=600,
        xaxis_title="日期",
        yaxis_title="價格",
        yaxis2=dict(overlaying='y', side='right', showgrid=False),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False # 隱藏下方滑桿，讓畫面更清爽
    )

    # 顯示圖表
    st.plotly_chart(fig, use_container_width=True)

    # --- 4. 你的原始分析邏輯 (完全保留在下方) ---
    st.write("---")
    st.subheader("分析結果")
    # 此處會自動跑你原本寫好的 F 欄位判斷邏輯
    latest_price = df['Close'].iloc[-1]
    st.write(f"當前價格: {latest_price:.2f}")
    
else:
    st.error("找不到數據，請確認代號。")