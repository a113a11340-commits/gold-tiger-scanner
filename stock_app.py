import streamlit as st
import pandas as pd
import requests
import io
import time

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-試算表同步戰情室")

# 強制調整邊距，讓表格長得像試算表
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    table { width: 100% !important; }
    </style>
    """, unsafe_allow_html=True)

SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
SHEET_MAP = {
    "0": "工作表1",
    "1241939414": "工作表2",
    "534437042": "工作表3"
}

def calculate_ma_signals(sid, short_n, long_n):
    """直接在網頁端計算均線並判定站上/跌破"""
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        # 抓取足夠計算長均線的歷史資料
        max_n = int(max(short_n, long_n)) + 5
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d&t={time.time()}"
        try:
            res = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
            r = res.json()['chart']['result'][0]
            closes = [p for p in r['indicators']['quote'][0]['close'] if p is not None]
            cur_price = r['meta']['regularMarketPrice']
            
            if len(closes) < max(short_n, long_n): continue
            
            # 計算均線 (Python 邏輯)
            ma_short = sum(closes[-int(short_n):]) / short_n
            ma_long = sum(closes[-int(long_n):]) / long_n
            
            # 判定站上/跌破
            if cur_price > ma_short and cur_price > ma_long:
                status = "🟢 站上均線"
            elif cur_price < ma_short or cur_price < ma_long:
                status = "🔴 跌破均線"
            else:
                status = "🟡 均線糾結"
                
            return {"cur_price": cur_price, "status": status}
        except: continue
    return None

def run_scan():
    """執行全分頁掃描"""
    grouped_results = {name: [] for name in SHEET_MAP.values()}
    for gid, sheet_name in SHEET_MAP.items():
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}&cb={time.time()}"
        try:
            res = requests.get(csv_url, timeout=10)
            res.encoding = 'utf-8'
            raw_df = pd.read_csv(io.StringIO(res.text))
            
            for _, row in raw_df.iterrows():
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                if not sid_raw: continue
                
                # 從試算表讀取你設定的均線天數 (C, D 欄)
                short_ma_days = pd.to_numeric(row.iloc[2], errors='coerce')
                long_ma_days = pd.to_numeric(row.iloc[3], errors='coerce')
                
                if pd.isna(short_ma_days) or pd.isna(long_ma_days): continue
                
                # 呼叫計算邏輯
                result = calculate_ma_signals(sid_raw, short_ma_days, long_ma_days)
                if not result: continue

                grouped_results[sheet_name].append({
                    "代號": sid_raw,
                    "名稱": row.iloc[1] if pd.notna(row.iloc[1]) else "未命名",
                    "短均天數": int(short_ma_days),
                    "長均天數": int(long_ma_days),
                    "現價": f"{result['cur_price']:.2f}",
                    "判定結果": result['status'],
                    "原始備註": str(row.iloc[5]) if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                })
        except: continue
    return grouped_results

# --- 2. 介面呈現 ---
st.title("🐯 金虎南-試算表同步監控")

if "data" not in st.session_state:
    with st.spinner('正在根據試算表參數進行 Python 即時運算...'):
        st.session_state["data"] = run_scan()

if st.button("🔄 重新同步試算表並重新計算"):
    if "data" in st.session_state:
        del st.session_state["data"]
    st.rerun()

gd = st.session_state["data"]
for s_name, signals in gd.items():
    if signals:
        st.subheader(f"📊 {s_name}")
        # 轉換為 DataFrame 並顯示，這會長得跟試算表一模一樣
        df_display = pd.DataFrame(signals)
        st.table(df_display) 
        st.divider()

if not any(gd.values()):
    st.info("目前沒有符合均線判定條件的股票。")