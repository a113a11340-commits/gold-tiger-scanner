import streamlit as st
import pandas as pd
import requests
import io
import numpy as np
import datetime

# --- 1. 設定與參數 ---
st.set_page_config(layout="wide", page_title="金虎南-轉折監控")
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4/export?format=csv&gid=1426872214"
FUGLE_KEY = "Mzk5YWVkYmMtYzVhNi00OWRhLWI5NWUtNGNjYzI3NjNjZDYyIDg0NDdhYjVmLThlMTktNDE3MC1hZDZmLThkMDcwNThiYzM1Mw=="

# --- 2. 運算函數 ---
def get_price(sid, cls_default):
    # 僅平日盤中呼叫富果 API，其餘時間使用 Yahoo 收盤價
    if datetime.datetime.now().weekday() < 5:
        try:
            url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
            res = requests.get(url, headers={"X-API-KEY": FUGLE_KEY}, timeout=3)
            return res.json()['data']['quote'].get('price', cls_default)
        except: return cls_default
    return cls_default

def scan_stock(sid, short_n, long_n):
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=100d&interval=1d"
            res = requests.get(url, timeout=5)
            if res.status_code != 200: continue
            cls = [p for p in res.json()['chart']['result'][0]['indicators']['quote'][0]['close'] if p is not None]
            if len(cls) < 40: continue
            
            p0 = get_price(sid, cls[-1])
            ma_s = sum(cls[-int(short_n):]) / int(short_n)
            
            signal = ""
            if cls[-2] < (sum(cls[-int(short_n)-1:-1])/int(short_n)) and p0 > ma_s:
                signal = f"站上{short_n}MA"
            elif cls[-2] >= (sum(cls[-int(short_n)-1:-1])/int(short_n)) and p0 < ma_s:
                signal = f"跌破{short_n}MA"
            
            return {"price": float(p0), "signal": signal}
        except: continue
    return None

# --- 3. 網頁介面 ---
st.title("🐯 金虎南：轉折監控系統 (主表模式)")

def run_scanner():
    try:
        # 使用 utf-8-sig 解決中文亂碼問題
        res = requests.get(SHEET_CSV_URL)
        df = pd.read_csv(io.StringIO(res.text), encoding='utf-8-sig')
        results = []
        for _, row in df.iterrows():
            sid = str(row.iloc[0]).split('.')[0]
            data = scan_stock(sid, row.iloc[2], row.iloc[3])
            if data and data['signal']:
                results.append({"代號": sid, "名稱": row.iloc[1], "現價": data['price'], "訊號": data['signal']})
        st.session_state["data"] = pd.DataFrame(results)
    except Exception as e:
        st.error(f"掃描失敗: {e}")

# 開啟時自動執行一次
if "data" not in st.session_state:
    run_scanner()

# 提供手動更新按鈕
if st.button("🔄 同步主表資料 / 🚀 強制刷新即時報價"):
    run_scanner()

# 顯示結果
if "data" in st.session_state and not st.session_state["data"].empty:
    st.dataframe(st.session_state["data"], use_container_width=True, hide_index=True)
else:
    st.info("目前無觸發訊號，請點擊上方按鈕手動更新。")