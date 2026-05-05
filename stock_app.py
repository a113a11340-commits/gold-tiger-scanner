import streamlit as st          # 網頁框架
import plotly.graph_objects as go # 繪圖套件
import pandas as pd             # 資料處理
import yfinance as yf           # 抓取股價
import requests                 # 讀取試算表
import io                       # 處理資料流

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide")

# 試算表基礎網址與所有分頁 GID
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
GIDS = ["0", "1241939414", "534437042", "1019044698"]

def get_all_targets():
    """從所有分頁中抓取所有監控標的，不允許遺漏或覆蓋"""
    all_list = []
    for gid in GIDS:
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code != 200: continue
            df_temp = pd.read_csv(io.StringIO(res.text))
            
            for _, row in df_temp.iterrows():
                # 只要代碼欄位有值就抓取
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue
                
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                # 統一格式化代碼
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                
                # 讀取試算表中的短均線天數 (無預設值)
                all_list.append({
                    "sid": sid_full,
                    "name": row.iloc[1] if pd.notna(row.iloc[1]) else "未命名",
                    "s_ma_p": pd.to_numeric(row.iloc[2], errors='coerce')
                })
        except: continue
    return all_list

def run_scan(target_list):
    """執行嚴格突破判定邏輯"""
    if not target_list: return []
    
    results = []
    tickers = [t['sid'] for t in target_list]
    # 下載歷史數據
    full_data = yf.download(tickers, period="100d", progress=False, group_by='ticker')

    for item in target_list:
        try:
            sid = item['sid']
            ma_len = item['s_ma_p']
            if pd.isna(ma_len): continue # 沒填均線就不計算
            
            # 提取個股數據並刪除缺失值
            stock = full_data[sid].copy() if len(tickers) > 1 else full_data.copy()
            stock.dropna(subset=['Close'], inplace=True)
            
            # 計算均線
            stock['MA'] = stock['Close'].rolling(window=int(ma_len)).mean()
            
            # 今日數據 (5/5) 與 昨日數據 (5/4)
            curr_p, curr_ma = stock['Close'].iloc[-1], stock['MA'].iloc[-1]
            prev_p, prev_ma = stock['Close'].iloc[-2], stock['MA'].iloc[-2]
            
            # --- 嚴格突破判定：昨日在線下、今日在線上 ---
            if prev_p < prev_ma and curr_p > curr_ma:
                item.update({
                    "df": stock,
                    "c_p": curr_p,
                    "c_ma": curr_ma,
                    "sign": f"🚀突破{int(ma_len)}MA"
                })
                results.append(item)
        except: continue
    return results

# --- 2. 介面呈現 ---
st.subheader("🐯 金虎南-精密訊號監控系統")

# 使用 Session State 確保不會重複載入
if "final_results" not in st.session_state:
    with st.spinner('讀取試算表並掃描訊號中...'):
        targets = get_all_targets()
        st.session_state.final_results = run_scan(targets)

data_list = st.session_state.final_results

if not data_list:
    st.info("目前尚無符合「昨日線下、今日線上」之突破標的。")
else:
    for i, item in enumerate(data_list):
        df = item['df']
        with st.expander(f"{item['sid']} {item['name']} ➔ {item['sign']}", expanded=True):
            # 建立圖表
            fig = go.Figure()
            
            # 畫 K 線 (紅漲綠跌)
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F'
            ))
            
            # 畫均線 (白色)
            fig.add_trace(go.Scatter(
                x=df.index, y=df['MA'], name="均線", 
                line=dict(color='white', width=2)
            ))

            # 設定圖表格式：鎖定顯示範圍為 42 天
            fig.update_layout(
                height=400, showlegend=False, template="plotly_dark",
                xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=10, b=10),
                xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5]),
                yaxis=dict(side='right')
            )
            
            # 呈現圖表：設定 staticPlot: True 徹底鎖定，禁止縮放與移動
            st.plotly_chart(
                fig, 
                use_container_width=True, 
                config={'displayModeBar': False, 'staticPlot': True}, 
                key=f"chart_{item['sid']}_{i}"
            )

# 重新掃描按鈕
if st.button("🔄 重新掃描數據"):
    if "final_results" in st.session_state:
        del st.session_state.final_results
    st.rerun()