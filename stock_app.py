import streamlit as st
import pandas as pd
import requests
import numpy as np
import datetime

# --- 1. 設定與參數 ---
st.set_page_config(layout="wide", page_title="金虎南-轉折監控")
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4/export?format=csv&gid=1426872214"
FUGLE_KEY = "Mzk5YWVkYmMtYzVhNi00OWRhLWI5NWUtNGNjYzI3NjNjZDYyIDg0NDdhYjVmLThlMTktNDE3MC1hZDZmLThkMDcwNThiYzM1Mw=="

# --- 2. 核心運算 ---
def get_price(sid, cls_default):
    # 僅在平日盤中讀取富果，其餘使用 Yahoo 收盤價
    if datetime.datetime.now().weekday() < 5:
        try:
            url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
            res = requests.get(url, headers={"X-API-KEY": FUGLE_KEY}, timeout=3)
            return res.json()['data']['quote'].get('price', cls_default)
        except: return cls_default
    return cls_default

@st.cache_data(ttl=60)
def scan_stock(sid, short_n, long_n):
    # 此處保留您原本的 Yahoo 歷史邏輯
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=100d&interval=1d"
            res = requests.get(url, timeout=5)
            if res.status_code != 200: continue
            cls = [p for p in res.json()['chart']['result'][0]['indicators']['quote'][0]['close'] if p is not None]
            
            p0 = get_price(sid, cls[-1])
            ma_s = sum(cls[-int(short_n):]) / int(short_n)
            
            # 判斷邏輯
            signal = ""
            if cls[-2] < (sum(cls[-int(short_n)-1:-1])/int(short_n)) and p0 > ma_s:
                signal = f"站上{short_n}MA({ma_s:.2f})"
            elif cls[-2] >= (sum(cls[-int(short_n)-1:-1])/int(short_n)) and p0 < ma_s:
                signal = f"跌破{short_n}MA({ma_s:.2f})"
                
            return {"price": float(p0), "signal": signal}
        except: continue
    return None

# --- 3. 介面 ---
st.title("🐯 金虎南：轉折監控系統 (主表模式)")

if st.button("🔄 同步主表資料 / 🚀 強制刷新即時報價"):
    df = pd.read_csv(SHEET_CSV_URL)
    results = []
    for _, row in df.iterrows():
        sid = str(row.iloc[0]).split('.')[0]
        data = scan_stock(sid, row.iloc[2], row.iloc[3])
        if data and data['signal']:
            results.append({"代號": sid, "名稱": row.iloc[1], "現價": data['price'], "訊號": data['signal']})
    
    st.session_state["data"] = pd.DataFrame(results)

if "data" in st.session_state:
    st.dataframe(st.session_state["data"], use_container_width=True)