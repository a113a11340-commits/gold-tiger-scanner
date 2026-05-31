import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import plotly.graph_objects as go

# --- 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-轉折監控")

# --- 富果 API 與 Sheet 設定 ---
FUGLE_KEY = "Mzk5YWVkYmMtYzVhNi00OWRhLWI5NWUtNGNjYzI3NjNjZDYyIDg0NDdhYjVmLThlMTktNDE3MC1hZDZmLThkMDcwNThiYzM1Mw=="
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
TARGET_GID = "0"
TARGET_NAME = "工作表1"

# --- 計算均線工具函數 ---
def get_ma(arr, period, offset=0):
    sub = arr[offset:offset+period]
    return sum(sub) / period if len(sub) == period else None

# --- 水平共振線計算 ---
def get_resonance_line(closes_list):
    data = closes_list[:60]
    if not data: return 0
    v_min, v_max = min(data), max(data)
    v_range = v_max - v_min
    if v_range <= 0: return data[0]
    buckets = [0] * 20
    for p in data:
        idx = int(((p - v_min) / v_range) * 19)
        idx = max(0, min(19, idx))
        buckets[idx] += 1
    max_idx = buckets.index(max(buckets))
    return v_min + (max_idx * (v_range / 19))
@st.cache_data(ttl=60, show_spinner=False)
def fetch_signals(sid, short_n, long_n):
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=90d&interval=1d"
            res = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
            data = res.json()['chart']['result'][0]
            quote = data['indicators']['quote'][0]
            cls = quote['close'][::-1]
            highs = quote['high'][::-1]
            lows = quote['low'][::-1]
            
            # 取得即時報價
            f_res = requests.get(f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}", headers={"X-API-KEY": FUGLE_KEY}, timeout=5)
            f_data = f_res.json().get('data', {}).get('quote', {}) if f_res.status_code == 200 else {}
            curr = f_data.get('price', cls[0])
            
            signals = []
            # 均線判定 (短長均線)
            if pd.notna(short_n):
                ma_s = get_ma([curr] + cls, int(short_n), 0)
                if cls[1] < get_ma(cls, int(short_n), 1) and curr > ma_s: signals.append("短均突破")
            if pd.notna(long_n):
                ma_l = get_ma([curr] + cls, int(long_n), 0)
                if cls[1] < get_ma(cls, int(long_n), 1) and curr > ma_l: signals.append("長均突破")
            
            # 水平共振線判定
            res_line = get_resonance_line(cls)
            if cls[1] < res_line and curr >= res_line: signals.append("水平共振線突破")
            
            # 對稱趨勢斜線判定 (簡化版邏輯)
            # (此處可填入您原本的斜線計算公式)
            
            if signals:
                return {"price": curr, "signal": " + ".join(signals), "cls": cls[:60], "res": res_line}
        except: continue
    return None
def run_scan():
    results = []
    csv_url = f"{SHEET_BASE}/export?format=csv&gid={TARGET_GID}"
    try:
        res = requests.get(csv_url, timeout=10)
        df = pd.read_csv(io.StringIO(res.text))
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fetch_signals, str(row[0]), row[2], row[3]): row for _, row in df.iterrows()}
            for f in concurrent.futures.as_completed(futures):
                data = f.result()
                if data:
                    row = futures[f]
                    results.append({"代號": str(row[0]), "名稱": row[1], "訊號": data["signal"], "plot": data})
    except: pass
    return results
st.title("🐯 金虎南：轉折監控")
if st.button("🔄 同步資料"):
    st.session_state["data"] = run_scan()
    st.rerun()

if "data" in st.session_state:
    for item in st.session_state["data"]:
        sig = item["訊號"]
        p = item["plot"]
        with st.expander(f"{item['代號']} - {sig}"):
            fig = go.Figure()
            # 畫出基礎 K 線
            fig.add_trace(go.Candlestick(close=p["cls"], ...))
            
            # 條件式繪圖：只有包含特定訊號才畫線
            if "短均" in sig:
                fig.add_trace(go.Scatter(y=..., name="短均線"))
            if "長均" in sig:
                fig.add_trace(go.Scatter(y=..., name="長均線"))
            if "水平共振線" in sig:
                fig.add_trace(go.Scatter(y=[p["res"]]*60, name="水平共振線"))
            
            st.plotly_chart(fig)