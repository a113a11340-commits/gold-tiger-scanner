import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np

# 1. 頁面基本設定
st.set_page_config(
    page_title="金虎男 - 純均線監控戰情室",
    page_icon="📈",
    layout="wide"
)

st.title("📈 金虎男 - 純均線監控戰情室")
st.caption("支援台股與美股均線扣抵、轉折點與斜率即時監控")

# 2. 資料獲取與快取函數
@st.cache_data(ttl=600)  # 快取 10 分鐘
def fetch_stock_data(ticker_symbol: str):
    """
    從 Yahoo Finance 抓取個股歷史資料，並處理台股代號格式
    """
    symbol = ticker_symbol.strip().upper()
    # 若輸入 4 位數台股代碼，自動補上 .TW
    if symbol.isdigit() and len(symbol) == 4:
        symbol += ".TW"
    
    try:
        stock = yf.Ticker(symbol)
        # 抓取足夠計算 240MA + 扣抵差值的歷史數據（約 1.5 年交易日）
        df = stock.history(period="2y")
        if df.empty:
            return None, symbol
        return df, symbol
    except Exception as e:
        return None, symbol

# 3. 均線核心計算邏輯
def calculate_ma_metrics(cls: list, ma_periods=[5, 10, 20, 60, 120, 240]):
    """
    cls 陣列說明（索引 index）：
    cls[0] : 今日收盤價 (Today)
    cls[1] : 昨日收盤價 (Yesterday)
    cls[2] : 前日收盤價 (Day before yesterday)
    ...
    cls[N-1] : 今日 MA_N 的扣抵值（明天將被扣掉的歷史價格）
    """
    results = []
    
    for p in ma_periods:
        # 確保歷史資料長度足夠計算 B_ma (需要至少 p + 2 天資料)
        if len(cls) >= p + 2:
            # 均線計算 (Slice 切片)
            t_ma = np.mean(cls[0:p])       # 當日均線 T_ma
            y_ma = np.mean(cls[1:p + 1])   # 昨日均線 Y_ma
            b_ma = np.mean(cls[2:p + 2])   # 前日均線 B_ma
            
            # 斜率與動能變化
            diff_today = t_ma - y_ma       # 今日均線增減量
            diff_yest = y_ma - b_ma        # 昨日均線增減量
            acceleration = diff_today - diff_yest  # 動能加速度
            
            # 扣抵與轉折關鍵價計算
            # 明天計算 MA_N 時，會扣除 cls[p-1]。
            # 因此明天收盤價若高於 cls[p-1]，MA_N 將繼續向上翻揚。
            koudi_tomorrow = cls[p - 1]
            koudi_diff = cls[0] - koudi_tomorrow # 當前股價比扣抵價高多少
            
            # 趨勢判定
            is_rising = t_ma > y_ma
            is_accelerating = acceleration > 0
            
            results.append({
                "均線週期": f"{p}MA",
                "當日均線 (T_ma)": round(t_ma, 2),
                "昨日均線 (Y_ma)": round(y_ma, 2),
                "前日均線 (B_ma)": round(b_ma, 2),
                "今日斜率 (T-Y)": round(diff_today, 2),
                "趨勢": "🟢 向上" if is_rising else "🔴 向下",
                "明日扣抵價": round(koudi_tomorrow, 2),
                "扣抵安全邊際": round(koudi_diff, 2),
                "扣抵狀態": "🟢 高於扣抵" if koudi_diff >= 0 else "🔴 低於扣抵"
            })
            
    return pd.DataFrame(results)

# 4. 側邊欄控制項
st.sidebar.header("🔍 股票查詢與設定")
stock_input = st.sidebar.text_input("輸入股票代號（例如：2330, 2454, AAPL, TSLA）", value="2330")

ma_selection = st.sidebar.multiselect(
    "選擇監控均線週期",
    options=[5, 10, 20, 60, 120, 240],
    default=[5, 10, 20, 60, 120, 240]
)

