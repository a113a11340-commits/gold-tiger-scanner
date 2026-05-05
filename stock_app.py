import streamlit as st          # 網頁介面開發工具
import plotly.graph_objects as go # 繪製互動式 K 線圖與均線圖
import pandas as pd             # 資料處理與分析（DataFrame 操作）
import yfinance as yf           # 從 Yahoo Finance 抓取股市歷史資料
import requests                 # 發送網頁請求（讀取 Google 試算表）
import io                       # 處理文字串流（將 CSV 文字轉為資料框架）

# --- 1. 網頁基本設定 ---
# 設定網頁為寬螢幕模式，並設定網頁分頁標題
st.set_page_config(layout="wide", page_title="金虎南-精密訊號監控")

# Google 試算表的基本網址（不含分頁 ID）
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
# 定義試算表中要讀取的四個分頁 GID
GIDS = ["0", "1241939414", "534437042", "1019044698"]

def run_scan():
    """主掃描函式：讀取設定、抓取數據、判定訊號"""
    all_targets = [] # 初始化清單，存放從試算表讀取的標的設定
    
    # --- 步驟 1: 讀取所有分頁標的 ---
    for gid in GIDS:
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}" # 拼接匯出 CSV 的網址
        try:
            res = requests.get(csv_url, timeout=10) # 發送請求讀取資料
            res.encoding = 'utf-8' # 強制編碼為 utf-8 避免中文亂碼
            if res.status_code != 200: continue # 如果讀取失敗就跳過該分頁
            raw_df = pd.read_csv(io.StringIO(res.text)) # 將下載的 CSV 文字轉為資料表
            
            for _, row in raw_df.iterrows():
                # 如果第一欄（股票代碼）是空的，代表這行沒資料，直接跳過
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue
                
                # 處理代碼格式，去掉可能的小數點，並加上 .TW 字尾
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                
                # 將設定存入清單，均線天數若空白會被 pd.to_numeric 轉為 NaN (無預設值)
                all_targets.append({
                    "sid": sid_full,
                    "name": row.iloc[1] if pd.notna(row.iloc[1]) else "未命名",
                    "s_ma_p": pd.to_numeric(row.iloc[2], errors='coerce'), # 短均線天數
                    "l_ma_p": pd.to_numeric(row.iloc[3], errors='coerce')  # 長均線天數
                })
        except Exception: continue # 發生異常就跳過該分頁

    if not all_targets: return [] # 如果完全沒標的，回傳空列表

    # --- 步驟 2: 批次下載數據 ---
    # 取得所有不重複的股票代碼
    tickers = list(set([t['sid'] for t in all_targets]))
    # 下載最近 120 天數據，確保能算出 60MA
    full_data = yf.download(tickers, period="120d", progress=False, group_by='ticker')

    results = [] # 存放最終有觸發訊號的結果
    for item in all_targets:
        try:
            sid = item['sid']
            # 從大包數據中取出該檔股票的資料
            stock = full_data[sid].copy() if len(tickers) > 1 else full_data.copy()
            stock.dropna(subset=['Close'], inplace=True) # 刪除沒收盤價的日期
            
            if not stock.empty:
                # --- 核心：動態均線計算 (完全無預設值) ---
                s_day = item.get('s_ma_p')
                l_day = item.get('l_ma_p')
                
                has_s = pd.notna(s_day) # 判斷短均是否有填寫
                has_l = pd.notna(l_day) # 判斷長均是否有填寫

                # 如果短長均線都沒填，代表這檔不監控，直接跳過
                if not has_s and not has_l: continue

                # 只有在有填寫天數的情況下，才計算均線欄位
                if has_s:
                    stock['MA_S'] = stock['Close'].rolling(window=int(s_day)).mean()
                if has_l:
                    stock['MA_L'] = stock['Close'].rolling(window=int(l_day)).mean()

                # --- 訊號判定 (併行判斷，不設優先權) ---
                curr_p = float(stock['Close'].iloc[-1]) # 今日收盤價
                prev_p = float(stock['Close'].iloc[-2]) # 昨日收盤價
                
                signals = [] # 收集觸發了哪些訊號
                check_items = []
                if has_s: check_items.append(('MA_S', int(s_day)))
                if has_l: check_items.append(('MA_L', int(l_day)))

                for ma_key, ma_days in check_items:
                    # 確保歷史數據足夠計算出均線值
                    if len(stock) < 2 or pd.isna(stock[ma_key].iloc[-2]): continue
                    
                    c_ma = stock[ma_key].iloc[-1] # 今日均線價
                    p_ma = stock[ma_key].iloc[-2] # 昨日均線價
                    
                    # 判定「突破」：昨日在線下，今日收盤在線上
                    if (prev_p <= p_ma) and (curr_p > c_ma):
                        signals.append(f"🚀突破{ma_days}MA")
                    # 判定「跌破」：昨日在線上，今日收盤在線下
                    elif (prev_p >= p_ma) and (curr_p < c_ma):
                        signals.append(f"🚨跌破{ma_days}MA")

                # 若所有設定的均線都沒觸發訊號，就跳過這檔
                if not signals: continue

                # --- 狀態資訊生成 ---
                # 以第一個設定的均線作為乖離率與趨勢的參考基準
                ref_ma_key, _ = check_items[0]
                ref_ma_val = stock[ref_ma_key].iloc[-1]
                ref_ma_prev = stock[ref_ma_key].iloc[-2]
                
                bias = ((curr_p - ref_ma_val) / ref_ma_val) * 100 # 乖離率
                ma_trend = "⤴️上揚" if ref_ma_val > ref_ma_prev else "⤵️下彎" # 均線趨勢
                sign_summary = " + ".join(signals) # 合併訊號字串
                
                status = f"{sign_summary} | 現價:{curr_p:.2f} | 趨勢:{ma_trend} | 乖離:{bias:.2f}%"
                
                # --- 箱型演算法 (偵測最近 42 天的窄幅盤整區) ---
                view_df = stock.tail(42)
                best_box = None
                idx = 0
                while idx < len(view_df) - 2:
                    w = view_df.iloc[idx:idx+3]
                    w_max, w_min = w['High'].max(), w['Low'].min()
                    # 判斷 3 天內價差是否在 3% 內
                    if (w_max - w_min) / w_min <= 0.03:
                        c_i = idx + 1
                        while c_i < len(view_df):
                            nr = view_df.iloc[c_i]
                            # 若價格跑出箱型上下 1.5% 則箱型結束
                            if nr['Low'] < w_min * 0.985 or nr['High'] > w_max * 1.015: break
                            c_i += 1
                        best_box = {'start': view_df.index[idx], 'end': view_df.index[c_i-1], 'top': w_max, 'bottom': w_min}
                        idx = c_i
                    else: idx += 1

                # 將計算結果封裝回 item 物件
                item.update({"price": curr_p, "df": stock, "box": best_box, "sign": status})
                results.append(item)
        except Exception: continue
    return results

