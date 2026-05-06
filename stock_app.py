import streamlit as st
import pandas as pd
import requests
import io
import time

# --- 1. 手機優化樣式 ---
st.set_page_config(layout="wide", page_title="金虎南監控")

st.markdown("""
    <style>
    .block-container { padding: 1rem 0.5rem; }
    div[data-testid="stDataFrame"] td, div[data-testid="stDataFrame"] th { font-size: 15px !important; }
    .stButton>button { width: 100%; height: 3rem; background-color: #ff4b4b; color: white; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
SHEET_MAP = {"0": "工作表1", "1241939414": "工作表2", "534437042": "工作表3"}

def fetch_signals(sid, short_n, long_n):
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            # 限制抓取天數，減少被封鎖機率
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=100d&interval=1d"
            res = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
            
            data = res.json()['chart']['result'][0]
            cur_price = data['meta']['regularMarketPrice']
            q = data['indicators']['quote'][0]
            cls = [p for p in q['close'] if p is not None]
            hi = [p for p in q['high'] if p is not None]
            lo = [p for p in q['low'] if p is not None]
            vol = [v for v in q['volume'] if v is not None]

            if len(cls) < 65: continue # 確保資料夠算長均線

            p0, p1, p2 = cur_price, cls[-1], cls[-2]
            h1, l1 = hi[-1], lo[-1]
            
            signal_text = ""
            # 只檢查有數值的均線
            valid_ma = []
            if pd.notna(short_n): valid_ma.append(("短", int(short_n)))
            if pd.notna(long_n): valid_ma.append(("長", int(long_n)))

            for label, n in valid_ma:
                ma0 = sum(cls[-n:]) / n
                ma1 = sum(cls[-n-1:-1]) / n
                ma2 = sum(cls[-n-2:-2]) / n

                if p1 < ma1 and p0 > ma0: signal_text = f"反2(假跌){label}"; break
                if p1 > ma1 and p0 < ma0: signal_text = f"反2(假突){label}"; break
                if p1 > ma1 and l1 <= ma1 and p0 > p1: signal_text = f"反2(支撐){label}"; break
                if p1 < ma1 and h1 >= ma1 and p0 < p1: signal_text = f"反2(壓弱){label}"; break
                if p1 > ma1 and p0 > ma0 and p0 > p1 and p2 <= ma2: signal_text = f"2日強勢{label}"; break
                if p1 >= ma1 and p0 < ma0: signal_text = f"跌破{label}"; break
                if p1 <= ma1 and p0 > ma0: signal_text = f"站上{label}"; break

            v_tag = "🔴量增" if (len(vol) > 1 and vol[-1] > vol[-2] * 1.2) else ""
            if signal_text:
                return {"price": cur_price, "signal": signal_text, "vol": v_tag}
        except: continue
    return None

def run_scan():
    results = {}
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, (gid, name) in enumerate(SHEET_MAP.items()):
        status_text.text(f"正在掃描：{name}...")
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}"
        try:
            df = pd.read_csv(io.StringIO(requests.get(csv_url).text))
            sheet_results = []
            for _, row in df.iterrows():
                sid_raw = row.iloc[0]
                if pd.isna(sid_raw): continue
                sid = str(int(float(sid_raw))) if str(sid_raw).replace('.','').isdigit() else str(sid_raw)
                
                data = fetch_signals(sid, row.iloc[2], row.iloc[3])
                if data:
                    sheet_results.append({
                        "代號": sid, "名稱": str(row.iloc[1])[:4],
                        "現價": f"{data['price']:.1f}", "訊號": data['signal'], "量": data['vol']
                    })
            if sheet_results: results[name] = sheet_results
        except: continue
        progress_bar.progress((idx + 1) / len(SHEET_MAP))
    
    progress_bar.empty()
    status_text.empty()
    return results

# --- 2. 介面 ---
st.subheader("🐯 金虎南監控 (強韌版)")

if st.button("🚀 點我開始掃描訊號"):
    st.session_state["scan_results"] = run_scan()

if "scan_results" in st.session_state:
    if st.session_state["scan_results"]:
        for s_name, signals in st.session_state["scan_results"].items():
            st.write(f"📌 {s_name}")
            st.dataframe(pd.DataFrame(signals), use_container_width=True, hide_index=True)
    else:
        st.info("掃描完成，目前無訊號。")