import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import plotly.graph_objects as go

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-轉折監控")

# --- 富果 API 設定 ---
FUGLE_KEY = "Mzk5YWVkYmMtYzVhNi00OWRhLWI5NWUtNGNjYzI3NjNjZDYyIDg0NDdhYjVmLThlMTktNDE3MC1hZDZmLThkMDcwNThiYzM1Mw=="

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    table { width: 100% !important; font-size: 18px !important; }
    th { background-color: #f0f2f6 !important; }
    </style>
    """, unsafe_allow_html=True)

SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
TARGET_GID = "0"
TARGET_NAME = "工作表1"

# 計算均線工具函數
def get_ma(arr, period, offset=0):
    sub = arr[offset:offset+period]
    return sum(sub) / period if len(sub) == period else None

# 水平共振線計算邏輯
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

# ⚡ 獨立包裝：防截斷的圖表數據線生成器
def build_plot_lines(cls, short_n, long_n, res_line, highs, is_fugle, slopeH, slopeL, hIdx1, lIdx1, hVal1, lVal1):
    p_ma_s, p_ma_l, p_res, p_dH, p_dL = [], [], [], [], []
    for i in range(60):
        if i >= len(cls): break
        p_ma_s.append(get_ma(cls, int(short_n), i) if pd.notna(short_n) else None)
        p_ma_l.append(get_ma(cls, int(long_n), i) if pd.notna(long_n) else None)
        p_res.append(res_line)
        if len(highs) >= 51:
            h_idx = (i - 1) if is_fugle else i
            p_dH.append(hVal1 + slopeH * (h_idx - hIdx1))
            p_dL.append(lVal1 + slopeL * (h_idx - lIdx1))
        else:
            p_dH.append(None)
            p_dL.append(None)
    return p_ma_s, p_ma_l, p_res, p_dH, p_dL

@st.cache_data(ttl=60, show_spinner=False)
def fetch_signals(sid, short_n, long_n):
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            valid_ns = [n for n in [short_n, long_n] if pd.notna(n)]
            max_n = max(90, int(max(valid_ns) * 1.5) + 20 if valid_ns else 60)
            
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d"
            res = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
                
            data = res.json()['chart']['result'][0]
            quote = data['indicators']['quote'][0]
            timestamps = data.get('timestamp', [])
            
            raw_cls = quote.get('close', [])
            raw_high = quote.get('high', [])
            raw_low = quote.get('low', [])
            raw_op = quote.get('open', [])
            raw_vol = quote.get('volume', [])
            
            t_cls, t_highs, t_lows, t_opens, t_vols, t_dates = [], [], [], [], [], []
            for i in range(len(raw_cls)):
                if raw_cls[i] is not None and raw_high[i] is not None and raw_low[i] is not None and raw_op[i] is not None:
                    t_cls.append(raw_cls[i])
                    t_highs.append(raw_high[i])
                    t_lows.append(raw_low[i])
                    t_opens.append(raw_op[i])
                    t_vols.append(raw_vol[i] if raw_vol[i] is not None else 0)
                    t_dates.append(time.strftime('%Y-%m-%d', time.localtime(timestamps[i])) if i < len(timestamps) else "")
                        
            cls, highs, lows, opens, vols, dates = t_cls[::-1], t_highs[::-1], t_lows[::-1], t_opens[::-1], t_vols[::-1], t_dates[::-1]
            if len(cls) < 60: continue

            # --- 獲取即時價格 (富果 API) ---
            f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
            f_res = requests.get(f_url, headers={"X-API-KEY": FUGLE_KEY}, timeout=5)
            
            is_fugle_active = False
            if f_res.status_code == 200:
                f_data = f_res.json().get('data', {}).get('quote', {})
                cur_price = f_data.get('price', cls[0])
                if cur_price and cur_price > 0:
                    is_fugle_active = True
                    T_close = cur_price
                    T_low = f_data.get('low', cur_price) if f_data.get('low', 0) > 0 else cur_price
                    T_high = f_data.get('high', cur_price) if f_data.get('high', 0) > 0 else cur_price
                    Y_close, Y_low, Y_high = cls[0], lows[0], highs[0]
                    B_close = cls[1]
            
            if not is_fugle_active:
                T_close, T_low, T_high = cls[0], lows[0], highs[0]
                Y_close, Y_low, Y_high = cls[1], lows[1], highs[1]
                B_close = cls[2]
            
            signals = []
            has_signal = False
            ma_list = [("短", short_n), ("長", long_n)]
            
            # 1. 均線與二日法則判定
            for label, n in ma_list:
                if pd.isna(n): continue
                n = int(n)
                Y_ma = get_ma(cls, n, 0) if is_fugle_active else get_ma(cls, n, 1)
                B_ma = get_ma(cls, n, 1) if is_fugle_active else get_ma(cls, n, 2)
                T_ma = get_ma([T_close] + cls, n, 0) if is_fugle_active else get_ma(cls, n, 0)
                
                if T_ma is None or Y_ma is None or B_ma is None: continue
                trend = "⬆️" if T_ma > Y_ma else "↘️"
                label_str = f"{label}({n}MA:{T_ma:.2f}){trend}"
                
                if (B_close < B_ma and Y_close > Y_ma) and (T_low > T_ma) and (T_close > Y_close):
                    signals.append(f"🔥2日法則(強勢突破){label_str}")
                    has_signal = True
                
                if (Y_close < Y_ma and B_close >= B_ma) and T_close > T_ma:
                    tag = "[強勢反轉]" if (T_close - T_ma) / T_ma > 0.005 else ""
                    signals.append(f"🔄反2日(假跌破){label_str}{tag}")
                    has_signal = True
                
                if Y_close >= Y_ma and T_close < T_ma:
                    signals.append(f"跌破{label_str}[停損]")
                    has_signal = True
                elif Y_close < Y_ma and T_close > T_ma and not any(k in s for k in ["假跌破", "2日法則"] for s in signals):
                    signals.append(f"突破{label_str}[進場1/2]")
                    has_signal = True

            # 2. 小箱型邏輯
            if not pd.isna(short_n):
                off = 1 if is_fugle_active else 2
                c_highs = [T_high, Y_high, highs[off]]
                c_lows = [T_low, Y_low, lows[off]]
                c_closes = [T_close, Y_close, cls[off]]
                maST = get_ma([T_close] + cls, int(short_n), 0) if is_fugle_active else get_ma(cls, int(short_n), 0)
                
                def is_touch(i):
                    m = maST if i == 0 else (get_ma(cls, int(short_n), i-1) if is_fugle_active else get_