下午 06:50 2026/4/18import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io
import numpy as np
from collections import Counter

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南小箱型-搬家整合版")

# 更新後的試算表網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4/edit"

# --- 2. 金唬男核心邏輯：小箱型偵測演算法 ---
def analyze_gold_tiger_box(df, ma_window):
    """
    1. 尋找區間：往回找觸線 K 棒，連續 2 天未觸碰則斷線 [cite: 1]
    2. 形成門檻：區間內觸線天數必須 >= 3 天 [cite: 1]
    3. 動態共振線：統計頻率最高價位 [cite: 1]
    4. 箱頂定義：Max(最強共振線, 區間最高收盤價) [cite: 1]
    """
    if len(df) < 60: return None
    
    # 計算均線
    df['MA'] = df['Close'].rolling(window=ma_window).mean()
    prices = df.copy()
    
    box_indices = []
    gap_count = 0
    
    # 從最新的一天往回掃描 (2天斷線邏輯)
    for i in range(len(prices)-1, -1, -1):
        row = prices.iloc[i]
        if pd.isna(row['MA']): continue
        
        # 觸線條件：高點 >= 均線 且 低點 <= 均線
        is_touching = (row['High'] >= row['MA']) and (row['Low'] <= row['MA'])
        
        if is_touching:
            box_indices.append(i)
            gap_count = 0 # 重置斷線計數
        else:
            gap_count += 1
            
        # 終止條件：一旦出現連續 2 天未觸碰均線，即判定該箱體區間結束 [cite: 1]
        if gap_count >= 2:
            break
            
    # 形成門檻：區間內觸線天數必須 ≥3 天，小箱型才成立 [cite: 1]
    if len(box_indices) < 3:
        return None
    
    # 取得箱體區間資料
    start_idx = min(box_indices)
    end_idx = max(box_indices)
    box_df = prices.iloc[start_idx : end_idx + 1]
    
    # 動態共振線計算：找出出現頻率最高（共振次數最多）的價位 [cite: 1]
    all_points = pd.concat([box_df['Close'], box_df['High']]).round(2).tolist()
    counts = Counter(all_points)
    max_freq = max(counts.values())
    resonance_candidates = [price for price, freq in counts.items() if freq == max_freq]
    resonance_line = max(resonance_candidates) # 若次數相同，以價格高者為準 [cite: 1]
    
    # 箱頂定義：取 Max(最強共振線價位, 區間最高收盤價) [cite: 1]
    box_top = max(resonance_line, box_df['Close'].max())
    box_bottom_min = box_df['Close'].min() 
    
    # 突破/跌破判定 (含 1.5% 緩衝與量能)
    current_price = prices['Close'].iloc[-1]
    current_ma = prices['MA'].iloc[-1]
    prev_vol = prices['Volume'].iloc[-2]
    curr_vol = prices['Volume'].iloc[-1]
    
    buffer_up = max(box_top, current_ma * 1.015) # 空間：當前收盤價 > Max(箱頂, 均線 ×1.015) [cite: 1]
    buffer_down = min(box_bottom_min, current_ma * 0.985) # 跌破：當前收盤價 < Min(最低收盤, 均線 ×0.985) [cite: 1]
    
    # 能量過濾：當前成交量 > 昨日成交量 ×1.2 [cite: 1]
    vol_pass = curr_vol > prev_vol * 1.2
    
    status = "⌛ 延續小箱型 [盤整中]"
    if current_price > buffer_up and vol_pass:
        status = "🚀 正式突破 [多頭表態]"
    elif current_price < buffer_down:
        status = "📉 向下跌破 [型態失效]"
    
    return {
        "box_top": box_top,
        "buffer_up": buffer_up,
        "buffer_down": buffer_down,
        "box_start": box_df.index[0],
        "box_end": box_df.index[-1],
        "status": f"{status} ({len(box_df)}天)",
        "count": len(box_df)
    }

# --- 3. 掃描引擎 ---
def run_scan():
    csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv&gid=0'
    try:
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        raw_df = pd.read_csv(io.StringIO(res.text))
    except: return []

    results = []
    for i, row in raw_df.iterrows():
        try:
            sid_raw = str(row.iloc[0]).split('.')[0].strip()
            if not sid_raw or sid_raw == "nan": continue
            sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
            
            # 計算用 250 天，確保數據足夠
            stock = yf.download(sid_full, period="250d", progress=False)
            if stock.empty: continue
            if isinstance(stock.columns, pd.MultiIndex): stock.columns = stock.columns.get_level_values(0)
            
            ma_window = int(row.iloc[2]) if pd.notna(row.iloc[2]) else 20
            box_data = analyze_gold_tiger_box(stock, ma_window)
            
            results.append({
                "sid": sid_full, "name": row.iloc[1], "price": stock['Close'].iloc[-1],
                "sign": row.iloc[5], "df": stock, "box": box_data, "ma_window": ma_window
            })
        except: continue
    return results

# --- 4. 畫面顯示 ---
st.title("🐯 金虎南手機版-小箱型邏輯整合")

if "data" not in st.session_state:
    with st.spinner('同步金唬男規格中...'):
        st.session_state["data"] = run_scan()

if st.button("🔄 刷新數據"):
    del st.session_state["data"]
    st.rerun()

for item in st.session_state["data"]:
    df = item['df']
    # 顯示 2 個月數據 (約 42 個交易日) [cite: 1]
    display_df = df.iloc[-42:]
    box = item['box']
    
    title = f"{item['sid']} {item['name']} | {item['price']:.2f} | {box['status'] if box else '無符合箱型'}"
    with st.expander(title, expanded=True):
        
        fig = go.Figure()
        # K線
        fig.add_trace(go.Candlestick(
            x=display_df.index, open=display_df['Open'], high=display_df['High'], 
            low=display_df['Low'], close=display_df['Close'],
            increasing_line_color='red', decreasing_line_color='green', name="K線"
        ))
        
        # 均線
        ma_line = df['MA'].iloc[-42:]
        fig.add_trace(go.Scatter(x=display_df.index, y=ma_line, line=dict(color='yellow', width=1), name="MA"))

        if box:
            # 畫出：共振箱頂水平線 (紅色粗實線) [cite: 1]
            fig.add_shape(type="line", x0=display_df.index[0], x1=display_df.index[-1],
                          y0=box['box_top'], y1=box['box_top'],
                          line=dict(color="red", width=2))
            
            # 畫出：均線 +1.5% 緩衝線 (白色虛線) [cite: 1]
            fig.add_shape(type="line", x0=display_df.index[0], x1=display_df.index[-1],
                          y0=box['buffer_up'], y1=box['buffer_up'],
                          line=dict(color="white", width=1, dash="dash"))
            
            # 文字資訊顯示
            st.write(f"📊 **箱體分析**：{box['status']}")
            c1, c2, c3 = st.columns(3)
            c1.metric("共振箱頂", f"{box['box_top']:.2f}")
            c2.metric("突破門檻", f"{box['buffer_up']:.2f}")
            c3.metric("跌破門檻", f"{box['buffer_down']:.2f}")

        fig.update_layout(
            height=300, margin=dict(l=10, r=10, t=10, b=10),
            xaxis_rangeslider_visible=False, template="plotly_dark",
            xaxis=dict(type='category', showticklabels=False),
            yaxis=dict(side='right')
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})