# 5. 主畫面執行
if stock_input:
    with st.spinner("正在抓取最新股價與均線資料..."):
        df_history, formatted_symbol = fetch_stock_data(stock_input)
        
    if df_history is None or df_history.empty:
        st.error(f"❌ 查無股票代號 `{formatted_symbol}` 的資料，請確認代碼是否正確。")
    else:
        # 取出 Close 收盤價，並反轉順序：索引 0 為最新的今天
        cls = df_history['Close'].iloc[::-1].tolist()
        latest_date = df_history.index[-1].strftime('%Y-%m-%d')
        latest_price = cls[0]
        prev_price = cls[1]
        price_change = latest_price - prev_price
        pct_change = (price_change / prev_price) * 100
        
        # 顯示頭部個股概況卡片
        st.subheader(f"📌 {formatted_symbol} 盤後即時指標（資料日期：{latest_date}）")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("當日收盤價", f"{latest_price:.2f}", f"{price_change:+.2f} ({pct_change:+.2f}%)")
        col2.metric("昨日收盤價", f"{prev_price:.2f}")
        col3.metric("前日收盤價", f"{cls[2]:.2f}")
        col4.metric("歷史數據天數", f"{len(cls)} 天")
        
        st.markdown("---")
        
        # 計算均線數據
        df_ma = calculate_ma_metrics(cls, ma_periods=sorted(ma_selection))
        
        if not df_ma.empty:
            st.subheader("📊 多週期均線扣抵與斜率分析表")
            
            # 使用條件高亮顯眼顯示
            st.dataframe(
                df_ma,
                column_config={
                    "均線週期": st.column_config.TextColumn("均線", help="觀察的均線天數"),
                    "當日均線 (T_ma)": st.column_config.NumberColumn("T_ma (今日)", format="%.2f"),
                    "昨日均線 (Y_ma)": st.column_config.NumberColumn("Y_ma (昨日)", format="%.2f"),
                    "前日均線 (B_ma)": st.column_config.NumberColumn("B_ma (前日)", format="%.2f"),
                    "今日斜率 (T-Y)": st.column_config.NumberColumn("均線變化量", format="%.2f"),
                    "明日扣抵價": st.column_config.NumberColumn("明日扣抵價", help="明日股價需高於此數值，均線才能維持向上"),
                    "扣抵安全邊際": st.column_config.NumberColumn("扣抵差值 (現價-扣抵)", format="%.2f")
                },
                hide_index=True,
                use_container_width=True
            )
            
            # 戰略重點提醒
            st.subheader("💡 隔日戰術預演解讀")
            rising_mas = df_ma[df_ma["趨勢"].str.contains("向上")]["均線週期"].tolist()
            falling_mas = df_ma[df_ma["趨勢"].str.contains("向下")]["均線週期"].tolist()
            
            bullet_points = [
                f"**多頭向上均線**：{', '.join(rising_mas) if rising_mas else '無'}",
                f"**空頭向下均線**：{', '.join(falling_mas) if falling_mas else '無'}"
            ]
            
            for ma_row in df_ma.itertuples():
                if ma_row.扣抵安全邊際 < 0:
                    bullet_points.append(
                        f"⚠️ **{ma_row.均線週期} 警訊**：現價 ({latest_price:.2f}) 已低於明日扣抵價 ({ma_row.明日扣抵價:.2f})，明日需上漲至少 **{-ma_row.扣抵安全邊際:.2f} 元** 才能保住均線不彎頭向下。"
                    )
                else:
                    bullet_points.append(
                        f"✅ **{ma_row.均線週期} 安全**：現價高於明日扣抵價 ({ma_row.明日扣抵價:.2f})，安全邊際為 **+{ma_row.扣抵安全邊際:.2f} 元**。"
                    )
            
            st.markdown("\n".join([f"- {pt}" for pt in bullet_points]))

        else:
            st.warning("⚠️ 歷史資料天數不足以計算所選均線週期。")
