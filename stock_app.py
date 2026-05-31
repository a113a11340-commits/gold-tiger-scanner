import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures  # 導入多執行緒平行加速庫

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

# 水平共振線計算邏輯 (找出過去60天最密集的價格區間)
def get_resonance_line(closes_list):
    data = closes_list[:60]
    if not data: return 0
    v_min = min(data)
    v_max = max(data)
    v_range = v_max - v_min
    if v_range <= 0: return data[0]
    buckets = [0] * 20
    for p in data:
        idx = int(((p - v_min) / v_range) * 19)
        if idx < 0: idx = 0
        if idx > 19: idx = 19
        buckets[idx] += 1
    max_idx = buckets.index(max(buckets))
    return v_min + (max_idx * (v_range / 19))

@st.cache_data(ttl=60, show_spinner=False)
def fetch_signals(sid, short_n, long_n):
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            valid_ns = [n for n in [short_n, long_n] if pd.notna(n)]
            max_n = int(max(valid_ns) * 1.5) + 20 if valid_ns else 60
            max_n = max(max_n, 90)  # 確保至少有 90 天以上的歷史數據來精準計算斜線與水平線
            
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d"
            res = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
                
            data = res.json()['chart']['result'][0]
            quote = data['indicators']['quote'][0]
            
            # 過濾 None 並反轉數組，讓 index 0 代表最新的一天 (與 GAS 版本邏輯對齊)
            cls = [p for p in quote['close'] if p is not None][::-1]
            highs = [h for h in quote['high'] if h is not None][::-1]
            lows = [l for l in quote['low'] if l is not None][::-1]
            vols = [v for v in quote['volume'] if v is not None][::-1]
            
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
                cur_price = cls[0]
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
                
                if is_fugle_active:
                    Y_ma = get_ma(cls, n, 0)
                    B_ma = get_ma(cls, n, 1)
                    T_ma = get_ma([T_close] + cls, n, 0)
                else:
                    T_ma = get_ma(cls, n, 0)
                    Y_ma = get_ma(cls, n, 1)
                    B_ma = get_ma(cls, n, 2)
                
                if T_ma is None or Y_ma is None or B_ma is None: continue

                trend = "⬆️" if T_ma > Y_ma else "↘️"
                label_str = f"{label}({n}MA:{T_ma:.2f}){trend}"
                
                # 2日確認法則
                is_yesterday_breakout = (B_close < B_ma and Y_close > Y_ma)
                is_today_away = (T_low > T_ma)
                is_higher_than_yesterday = (T_close > Y_close)
                
                if is_yesterday_breakout and is_today_away and is_higher_than_yesterday:
                    signals.append(f"🔥2日法則(強勢突破){label_str}")
                    has_signal = True
                
                # 反2日假跌破
                y_break = (Y_close < Y_ma and B_close >= B_ma)
                if y_break and T_close > T_ma:
                    if (T_close - T_ma) / T_ma > 0.005:
                        signals.append(f"🔄反2日(假跌破){label_str}[強勢反轉]")
                    else:
                        signals.append(f"🔄反2日(假跌破){label_str}")
                    has_signal = True
                
                # 普通突破 / 跌破
                if Y_close >= Y_ma and T_close < T_ma:
                    signals.append(f"跌破{label_str}[停損]")
                    has_signal = True
                elif Y_close < Y_ma and T_close > T_ma and not any("假跌破" in s or "2日法則" in s for s in signals):
                    signals.append(f"突破{label_str}[進場1/2]")
                    has_signal = True

            # 2. 小箱型邏輯
            if not pd.isna(short_n):
                idx_offset = 1 if is_fugle_active else 2
                c_highs = [T_high, Y_high, highs[idx_offset]]
                c_lows = [T_low, Y_low, lows[idx_offset]]
                c_closes = [T_close, Y_close, cls[idx_offset]]
                c_vols = [vols[0], vols[1], vols[2]]
                maST = get_ma([T_close] + cls, int(short_n), 0) if is_fugle_active else get_ma(cls, int(short_n), 0)
                
                def is_touching(i):
                    ma = maST if i == 0 else (get_ma(cls, int(short_n), i - 1) if is_fugle_active else get_ma(cls, int(short_n), i))
                    if ma is None: return False
                    return c_highs[i] >= ma and c_lows[i] <= ma

                if maST and is_touching(0) and is_touching(1) and is_touching(2):
                    box_top = max(c_highs)
                    box_bottom = min(c_closes)
                    if T_close > max(box_top, maST * 1.015) and c_vols[0] > c_vols[1] * 1.2:
                        signals.append("💎小箱型突破(表態)")
                        has_signal = True
                    elif T_close < min(box_bottom, maST * 0.985):
                        signals.append("📉小箱型失守")
                        has_signal = True
                    else:
                        signals.append("⌛延續小箱型(盤整中)")
                        has_signal = True

            # 3. 軌道一：【水平線】狀態精準判定
            res_line = get_resonance_line(cls)
            is_res_out = (Y_close < res_line and T_close >= res_line)
            is_res_break = (Y_close >= res_line and T_close < res_line)
            
            if is_res_out:
                signals.append(f"🎯[水平線:共振壓力]突破({res_line:.2f})")
                has_signal = True
            elif is_res_break:
                signals.append(f"🎯[水平線:共振支撐]跌破({res_line:.2f})")
                has_signal = True
            elif abs(T_close - res_line) / res_line < 0.005:
                if T_close >= res_line:
                    signals.append(f"🎯[水平線:共振支撐]接近({res_line:.2f})")
                else:
                    signals.append(f"🎯[水平線:共振壓力]接近({res_line:.2f})")
                has_signal = True

            # 4. 軌道二：【斜線】趨勢線動態判定
            if len(highs) >= 51 and len(lows) >= 51:
                hIdx1, hVal1 = 1, highs[1]
                for i in range(2, 21):
                    if highs[i] > hVal1: hVal1 = highs[i]; hIdx1 = i
                hIdx2, hVal2 = 21, highs[21]
                for i in range(22, 51):
                    if highs[i] > hVal2: hVal2 = highs[i]; hIdx2 = i

                lIdx1, lVal1 = 1, lows[1]
                for i in range(2, 21):
                    if lows[i] < lVal1: lVal1 = lows[i]; lIdx1 = i
                lIdx2, lVal2 = 21, lows[21]
                for i in range(22, 51):
                    if lows[i] < lVal2: lVal2 = lows[i]; lIdx2 = i

                target_idx = -1 if is_fugle_active else 0
                y_idx = 0 if is_fugle_active else 1

                slopeH = (hVal1 - hVal2) / (hIdx1 - hIdx2) if (hIdx1 - hIdx2) != 0 else 0
                diagH_Today = hVal1 + slopeH * (target_idx - hIdx1)
                diagH_Yest = hVal1 + slopeH * (y_idx - hIdx1)

                slopeL = (lVal1 - lVal2) / (lIdx1 - lIdx2) if (lIdx1 - lIdx2) != 0 else 0
                diagL_Today = lVal1 + slopeL * (target_idx - lIdx1)
                diagL_Yest = lVal1 + slopeL * (y_idx - lIdx1)

                if Y_close < diagH_Yest and T_close >= diagH_Today:
                    signals.append(f"📐[斜線:趨勢壓力]突破({diagH_Today:.2f})")
                    has_signal = True
                elif Y_close >= diagL_Yest and T_close < diagL_Today:
                    signals.append(f"📐[斜線:趨勢支撐]跌破({diagL_Today:.2f})")
                    has_signal = True
                else:
                    if abs(T_close - diagH_Today) / diagH_Today < 0.005:
                        signals.append(f"📐[斜線:趨勢壓力]接近({diagH_Today:.2f})")
                        has_signal = True
                    if abs(T_close - diagL_Today) / diagL_Today < 0.005:
                        signals.append(f"📐[斜線:趨勢支撐]接近({diagL_Today:.2f})")
                        has_signal = True

            vol_tag = ""
            if len(vols) >= 2 and vols[0] > vols[1] * 1.25:
                vol_tag = "🔴量增"

            # 只要有觸發任何一個訊號就回傳
            if has_signal:
                return {"price": T_close, "signal": " + ".join(signals), "vol": vol_tag}
                
        except Exception: continue
    return None

@st.cache_data(ttl=60, show_spinner=False)
def run_scan():
    results = []
    csv_url = f"{SHEET_BASE}/export?format=csv&gid={TARGET_GID}&cb={int(time.time())}"
    try:
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df = pd.read_csv(io.StringIO(res.text))
        
        # 建立平行任務清單
        tasks = []
        for _, row in df.iterrows():
            sid_raw = row.iloc[0]
            if pd.isna(sid_raw): continue
            sid = str(sid_raw).strip()
            if sid.replace('.', '').replace('-', '').isdigit():
                sid = str(int(float(sid)))
            
            sn_raw = pd.to_numeric(row.iloc[2], errors='coerce')
            ln_raw = pd.to_numeric(row.iloc[3], errors='coerce')
            name = row.iloc[1]
            tasks.append((sid, sn_raw, ln_raw, name))
            
        # ⚡ 核心升級：使用 ThreadPoolExecutor 進行多執行緒平行高速抓取
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # 提交所有任務
            future_to_stock = {executor.submit(fetch_signals, t[0], t[1], t