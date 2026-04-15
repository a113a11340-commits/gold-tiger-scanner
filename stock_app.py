import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np

# --- 1. 金虎南終極交易大腦 (邏輯封裝) ---
class KingTigerUltimateExpert:
    def __init__(self, df, market_df, total_capital):
        self.df = df.copy()
        self.market_df = market_df
        self.total_capital = total_capital
        
        # 基礎指標計算
        self.df['MA5'] = self.df['Close'].rolling(window=5).mean()
        self.df['MA19'] = self.df['Close'].rolling(window=19).mean() # 影片愛用 19MA
        self.df['MA50'] = self.df['Close'].rolling(window=50).mean()
        self.df['MA200'] = self.df['Close'].rolling(window=200).mean()
        self.df['Vol_MA20'] = self.df['Volume'].rolling(window=20).mean()
        
        self.latest = self.df.iloc[-1]
        self.prev = self.df.iloc[-5] # 用於比對斜率

    def check_market_environment(self):
        """傑西·李佛摩：由上而下大盤濾網"""
        if self.market_df is None or self.market_df.empty:
            return "⚪ 大盤資料未載入"
            
        m_latest = self.market_df.iloc[-1]
        m_ma20 = self.market_df['Close'].rolling(window=20).mean().iloc[-1]
        
        if m_latest['Close'] > m_ma20:
            return "🟢 大盤多頭 (李佛摩許可進場)"
        else:
            return "🔴 大盤空頭 (李佛摩建議觀望)"

    def analyze_ma_and_dow(self):
        """均線語言與道氏結構"""
        m5, m19, m50 = self.latest['MA5'], self.latest['MA19'], self.latest['MA50']
        
        # 均線糾結與發散
        cv = np.std([m5, m19, m50]) / np.mean([m5, m19, m50])
        is_bullish = m5 > m19 > m50
        slope_19 = (m19 - self.prev['MA19']) / self.prev['MA19']
        
        ma_msg = "🤫 均線糾結" if cv < 0.02 else ("💥 多頭發散" if is_bullish else "🔄 整理中")
        if slope_19 > 0.08: ma_msg += " (⚠️ 角度過陡)"
        
        # 道氏理論 (底底高)
        recent_lows = self.df['Low'].tail(30).rolling(window=5).min()
        is_hl = self.latest['Low'] > recent_lows.iloc[-10] # 低點墊高
        dow_msg = "🛡️ 道氏底底高" if is_hl else "🌪️ 結構破壞"
        
        return f"{dow_msg} | {ma_msg}"

    def detect_vcp_and_pivotal(self):
        """VCP 收縮與李佛摩關鍵點突破"""
        # VCP 邏輯
        d = self.df.tail(60)
        depth_60 = (d['High'].max() - d['Low'].min()) / d['High'].max()
        depth_12 = (self.df['High'].tail(12).max() - self.df['Low'].tail(12).min()) / self.df['High'].tail(12).max()
        vol_dry = self.df['Volume'].tail(3).mean() < self.latest['Vol_MA20'] * 0.75
        
        vcp_msg = ""
        if depth_60 > 0.15 and depth_12 < 0.08 and vol_dry:
            vcp_msg = "💎 VCP 緊湊點"

        # 李佛摩關鍵點 (Pivotal Point)：接近前高且帶量
        recent_high = d['High'].max()
        vol_spike = self.latest['Volume'] > self.latest['Vol_MA20'] * 1.5
        pivotal_msg = "🎯 關鍵點突破" if (self.latest['Close'] >= recent_high * 0.98 and vol_spike) else ""
        
        return " | ".join(filter(None, [vcp_msg, pivotal_msg])) or "無特殊形態"

    def calculate_tactics_and_risk(self):
        """金唬男 1.5% + 達華斯紀律 + 李佛摩資金管理"""
        price = self.latest['Close']
        ma19 = self.latest['MA19']
        
        # 1. 進場點 (MA19 + 1.5%)
        buy_trigger = ma19 * 1.015
        
        # 2. 達華斯動態停利 (前 5 日低點與 MA19 取高)
        trailing_stop = max(self.df['Low'].tail(5).min(), ma19)
        
        # 3. 李佛摩 10% 鋼鐵停損與部位控管
        # 假設在 buy_trigger 進場
        hard_stop = buy_trigger * 0.90 
        
        # 試單配比：第一筆最多 20% (李佛摩)，或 1% 總風險原則
        # 若停損距離是 10%，投入 10% 資金剛好等於總風險 1%
        test_unit_pct = min(0.20, 0.01 / 0.10) 
        test_amount = self.total_capital * test_unit_pct
        
        return {
            "buy": buy_trigger,
            "trailing": trailing_stop,
            "hard_stop": hard_stop,
            "test_amount": test_amount
        }

