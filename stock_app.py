import streamlit as st
import pandas as pd
import requests
import io
import time

# --- 1. 手機瀏覽器優化設定 (Meta Tags & CSS) ---
st.set_page_config(
    layout="wide", 
    page_title="金虎南監控",
    initial_sidebar_state="collapsed"
)

# 注入 CSS 確保手機版不跑版、字體清晰且不需縮放
st.markdown("""
    <style>
    /* 1. 全域間距優化 */
    .block-container { 
        padding-top: 1rem; 
        padding-bottom: 1rem; 
        padding-left: 0.5rem; 
        padding-right: 0.5rem; 
    }
    
    /* 2. 表格字體優化：讓手機看剛好，不需放大 */
    div[data-testid="stDataFrame"] td, div[data-testid="stDataFrame"] th {
        font-size: 15px !important;
        padding: 5px !important;
    }

    /* 3. 按鈕加大，方便手指點擊 */
    .stButton>button {
        width: 100%;
        height: 3rem;
        font-size: 18px !important;
        border-radius: 8px;
        background-color: #f0f2f6;
    }

    /* 4. 隱藏不必要的頁首元件 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
SHEET_MAP = {"0": "工作表1", "1241939414": "工作表2", "534437042": "工作表3"}

def fetch_signals(sid, short_n, long_n):
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        max_val = max(filter(pd.notna, [short_n, long_n])) if any(pd.notna([short_n, long_n])) else 20
        max_n = int(max_val) + 15
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d&t={time.time()}"
        try:
            res = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
            r = res.json()['chart']['result'][0]
            q = r['indicators']['quote'][0]
            cls = [p for p in q['close'] if p is not None]
            hi = [p for p in q['high'] if p is not None]
            lo = [p for p in q['low'] if p is not None]
            vols = [v for v in reversed(q['volume']) if v is not None]
            cur_price = r['meta']['regularMarketPrice']
            
            if len(cls) < 3: continue
            p0, p1, p2 = cur_price, cls[-2], cls[-3]
            h1, l1 = hi[-2], lo[-2]
            
            signal_text = ""
            ma_list = [("短", short_n), ("長", long_n)]
            
            for label, n in ma_list:
                if pd.isna(n): continue
                n = int(n)
                ma0 = sum(cls[-n:]) / n
                ma1 = sum(cls[-n-1:-1]) / n
                ma2 = sum(cls[-n-2:-2]) / n

                if p1 < ma1 and p0 > ma0:
                    signal_text = f"反2(假跌){label}({n}MA)"
                    break
                if p1 > ma1 and p0 < ma0:
                    signal_text = f"反2(假突){label}({n}MA)"
                    break
                if p1 > ma1 and l1 <= ma1 and p0 > p1:
                    signal_text = f"反2(支撐){label}({n}MA)"
                    break
                if p1 < ma1 and h1 >= ma1 and p0 < p1:
                    signal_text = f"反2(壓弱){label}({n}MA)"
                    break
                if p1 > ma1 and p0 > ma0 and p0 > p1 and p2 <= ma2:
                    signal_text = f"2日強勢{label}({n}MA)"
                    break
                if p1 >= ma1 and p0 < ma0:
                    signal_text = f"跌破{label}({n}MA)"
                    break
                if p1 <= ma1 and p0 > ma0:
                    signal_text = f"站上{label}({n}MA)"
                    break

            vol_tag = "🔴量增" if (len(vols) > 1 and vols[0] > vols[1] * 1.2) else ""
            if signal_text:
                return {"price": cur_price, "signal": signal_text, "vol": vol_tag}
        except: continue
    return None

def run_scan():
    results = {name: [] for name in SHEET_MAP.values()}
    for gid, sheet_name in SHEET_MAP.items():
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}&cb={time.time()}"
        try:
            res = requests.get(csv_url, timeout=10)
            res.encoding = 'utf-8'
            df = pd.read_csv(io.StringIO(res.text))
            for _, row in df.iterrows():
                sid_raw = row.iloc[0]
                if pd.isna(sid_raw): continue
                # 強制轉換代號與天數為整數，省空間
                sid = str(int(float(sid_raw))) if str(sid_raw).replace('.','').isdigit() else str(sid_raw)
                sn_raw = pd.to_numeric(row.iloc[2], errors='coerce')
                ln_raw = pd.to_numeric(row.iloc[3], errors='coerce')
                
                data = fetch_signals(sid, sn_raw, ln_raw)
                if data:
                    results[sheet_name].append({
                        "代號": sid, 
                        "名稱": row.iloc[1][:4], # 限制名稱最多4個字
                        "短": int(sn_raw) if pd.notna(sn_raw) else "", 
                        "長": int(ln_raw) if pd.notna(ln_raw) else "",
                        "現價": f"{data['price']:.1f}", 
                        "訊號": data['signal'], 
                        "量": data['vol']
                    })
        except: continue
    return results

# --- 2. 介面呈現 ---
st.subheader("🐯 金虎南監控 (手機版)")

if "data" not in st.session_state:
    st.session_state["data"] = run_scan()

if st.button("🔄 點擊刷新 (同步試算表)"):
    st.session_state["data"] = run_scan()
    st.rerun()

found_any = False
for s_name, signals in st.session_state["data"].items():
    if signals:
        found_any = True
        st.write(f"📌 {s_name}")
        # 使用 Streamlit 內建的寬度自動適應，並隱藏序號
        st.dataframe(
            pd.DataFrame(signals), 
            use_container_width=True, 
            hide_index=True
        )

if not found_any:
    st.info("目前無轉折訊號。")