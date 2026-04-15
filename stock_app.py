import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
import plotly.graph_objects as go
import time

# --- 1. 金虎南全能分析核心 (嚴格依據參數) ---
class KingTigerStrictExpert:
    def __init__(self, df, market_df, total_capital, s_period, l_period):
        self.df = df.copy()
        self.market_df = market_df
        self.total_capital = total_capital
        
        # 處理參數：如果是 NaN 或 0 就設為 None
        self.s_period = int(s_period) if pd.notna(s_period) and s_period > 0 else None
        self.l_period = int(l_period) if pd.notna(l_period) and l_period > 0 else None
        
        # 動態計算均線
        if self.s_period:
            self.df['S_MA'] = self.df['Close'].rolling(window=self.s_period).mean()
        if self.l_period:
            self.df['L_MA'] = self.df['Close'].rolling(window=self.l_period).mean()
            
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
        # 只有當長短均線都有設定時，才判斷交叉
        if self.s_period and self.l_period:
            if self.latest['S_MA'] > self.latest['L_MA']:
                tags.append(f"🔥 金牛({self.s_period}/{self.l_period})")
            else:
                tags.append(f"💀 死亡({self.s_period}/{self.l_period})")
        
        if len(self.df) >= 2:
            is_up_2d = self.df['Close'].iloc[-1] > self.df['Close'].iloc[-2]
            tags.append("✅ 2日強勢" if is_up_2d else "📉 2日整理")
            
        vol_dry = self.df['Volume'].tail(3).mean() < self.latest['Vol_MA20'] * 0.75
        if vol_dry: tags.append("💎 縮量緊湊")
        return " | ".join(tags)

# --- 2. 介面設定 ---
st.set_page_config(layout="wide", page_title="金虎南-嚴格精準版")
st.title("🐅 金虎南 嚴格精準導航板")

SHEET_ID = "1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"

with st.sidebar:
    st.header("⚙️ 系統設定")
    total_capital = st.number_input("💵 總作戰資金 (NTD)", value=1000000)
    st.success("✅ 已鎖定試算表名單")
    run_btn = st.button("🚀 開始全自動掃描", use_container_width=True)

if run_btn:
    # 讀取工作表 1 (gid=0) 與 工作表 2 (gid=174175319) 
    # 提示：工作表 2 的 GID 可以在你瀏覽器網址最後面的 gid= 看到，我先放你提供的 0
    gids = ["0", "174175319"] # 請確認工作表2的正確GID
    all_data = []

    for gid in gids:
        try:
            url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
            tmp_df = pd.read_csv(url)
            all_data.append(tmp_df)
        except:
            continue

    if all_data:
        full_list = pd.concat(all_data).dropna(subset=[all_data[0].columns[0]])
        
        market_df = yf.download("^TWII", period="6mo", progress=False)
        if not market_df.empty and isinstance(market_df.columns, pd.MultiIndex):
            market_df.columns = market_df.columns.get_level_values(0)

        for _, row in full_list.iterrows():
            ticker = str(row.iloc[0]).strip()
            if not ticker or ticker == "nan": continue
            
            # 讀取均線，若為空則為 None
            s_val = row.iloc[1] if len(row) > 1 else None
            l_val = row.iloc[2] if len(row) > 2 else None

            try:
                df = yf.download(ticker, period="1y", progress=False)
                if df.empty: continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                expert = KingTigerStrictExpert(df, market_df, total_capital, s_val, l_val)
                
                # 繪圖
                fig = go.Figure(data=[go.Candlestick(
                    x=df.index, open=df['Open'], high=df['High'],
                    low=df['Low'], close=df['Close'], name='K線'
                )])
                
                # 有設定才畫線
                if expert.s_period:
                    fig.add_trace(go.Scatter(x=df.index, y=df['S_MA'], line=dict(color='yellow', width=1.5), name=f'{expert.s_period}MA'))
                if expert.l_period:
                    fig.add_trace(go.Scatter(x=df.index, y=df['L_MA'], line=dict(color='#FF9900', width=2.5), name=f'{expert.l_period}MA'))
                
                fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='#00FF00', width=1.5), name='60MA'))
                fig.update_layout(height=450, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10))
                
                # 顯示
                st.write(f"## 📌 {ticker}")
                st.success(f"{expert.get_market_status()} | {expert.get_signal_tags()}")
                st.plotly_chart(fig, use_container_width=True)
                
                # 戰術數據：只有當長均線存在時，才計算 1.5% 規則
                if expert.l_period:
                    buy_p = expert.latest['L_MA'] * 1.015
                    trail_p = max(df['Low'].tail(5).min(), expert.latest['L_MA'])
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"🔥 {expert.l_period}MA+1.5%", f"{buy_p:.2f}")
                    c2.metric("📈 動態停利點", f"{trail_p:.2f}")
                    c3.metric("🚫 10% 鋼鐵停損", f"{buy_p * 0.9:.2f}")
                    c4.metric("💰 建議試單 (20%)", f"${total_capital * 0.2:,.0f}")
                else:
                    st.info("💡 該標的未設定長均線參數，跳過戰術計算。")
                st.divider()

            except Exception as e:
                st.error(f"分析 {ticker} 出錯: {e}")