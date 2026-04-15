import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
import plotly.graph_objects as go
import time

# --- 1. 金虎南全能分析核心 ---
class KingTigerFullExpert:
    def __init__(self, df, market_df, total_capital):
        self.df = df.copy()
        self.market_df = market_df
        self.total_capital = total_capital
        
        # 指標計算
        self.df['MA5'] = self.df['Close'].rolling(window=5).mean()
        self.df['MA19'] = self.df['Close'].rolling(window=19).mean()
        self.df['MA60'] = self.df['Close'].rolling(window=60).mean()
        self.df['Vol_MA20'] = self.df['Volume'].rolling(window=20).mean()
        self.latest = self.df.iloc[-1]
        
    def get_market_status(self):
        if self.market_df is None or self.market_df.empty: return "⚪ 大盤同步中..."
        m_latest = self.market_df.iloc[-1]
        m_ma20 = self.market_df['Close'].rolling(window=20).mean().iloc[-1]
        return "🟢 大盤多頭" if m_latest['Close'] > m_ma20 else "🔴 大盤空頭"

    def get_signal_tags(self):
        tags = []
        if self.latest['MA5'] > self.latest['MA19']: tags.append("🔥 金牛交叉")
        else: tags.append("💀 死亡交叉")
        
        if len(self.df) >= 2:
            is_up_2d = self.df['Close'].iloc[-1] > self.df['Close'].iloc[-2]
            tags.append("✅ 2日強勢" if is_up_2d else "📉 2日整理")
            
        vol_dry = self.df['Volume'].tail(3).mean() < self.latest['Vol_MA20'] * 0.75
        if vol_dry: tags.append("💎 縮量緊湊")
        return " | ".join(tags)

# --- 2. 介面設定 ---
st.set_page_config(layout="wide", page_title="金虎南-雲端同步全能版")
st.title("🐅 金虎南 雲端戰鬥儀表板")

with st.sidebar:
    st.header("⚙️ 雲端與資金設定")
    total_capital = st.number_input("💵 總作戰資金 (NTD)", value=1000000)
    
    # --- 這裡是你最關心的試算表連動區 ---
    st.markdown("### 📋 試算表同步")
    sheet_id = st.text_input("Google Sheet ID", "你的試算表ID填在這裡")
    sheet_name = st.text_input("工作表名稱", "Sheet1")
    
    run_btn = st.button("🚀 讀取雲端名單並開始掃描")
    st.info("💡 程式會自動讀取第一欄作為股票代號")

if run_btn:
    try:
        # 1. 讀取 Google 試算表
        sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
        raw_data = pd.read_csv(sheet_url)
        tickers = raw_data.iloc[:, 0].dropna().tolist() # 自動抓第一欄
        st.success(f"✅ 成功讀取 {len(tickers)} 檔標的")
        
        # 2. 抓取大盤
        market_df = yf.download("^TWII", period="6mo", progress=False)
        if not market_df.empty and isinstance(market_df.columns, pd.MultiIndex):
            market_df.columns = market_df.columns.get_level_values(0)

        # 3. 逐一分析
        for ticker in tickers:
            ticker = str(ticker).strip()
            if not ticker: continue
            
            try:
                df = yf.download(ticker, period="1y", progress=False)
                if df.empty: continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                expert = KingTigerFullExpert(df, market_df, total_capital)
                
                # 繪製 K 線圖
                fig = go.Figure(data=[go.Candlestick(
                    x=df.index, open=df['Open'], high=df['High'],
                    low=df['Low'], close=df['Close'], name='K線'
                )])
                fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='yellow', width=1), name='5MA'))
                fig.add_trace(go.Scatter(x=df.index, y=df['MA19'], line=dict(color='orange', width=2), name='19MA'))
                fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='green', width=1.5), name='60MA'))
                fig.update_layout(height=450, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10))
                
                # 顯示
                st.write(f"### 📌 {ticker}")
                st.success(f"{expert.get_market_status()} | {expert.get_signal_tags()}")
                st.plotly_chart(fig, use_container_width=True)
                
                # 戰術數據
                buy_p = expert.latest['MA19'] * 1.015
                trail_p = max(df['Low'].tail(5).min(), expert.latest['MA19'])
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("🔥 1.5% 買入價", f"{buy_p:.2f}")
                c2.metric("📈 動態停利點", f"{trail_p:.2f}")
                c3.metric("🚫 10% 鋼鐵停損", f"{buy_p * 0.9:.2f}")
                c4.metric("💰 首筆試單 (20%)", f"${total_capital * 0.2:,.0f}")
                st.divider()

            except Exception as e:
                st.error(f"分析 {ticker} 失敗: {e}")

    except Exception as e:
        st.error(f"❌ 無法讀取試算表，請確認 ID 是否正確且權限已開啟（知道連結的人皆可檢視）。\n錯誤訊息: {e}")