import streamlit as st
import pandas as pd
import requests
import io
import time

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-轉折監控")

# --- 新增：富果 API 設定 ---
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

def calc_ma_by_index(cls, end_idx, n):
    if end_idx == 0:
        sub_list = cls
    else:
        sub_list = cls[:-end_idx]
        
    if len(sub_list) < n or n < 1:
        return None
    return sum(sub_list[-n:]) / n

@st.cache_data(ttl=60, show_spinner="正在抓取資料...")
def fetch_signals(sid, short_n, long_n):
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            valid_ns = [n for n in [short_n, long_n] if pd.notna(n)]
            max_n = int(max(valid_ns) * 1.5) + 20 if valid_ns else 60
            
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d"
            res = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
                
            data = res.json()['chart']['result'][0]
            quote = data['indicators']['quote'][0]
            cls = [p for p in quote['close'] if p is not None]
            volumes = [v for v in quote['volume'] if v is not None]
            
            if len(cls) < 5: continue

            # --- 核心修改：獲取即時價格 (富果 API) ---
            f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
            f_res = requests.get(f_url, headers={"X-API-KEY": FUGLE_KEY}, timeout=5)
            if f_res.status_code == 200:
                cur_price = f_res.json()['data']['quote'].get('price', cls[-1])
            else:
                cur_price = cls[-1]
            
            cls[-1] = cur_price
            p0, p1, p2 = cls[-1], cls[-2], cls[-3] if len(cls) >= 3 else cls[-2]
            
            signal_text = ""
            ma_list = [("短", short_n), ("長", long_n)]
            
            for label, n in ma_list:
                if pd.isna(n): continue
                n = int(n)
                ma0 = calc_ma_by_index(cls, 0, n)
                ma1 = calc_ma_by_index(cls, 1, n)
                ma2 = calc_ma_by_index(cls, 2, n)
                
                if ma0 is None or ma1 is None or ma2 is None: continue

                if p1 > ma1 and p0 > ma0 and p0 > p1 and p2 <= ma2:
                    signal_text = f"2日法則強勢表態{label}({n}MA:{ma0:.2f}) ⬆️ [加碼 1/2]"
                    break
                if p1 >= ma1 and p0 < ma0:
                    signal_text = f"跌破{label}({n}MA:{ma0:.2f}) 📉 [停損]"
                    break
                if p1 <= ma1 and p0 > ma0:
                    signal_text = f"站上{label}({n}MA:{ma0:.2f}) 📈"
                    break

            vol_tag = ""
            if len(volumes) >= 2 and volumes[-1] > volumes[-2] * 1.25:
                vol_tag = "🔴量增"

            if signal_text:
                return {"price": cur_price, "signal": signal_text, "vol": vol_tag}
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
        for _, row in df.iterrows():
            sid_raw = row.iloc[0]
            if pd.isna(sid_raw): continue
            sid = str(sid_raw).strip()
            if sid.replace('.', '').replace('-', '').isdigit():
                sid = str(int(float(sid)))
            sn_raw = pd.to_numeric(row.iloc[2], errors='coerce')
            ln_raw = pd.to_numeric(row.iloc[3], errors='coerce')
            data = fetch_signals(sid, sn_raw, ln_raw)
            if data:
                results.append({
                    "代號": sid, "名稱": row.iloc[1], "短": int(sn_raw) if pd.notna(sn_raw) else "",
                    "長": int(ln_raw) if pd.notna(ln_raw) else "", "現價": f"{data['price']:.2f}",
                    "訊號": data['signal'], "量能": data['vol']
                })
    except Exception as e: st.error(f"讀取 Google Sheet 失敗: {e}")
    return results

st.title("🐯 金虎南：轉折監控系統 (主表模式)")
update_time = time.strftime("%Y-%m-%d %H:%M:%S")
st.caption(f"最後更新時間：{update_time}（快取60秒）")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 同步主表資料", use_container_width=True):
        st.session_state["data"] = run_scan()
        st.rerun()
with col2:
    if st.button("🚀 強制刷新即時報價", type="primary", use_container_width=True):
        run_scan.clear()
        fetch_signals.clear()
        st.session_state["data"] = run_scan()
        st.rerun()

if "data" not in st.session_state: st.session_state["data"] = run_scan()
if st.session_state["data"]:
    st.subheader(f"📊 {TARGET_NAME} 監控結果 ({len(st.session_state['data'])} 檔觸發)")
    st.dataframe(pd.DataFrame(st.session_state["data"]), use_container_width=True, hide_index=True)
else: st.info(f"目前 {TARGET_NAME} 監控名單中無觸發訊號。")