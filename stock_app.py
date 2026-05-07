import streamlit as st
import pandas as pd
import requests
import io
import time

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-轉折監控")

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    table { width: 100% !important; font-size: 18px !important; }
    th { background-color: #f0f2f6 !important; }
    </style>
    """, unsafe_allow_html=True)

# 鎖定主試算表與單一分頁 (gid=0)
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
TARGET_GID = "0"
TARGET_NAME = "工作表1"

def fetch_signals(sid, short_n, long_n):
    """判定邏輯：僅保留 2 日法則與一般轉折，已移除反 2 日法則"""
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        valid_ns = [n for n in [short_n, long_n] if pd.notna(n)]
        max_n = int(max(valid_ns)) + 15 if valid_ns else 35
        
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d&t={time.time()}"
        try:
            res = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
            r = res.json()['chart']['result'][0]
            q = r['indicators']['quote'][0]
            
            cls = [p for p in q['close'] if p is not None]
            vols = [v for v in reversed(q['volume']) if v is not None]
            cur_price = r['meta']['regularMarketPrice']
            
            if len(cls) < 3: continue

            p0, p1, p2 = cur_price, cls[-2], cls[-3]
            
            signal_text = ""
            ma_list = [("短", short_n), ("長", long_n)]
            
            for label, n in ma_list:
                if pd.isna(n): continue
                n = int(n)
                ma0 = sum(cls[-n:]) / n
                ma1 = sum(cls[-n-1:-1]) / n
                ma2 = sum(cls[-n-2:-2]) / n

                # --- 2 日法則系列 ---
                if p1 > ma1 and p0 > ma0 and p0 > p1 and p2 <= ma2:
                    signal_text = f"2日法則強勢表態{label}({n}MA:{ma0:.2f}) ⬆️ [加碼 1/2]"
                    break

                # --- 一般站上/跌破 ---
                if p1 >= ma1 and p0 < ma0:
                    signal_text = f"跌破{label}({n}MA:{ma0:.2f}) 📉 [停損]"
                    break
                if p1 <= ma1 and p0 > ma0:
                    signal_text = f"站上{label}({n}MA:{ma0:.2f}) 📈"
                    break

            vol_tag = "🔴量增" if (len(vols) > 1 and vols[0] > vols[1] * 1.2) else ""
            if signal_text:
                return {"price": cur_price, "signal": signal_text, "vol": vol_tag}
        except: continue
    return None

def run_scan():
    results = []
    csv_url = f"{SHEET_BASE}/export?format=csv&gid={TARGET_GID}&cb={time.time()}"
    try:
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df = pd.read_csv(io.StringIO(res.text))
        for _, row in df.iterrows():
            sid_raw = row.iloc[0]
            if pd.isna(sid_raw): continue
            sid = str(int(float(sid_raw))) if str(sid_raw).replace('.','').isdigit() else str(sid_raw).strip()
            
            sn_raw = pd.to_numeric(row.iloc[2], errors='coerce')
            ln_raw = pd.to_numeric(row.iloc[3], errors='coerce')
            
            data = fetch_signals(sid, sn_raw, ln_raw)
            if data:
                results.append({
                    "代號": sid, 
                    "名稱": row.iloc[1], 
                    "短": int(sn_raw) if pd.notna(sn_raw) else "", 
                    "長": int(ln_raw) if pd.notna(ln_raw) else "",
                    "現價": f"{data['price']:.2f}", 
                    "訊號": data['signal'], 
                    "量能": data['vol']
                })
    except: pass
    return results

# --- 2. 介面呈現 ---
st.title("🐯 金虎南：轉折監控系統 (主表模式)")

if "data" not in st.session_state:
    st.session_state["data"] = run_scan()

if st.button("🔄 同步主表資料"):
    st.session_state["data"] = run_scan()
    st.rerun()

if st.session_state["data"]:
    st.subheader(f"📊 {TARGET_NAME} 監控結果")
    st.table(pd.DataFrame(st.session_state["data"]))
else:
    st.info(f"目前 {TARGET_NAME} 監控名單中無觸發訊號。")