import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 設定區 ---
st.set_page_config(layout="wide")
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
GIDS = ["0", "1241939414", "534437042", "1019044698"]

def get_full_targets():
    """從所有分頁抓取代碼與均線設定"""
    targets = []
    for gid in GIDS:
        url = f"{SHEET_BASE}/export?format=csv&gid={gid}"
        try:
            r = requests.get(url, timeout=10)
            r.encoding = 'utf-8'
            df = pd.read_csv(io.StringIO(r.text))
            for _, row in df.iterrows():
                sid = str(row.iloc[0]).split('.')[0].strip()
                if not sid or sid == 'nan': continue
                
                # 依據代碼長度補上後綴
                full_sid = f"{sid}.TW" if len(sid) == 4 else sid
                targets.append({
                    "sid": full_sid,
                    "name": row.iloc[1],
                    "s_ma": pd.to_numeric(row.iloc[2], errors='coerce')
                })
        except: continue
    return targets

# --- 2. 掃描執行 ---
def run_scan(all_targets):
    results = []
    tickers = [t['sid'] for t in all_targets]
    # 抓取足夠天數以計算均線
    data = yf.download(tickers, period="100d", progress=False, group_by='ticker')
    
    for item in all_targets:
        try:
            sid = item['sid']
            ma_len = item['s_ma']
            if pd.isna(ma_len): continue
            
            # 取得該股數據
            df = data[sid].copy() if len(tickers) > 1 else data.copy()
            df.dropna(subset=['Close'], inplace=True)
            
            # 計算均線
            df['MA'] = df['Close'].rolling(window=int(ma_len)).mean()
            
            # 取得最後兩筆：昨日與今日
            c_p, c_ma = df['Close'].iloc[-1], df['MA'].iloc[-1]
            p_p, p_ma = df['Close'].iloc[-2], df['MA'].iloc[-2]
            
            # 嚴格突破邏輯：昨日在下、今日在上
            if p_p < p_ma and c_p > c_ma:
                item.update({"curr": c_p, "ma_v": c_ma})
                results.append(item)
        except: continue
    return results

# --- 3. 網頁顯示 ---
st.subheader("精密訊號監控")

if "final_list" not in st.session_state:
    targets = get_full_targets()
    st.session_state.final_list = run_scan(targets)

if not st.session_state.final_list:
    st.write("目前無符合突破訊號之標的。")
else:
    for res in st.session_state.final_list:
        with st.container():
            st.write(f"### {res['sid']} {res['name']} ➔ 🚀突破{int(res['s_ma'])}MA")
            st.write(f"今日收盤: {res['curr']:.2f} / 均線位置: {res['ma_v']:.2f}")
            st.divider()

if st.button("重新整理數據"):
    del st.session_state.final_list
    st.rerun()