# --- 2. Streamlit 網頁介面 ---
st.set_page_config(layout="wide", page_title="金虎南-終極旗艦版")
st.title("🐅 金虎南 量化交易戰術板 (Livermore Edition)")

# 側邊欄設定
with st.sidebar:
    st.header("⚙️ 戰略設定")
    total_capital = st.number_input("💵 總作戰資金 (NTD)", value=1000000, step=100000)
    
    st.markdown("### 📝 觀察名單 (台股代號)")
    st.caption("每行一個代號，例如 2330.TW")
    # 這裡你可以後續替換成從 Google Sheet 讀取的代碼
    tickers_input = st.text_area("輸入代號", "2330.TW\n2303.TW\n2308.TW\n3231.TW\n2376.TW", height=150)
    
    run_btn = st.button("🚀 啟動全局掃描")

if run_btn:
    tickers = [t.strip() for t in tickers_input.split('\n') if t.strip()]
    
    with st.spinner('📊 正在獲取大盤與個股數據...'):
        # 獲取大盤數據 (加權指數)
        market_df = yf.download("^TWII", period="6mo", progress=False)
        if isinstance(market_df.columns, pd.MultiIndex): 
            market_df.columns = market_df.columns.get_level_values(0)
            
        # 迴圈處理每檔股票
        for ticker in tickers:
            try:
                df = yf.download(ticker, period="1y", progress=False)
                if df.empty: continue
                if isinstance(df.columns, pd.MultiIndex): 
                    df.columns = df.columns.get_level_values(0)
                
                # 初始化專家系統
                expert = KingTigerUltimateExpert(df, market_df, total_capital)
                
                # 取得各項分析報告
                market_status = expert.check_market_environment()
                ma_dow_status = expert.analyze_ma_and_dow()
                pattern_status = expert.detect_vcp_and_pivotal()
                tactics = expert.calculate_tactics_and_risk()
                
                # --- UI 渲染區塊 ---
                with st.container():
                    st.subheader(f"📌 {ticker} - 最新收盤價: {expert.latest['Close']:.2f}")
                    
                    # 大盤與形態警示
                    if "🔴" in market_status:
                        st.warning(f"{market_status} | {ma_dow_status} | {pattern_status}")
                    else:
                        st.success(f"{market_status} | {ma_dow_status} | {pattern_status}")
                    
                    # 數據儀表板
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric(label="🔥 1.5% 預約買入價", value=f"{tactics['buy']:.2f}", 
                                  help="金唬男法則：19MA 向上 1.5% 確認動能")
                    with col2:
                        st.metric(label="📈 達華斯動態停利", value=f"{tactics['trailing']:.2f}", 
                                  help="只要沒跌破此價位，放任獲利奔跑")
                    with col3:
                        st.metric(label="🚫 李佛摩鋼鐵停損", value=f"{tactics['hard_stop']:.2f}", 
                                  help="絕對底線：買入價跌 10% 無條件退場")
                    with col4:
                        st.metric(label="💰 李佛摩首筆試單", value=f"${tactics['test_amount']:,.0f}", 
                                  help="符合 1% 總風險原則的測試單資金")
                    
                    st.divider()
            
            except Exception as e:
                st.error(f"分析 {ticker} 時發生錯誤: {e}")

    st.success("🎉 掃描完成！請依據『大盤環境』與『達華斯紀律』進行操作。")