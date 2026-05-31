import streamlit as st
import pandas as pd
import requests
import numpy as np
import datetime

# --- 1. 設定與參數 ---
st.set_page_config(layout="wide", page_title="金虎南-轉折監控")
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4/export?format=csv&gid=1426872214"
FUGLE_KEY = "Mzk5YWVkYmMtYzVhNi00OWRhLWI5NWUtNGNjYzI3NjNjZDYyIDg0NDdhYjVmLThlMTktNDE3MC1hZDZmLThkMDcwNThiYzM1Mw=="

# --- 2. 核心運算函數 ---
def get_resonance_line(closes):
    data = closes[-60:]
    min_v, max_v = min(data), max(data)
    range_v = max_v - min_v
    if range_v <= 0: return data[-1]
    buckets = np.histogram(data, bins=20)[0]
    return min_v + (np.argmax(buckets) * (range_v / 19))

@st.cache_data(ttl=60)
def fetch_signals(sid, short_n, long_n):
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            # 歷史資料依舊使用 Yahoo
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=100d&interval=1d"
            res = requests.get(url, timeout=8)
            if res.status_code != 200: continue
            data = res.json()['chart']['result'][0]
            cls = [p for p in data['indicators']['quote'][0]['close'] if p is not None]
            if len(cls) < 40: continue
            
            # 判斷是否為開盤日 (週一至週五)
            now = datetime.datetime.now()
            is_weekday = now.weekday() < 5
            
            # 即時價格獲取邏輯
            p0 = cls[-1]  # 預設使用收盤價
            if is_weekday:
                f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
                f_res = requests.get(f_url, headers={"X-API-KEY": FUGLE_KEY}, timeout=5)
                if f_res.status_code == 200:
                    fugle_data = f_res.json().get('data', {}).get('quote', {})
                    p0 = fugle_data.get('price', cls[-1])
            
            signals = []
            ma_s = sum(cls[-int(short_n):]) / int(short_n)
            
            # 判斷邏輯
            if cls[-2] < (sum(cls[-int(short_n)-1:-1])/int(short_n)) and p0 > ma_s:
                signals.append(f"站上{short_n}MA")
            elif cls[-2] >= (sum(cls[-int(short_n)-1:-1])/int(short_n)) and p0 < ma_s:
                signals.append(f"跌破{short_n}MA")
            
            res_line = get_resonance_line(cls)
            if abs(p0 - res_line) / res_line < 0.005:
                signals.append(f"🎯共振線({res_line:.2f})[{'支撐' if p0 >= res_line else '跌破'}]")
            
            if signals:
                return {"price": p0, "signal": " + ".join(signals)}
        except: continue
    return None

# --- 3. 網頁介面 ---
st.title("🐯 金虎南：工作表20 監控系統")

if st.button("🔄 同步並掃描「工作表20」資料"):
    results = []
    df = pd.read_csv(SHEET_CSV_URL)
    for _, row in df.iterrows():
        sid = str(row.iloc[0]).split('.')[0] 
        data = fetch_signals(sid, row.iloc[2], row.iloc[3])
        if data:
            results.append({"代號": sid, "名稱": row.iloc[1], "現價": data['price'], "訊號": data['signal']})
    
    st.session_state["data"] = results

if "data" in st.session_state and st.session_state["data"]:
    st.dataframe(pd.DataFrame(st.session_state["data"]), use_container_width=True, hide_index=True)
elif "data" in st.session_state:
    st.info("目前無觸發訊號")