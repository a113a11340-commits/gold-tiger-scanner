import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
import time

# --- 1. 金虎南終極交易大腦 ---
class KingTigerUltimateExpert:
    def __init__(self, df, market_df, total_capital):
        self.df = df.copy()
        self.market_df = market_df
        self.total_capital = total_capital
        
        # 基礎指標計算
        self.df['MA5'] = self.df['Close'].rolling(window=5).mean()
        self.df['MA19'] = self.df['Close'].rolling(window=19).mean()
        self.df['MA50'] = self.df['Close'].rolling(window=50).mean()
        self.df['Vol_MA20'] = self.df['Volume'].rolling(window=20).mean()
        
        self.latest = self.df.iloc[-1]
        self.prev = self.df.iloc[-5] if len(self.df) > 5 else self.df.iloc[0]

    def check_market_environment(self):
        if self.market_df is None or self.market_df.empty:
            return "⚪ 大盤資料獲取失敗"
        m_latest = self.market_df.iloc[-1]
        m_ma20 = self.market_df['Close'].rolling(window=20).mean().iloc[-1]
        return "🟢 大盤多頭 (許可進場)" if m_latest['Close'] > m_ma20 else "🔴 大盤空頭 (建議觀望)"

    def analyze_all(self):
        # 均線與道氏
        is_bullish = self.latest['MA5'] > self.latest['MA19'] > self.latest['MA50']
        dow_msg = "🛡️ 道氏底底高" if self.latest['Low'] > self.df['Low'].tail(20).min() else "🌪️ 結構整理"
        
        # VCP 與 關鍵點
        vol_dry = self.df['Volume'].tail(3).mean() < self.latest['Vol_MA20'] * 0.8
        pivotal = "🎯 關鍵點突破" if (self.latest['Close'] >= self.df['High'].tail(20).max() * 0.98) else ""
        
        # 戰術計算
        buy_trigger = self.latest['MA19'] * 1.015
        trailing_stop = max(self.df['Low'].tail(5).min(), self.latest['MA19'])
        hard_stop = buy_trigger * 0.90
        test_amount = self.total_capital * 0.10 # 預設試單 10%
        
        return {
            "status": f"{dow_msg} | {'💥 多頭發散' if is_bullish else '🔄 趨勢盤整'} | {pivotal}",
            "buy": buy_trigger, "trailing": trailing_stop, "hard_stop": hard_stop, "test": test_amount
        }

# --- 2. 介面介面 ---
st.set_page_config(layout="wide", page_title="金虎南-終極旗艦版")
st.title("🐅 金虎南 量化交易戰術板")

with st.sidebar:
    st.header("⚙️ 戰略設定")
    total_capital = st.number_input("💵 總作戰資金 (NTD)", value=1000000)
    tickers_input = st.text_area("輸入代號 (每行一個)", "2330.TW\n2317.TW\n2454.TW")
    run_btn = st.button("🚀 啟動全局掃描")

if run_btn:
    tickers = [t.strip() for t in tickers_input.split('\n') if t.strip()]
    
    # 抓取大盤
    with st.spinner('正在同步大盤數據...'):
        market_df = yf.download("^TWII", period="3mo", progress=False)
        if not market_df.empty and isinstance(market_df.columns, pd.MultiIndex):
            market_df.columns = market_df.columns.get_level_values(0)

    # 抓取個股
    for ticker in tickers:
        with st.status(f"正在分析 {ticker}...", expanded=True) as status:
            try:
                df = yf.download(ticker, period="1y", progress=False)
                if df.empty:
                    st.error(f"❌ 無法取得 {ticker} 數據，請檢查代號是否正確。")
                    continue
                
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                expert = KingTigerUltimateExpert(df, market_df, total_capital)
                m_env = expert.check_market_environment()
                res = expert.analyze_all()
                
                # 顯示結果
                st.write(f"### {ticker} 分析報告")
                if "🔴" in m_env: st.warning(m_env)
                else: st.success(m_env)
                
                st.write(f"**目前狀態：** {res['status']}")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("🔥 1.5% 買入價", f"{res['buy']:.2f}")
                c2.metric("📈 動態停利點", f"{res['trailing']:.2f}")
                c3.metric("🚫 10% 鋼鐵停損", f"{res['hard_stop']:.2f}")
                c4.metric("💰 建議試單金額", f"${res['test']:,.0f}")
                
                status.update(label=f"✅ {ticker} 分析完成", state="complete")
            except Exception as e:
                st.error(f"分析 {ticker} 時發生錯誤: {e}")