# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="金虎南股票掃描器", layout="wide")
st.title("🐯 金虎南股票掃描器")

stock_id = st.text_input("輸入台股代號", "2324.TW")
df = yf.download(stock_id, period="1y")

if not df.empty:
    # 你的原始均線邏輯，完全不動
    df['MA19'] = df['Close'].rolling(window=19).mean()
    df['MA57'] = df['Close'].rolling(window=57).mean()

    # 畫圖
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'], name='K線'
    ))
    fig.add_trace(go.Scatter(x=df.index, y=df['MA19'], name='短均(19MA)', line=dict(color='#00FF00')))
    fig.add_trace(go.Scatter(x=df.index, y=df['MA57'], name='長均(57MA)', line=dict(color='#FF00FF')))

    fig.update_layout(
        template="plotly_dark",
        font=dict(family="Microsoft JhengHei, Arial, sans-serif", size=14),
        height=600,
        xaxis_title="日期",
        yaxis_title="價格",
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False
    )

    # ⭐️ 致命傷修正：必須加上 theme=None，強制 Streamlit 吐出黑底和中文字體！
    st.plotly_chart(fig, theme=None, use_container_width=True)

    st.write("---")
    st.subheader("分析結果")
    
    # ⭐️ 崩潰修正：用 .values[-1] 抽出最乾淨的浮點數，保證程式絕對能順利往下跑
    latest_price = float(df['Close'].values[-1])
    st.write(f"當前價格: {latest_price:.2f}")
    
    # (你的 F 欄位判斷邏輯可以安心接在這裡)

else:
    st.error("找不到數據")