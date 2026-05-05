import streamlit as st          # 網頁框架
import plotly.graph_objects as go # 繪圖套件
import pandas as pd             # 資料處理
import yfinance as yf           # 抓取股價
import requests                 # 讀取試算表
import io                       # 處理資料流

# --- 1. 網頁基本設定 ---
# 設定寬螢幕模式與分頁標題
st.set_page_config(layout="wide", page_title="金虎南-精密訊號監控")

# 試算表基礎網址
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
# 指定的分頁 GID
GIDS = ["0", "1241939414", "534437042", "1019044698"]

def run_scan():
    """執行全量掃描邏輯"""
    all_targets = [] # 儲存標的清單
    
    # --- 步驟 1: 讀取試算表標的 ---
    for gid in GIDS:
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code != 200: continue
            raw_df = pd.read_csv(io.StringIO(res.text))
            
            for _, row in raw_df.iterrows():
                # 排除空行（代碼欄位必須有值）
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue
                
                # 格式化股票代碼
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                
                # 讀取均線天數 (無預設值，未填則為 NaN)
                all_targets.append({
                    "sid": sid_full,
                    "name": row.iloc[1] if pd.notna(row.iloc[1]) else "未命名",
                    "s_ma_p": pd.to_numeric(row.iloc[2], errors='coerce'),
                    "l_ma_p": pd.to_numeric(row.iloc[3], errors='coerce')
                })
        except Exception: continue

    if not all_targets: return []

    # --- 步驟 2: 下載數據與判定訊號 ---
    tickers = list(set([t['sid'] for t in all_targets]))
    full_data = yf.download(tickers, period="120d", progress=False, group_by='ticker')

    results = []
    for item in all_targets:
        try:
            sid = item['sid']
            stock = full_data[sid].copy() if len(tickers) > 1 else full_data.copy()
            stock.dropna(subset=['Close'], inplace=True)
            
            if not stock.empty:
                # 判定哪些均線需要計算
                s_day, l_day = item.get('s_ma_p'), item.get('l_ma_p')
                has_s, has_l = pd.notna(s_day), pd.notna(l_day)

                if not has_s and not has_l: continue # 兩者皆無設定則跳過

                # 計算指定均線
                if has_s: stock['MA_S'] = stock['Close'].rolling(window=int(s_day)).mean()
                if has_l: stock['MA_L'] = stock['Close'].rolling(window=int(l_day)).mean()

                # 訊號判定邏輯
                curr_p = float(stock['Close'].iloc[-1]) # 今日收盤
                prev_p = float(stock['Close'].iloc[-2]) # 昨日收盤
                
                signals = []
                check_items = []
                if has_s: check_items.append(('MA_S', int(s_day)))
                if has_l: check_items.append(('MA_L', int(l_day)))

                for ma_key, ma_days in check_items:
                    if len(stock) < 2 or pd.isna(stock[ma_key].iloc[-2]): continue
                    c_ma, p_ma = stock[ma_key].iloc[-1], stock[ma_key].iloc[-2]
                    
                    if (prev_p <= p_ma) and (curr_p > c_ma):
                        signals.append(f"🚀突破{ma_days}MA")
                    elif (prev_p >= p_ma) and (curr_p < c_ma):
                        signals.append(f"🚨跌破{ma_days}MA")

                if not signals: continue # 無訊號則不顯示

                # 乖離與趨勢計算 (取 check_items 第一項為基準)
                ref_ma_key, _ = check_items[0]
                ref_ma_val, ref_ma_prev = stock[ref_ma_key].iloc[-1], stock[ref_ma_key].iloc[-2]
                bias = ((curr_p - ref_ma_val) / ref_ma_val) * 100
                ma_trend = "⤴️上揚" if ref_ma_val > ref_ma_prev else "⤵️下彎"
                
                status = f"{' + '.join(signals)} | 現價:{curr_p:.2f} | 趨勢:{ma_trend} | 乖離:{bias:.2f}%"
                
                # 箱型偵測邏輯 (42日觀測)
                view_df = stock.tail(42)
                best_box, idx = None, 0
                while idx < len(view_df) - 2:
                    w = view_df.iloc[idx:idx+3]
                    w_max, w_min = w['High'].max(), w['Low'].min()
                    if (w_max - w_min) / w_min <= 0.03:
                        c_i = idx + 1
                        while c_i < len(view_df):
                            nr = view_df.iloc[c_i]
                            if nr['Low'] < w_min * 0.985 or nr['High'] > w_max * 1.015: break
                            c_i += 1
                        best_box = {'start': view_df.index[idx], 'end': view_df.index[c_i-1], 'top': w_max, 'bottom': w_min}
                        idx = c_i
                    else: idx += 1

                item.update({"price": curr_p, "df": stock, "box": best_box, "sign": status})
                results.append(item)
        except Exception: continue
    return results

# --- 3. UI 呈現 ---
if "data" not in st.session_state:
    with st.spinner('正在掃描精密訊號...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

# 標題與重新整理列
col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-精密訊號過濾系統")
with col_b:
    if st.button("🔄 重新掃描"):
        del st.session_state["data"]
        st.rerun()

if not data_list:
    st.success("目前尚無符合設定均線之突破/跌破訊號。")
else:
    for i, item in enumerate(data_list):
        df = item['df']
        with st.expander(f"{item['sid']} {item['name']} ➔ {item['sign']}", expanded=True):
            fig = go.Figure()
            # 畫箱型
            if item['box']:
                b = item['box']
                fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                               line=dict(width=0), fillcolor="gray", opacity=0.3)

            # 畫 K 線 (紅漲綠跌)
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F'
            ))
            
            # 畫設定的均線
            if 'MA_S' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], name="短均", line=dict(color='#0055CC', width=2)))
            if 'MA_L' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], name="長均", line=dict(color='#888888', width=1, dash='dot')))

            # 鎖定圖表配置：不顯示滑桿、鎖定為 42 天範圍
            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
                yaxis=dict(side='right', tickfont=dict(size=11))
            )
            
            # 核心修正：加入 staticPlot=True 讓圖片完全不動
            st.plotly_chart(
                fig, 
                use_container_width=True, 
                config={'displayModeBar': False, 'staticPlot': True}, 
                key=f"ch_{item['sid']}_{i}"
            )