# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# 1. 頁面標題
st.set_page_config(page_title="金虎南股票掃描器", layout="wide")
st.title("🐯 金虎南股票掃描器")

# 2. 原始輸入與數據邏輯 (完全保留你的 19/57 參數)
stock_id = st.text_input("輸入台股代號", "2324.TW")
df = yf.download(stock_id, period="1y")

if not df.empty:
    # 你的原始均線計算
    df['MA19'] = df['Close'].rolling(window=19).mean()
    df['MA57'] = df['Close'].rolling(window=57).mean()

    # 3. 畫圖區 (只改外觀)
    fig = go.Figure()

    # K線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'], name='K線'
    ))

    # 均線
    fig.add_trace(go.Scatter(x=df.index, y=df['MA19'], name='短均(19MA)', line=dict(color='#00FF00')))
    fig.add_trace(go.Scatter(x=df.index, y=df['MA57'], name='長均(57MA)', line=dict(color='#FF00FF')))

    # 成交量
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', yaxis='y2', marker=dict(opacity=0.3)))

    # --- 關鍵修正：背景變黑 + 中文字型 ---
    fig.update_layout(
        template="plotly_dark",  # 背景變黑
        font=dict(family="Microsoft JhengHei, sans-serif", size=14), # 修正中文
        height=600,
        xaxis_title="日期",
        yaxis_title="價格",
        yaxis2=dict(overlaying='y', side='right', showgrid=False),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False
    )

    st.plotly_chart(fig, use_container_width=True)

    # --- 4. 原始分析結果 (僅修正報錯那一行，邏輯不動) ---
    st.write("---")
    st.subheader("分析結果")
    
    # 修正 TypeError：強制轉為浮點數以利顯示
    price_val = float(df['Close'].iloc[-1].iloc[0]) if isinstance(df['Close'].iloc[-1], pd.Series) else float(df['Close'].iloc[-1])
    
    st.write(f"當前價格: {price_val:.2f}")
    
    # 這裡接你原本的 F 欄位判斷 (範例)
    ma19_val = float(df['MA19'].iloc[-1])
    if price_val > ma19_val:
        st.success("價格在 19MA 之上")
    else:
        st.warning("價格在 19MA 之下")
        
else:
    st.error("找不到數據")