import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import plotly.graph_objects as go

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-純均線監控")

# --- 富果 API 設定 ---
FUGLE_KEY = "Mzk5YWVkYmMtYzVhNi00OWRhLWI5NWUtNGNjYzI3NjNjZDYyIDg0NDdhYjVmLThlMTktNDE3MC1hZDZmLThkMDcwNThiYzM1Mw=="

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    table { width: 100% !important; font-size: 18px !important; }
    th { background-color: #f0f2f6 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- Google Sheet 多分頁設定 ---
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
MONITOR_SHEETS = [
    {"name": "金虎男主頁", "gid": "0"},
    {"name": "工作表20", "gid": "1426872214"}
]

# 計算均線工具函數
def get_ma(arr, period, offset=0):
    sub = arr[offset:offset+period]
    return sum(sub) / period if len(sub) == period else None

@st.cache_data(ttl=60, show_spinner=False)
def fetch_signals(sid, short_n, long_n):
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            valid_ns = [n for n in [short_n, long_n] if pd.notna(n)]
            max_n = max(int(max(valid_ns)) + 10 if valid_ns else 30, 60)
            
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
                    t_highs