# --- 3. 介面呈現 (Streamlit UI) ---
if "data" not in st.session_state:
    with st.spinner('正在掃描精密訊號...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

# 顯示標題與功能按鈕
col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-精密訊號過濾系統")
with col_b:
    if st.button("🔄 重新掃描"):
        del st.session_state["data"]
        st.rerun()

# 顯示結果
if not data_list:
    st.success("目前尚無符合設定均線之「剛突破/跌破」訊號。")
else:
    for i, item in enumerate(data_list):
        df = item['df']
        # 使用展開容器顯示每檔股票的詳細圖表與狀態
        with st.expander(f"{item['sid']} {item['name']} ➔ {item['sign']}", expanded=True):
            fig = go.Figure()
            # 如果有偵測到箱型盤整區，畫出灰色矩形
            if item['box']:
                b = item['box']
                fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                               line=dict(width=0), fillcolor="gray", opacity=0.3)

            # 畫出紅漲綠跌的 K 線圖
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F'
            ))
            
            # 動態畫出均線 (只有在該欄位存在時才畫線)
            if 'MA_S' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], name="短均線", line=dict(color='#0055CC', width=2)))
            if 'MA_L' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], name="長均線", line=dict(color='#888888', width=1, dash='dot')))

            # 圖表美化設定
            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
                yaxis=dict(side='right', tickfont=dict(size=11))
            )
            # 在網頁上呈現互動式圖表
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}, key=f"ch_{item['sid']}_{i}")