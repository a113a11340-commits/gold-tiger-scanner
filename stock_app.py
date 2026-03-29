# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 1. 頁面初始設定 (不影響邏輯) ---
st.set_page_config(page_title="金虎南行動版", layout="wide")
st.title("🐯 金虎南股票掃描器")

# --- 2. 你的原始輸入與數據計算邏輯 (完全保留) ---
stock_id = st.text_input("輸入台股代號", "2382.TW")
# 這裡維持你原本的 21MA/152MA 或 19/57 邏輯，我以 1y 為例確保長均線有資料
df = yf.download(stock_id, period="1y")

if not df.empty:
    # 這裡是你原本的計算公式，請確認名稱與你後續分析邏輯一致
    df['MA21'] = df['Close'].rolling(window=21).mean()
    df['MA152'] = df['Close'].rolling(window=152).mean()

    # --- 3. 畫圖區：只改圖面效果，不改數據 ---
    fig = go.Figure()

    # K線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'], name='K線'
    ))

    # 均線 (顏色依照你截圖的黃、紫設定)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA21'], name='短均(21MA)', line=dict(color='yellow')))
    fig.add_trace(go.Scatter(x=df.index, y=df['MA152'], name='長均(152MA)', line=dict(color='magenta')))

    # 成交量
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', yaxis='y2', marker=dict(opacity=0.3)))

    # --- 這裡就是你要求的：背景變黑 + 中文修正 ---
    fig.update_layout(
        template="plotly_dark", # 背景變黑
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
        xaxis_rangeslider_visible=False # 關閉下方滑桿讓手機更好滑
    )

    # 執行畫圖 (手機滑動關鍵)
    st.plotly_chart(fig, use_container_width=True)

    # --- 4. 你的原始 F 欄位分析邏輯 (完全保留，放在圖表下方) ---
    st.write("---")
    st.subheader("分析結果")
    
    # 這裡請接續你原本的 if price > ma ... 等判斷邏輯
    # 我預留一個位置，你可以把原本那段寫在這裡
    latest_price = df['Close'].iloc[-1]
    st.write(f"當前收盤價: {latest_price:.2f}")
    
else:
    st.error("找不到股票數據，請檢查代號是否正確。")