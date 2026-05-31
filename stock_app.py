import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import plotly.graph_objects as go

st.set_page_config(layout="wide", page_title="金虎南-轉折監控")

def get_ma(arr, period, offset=0):
    sub = arr[offset:offset+period]
    return sum(sub) / period if len(sub) == period else None

def get_resonance_line(data):
    if not data: return 0
    v_min, v_max = min(data), max(data)
    v_range = v_max - v_min
    if v_range <= 0: return data[0]
    buckets = [0] * 20
    for p in data:
        idx = int(((p - v_min) / v_range) * 19)
        buckets[max(0, min(19, idx))] += 1
    max_idx = buckets.index(max(buckets))
    return v_min + (max_idx * (v_range / 19))
@st.cache_data(ttl=60, show_spinner=False)
def fetch_signals(sid, sn, ln):
    for sfx in [".TW", ".TWO"]:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=90d&interval=1d"
            res = requests.get(url, timeout=5)
            if res.status_code != 200: continue
            data = res.json()['chart']['result'][0]
            q = data['indicators']['quote'][0]
            cls = q['close'][::-1]
            highs = q['high'][::-1]
            lows = q['low'][::-1]
            
            # 獲取即時價
            f_res = requests.get(f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}", timeout=3)
            f_data = f_res.json().get('data', {}).get('quote', {}) if f_res.status_code == 200 else {}
            curr = f_data.get('price', cls[0])
            
            sigs = []
            res_line = get_resonance_line(cls)
            ma_s = get_ma([curr]+cls, int(sn)) if pd.notna(sn) else None
            ma_l = get_ma([curr]+cls, int(ln)) if pd.notna(ln) else None
            
            if sn and cls[1] < get_ma(cls, int(sn), 1) and curr > ma_s: sigs.append("短均突破")
            if ln and cls[1] < get_ma(cls, int(ln), 1) and curr > ma_l: sigs.append("長均突破")
            if cls[1] < res_line and curr >= res_line: sigs.append("水平共振線突破")
            
            if sigs:
                return {"price": curr, "signal": " + ".join(sigs), "cls": cls[:60], "highs": highs[:60], "lows": lows[:60], "opens": cls[:60], "ma_s": ma_s, "ma_l": ma_l, "res": res_line}
        except: continue
    return None
def run_scan():
    results = []
    # 請將您的 CSV 讀取路徑放這裡
    df = pd.read_csv(io.StringIO(requests.get("您的GoogleSheet網址/export?format=csv").text))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_signals, str(row[0]), row[2], row[3]): row for _, row in df.iterrows()}
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                results.append({"代號": str(futures[f][0]), "名稱": futures[f][1], "訊號": res["signal"], "plot": res})
    return results
st.title("🐯 金虎南：轉折監控")
if st.button("🔄 同步"):
    st.session_state["data"] = run_scan()
    st.rerun()

if "data" in st.session_state:
    for item in st.session_state["data"]:
        sig = item["訊號"]
        p = item["plot"]
        with st.expander(f"🔍 {item['代號']} {item['名稱']} — 【{sig}】"):
            fig = go.Figure()
            # 修正參數：確保每個 key 都給定值
            fig.add_trace(go.Candlestick(x=list(range(len(p["cls"]))), open=p["opens"], high=p["highs"], low=p["lows"], close=p["cls"], name="K線"))
            
            if "短均突破" in sig:
                fig.add_trace(go.Scatter(y=[p["ma_s"]]*60, mode='lines', name="短均線"))
            if "水平共振線" in sig:
                fig.add_trace(go.Scatter(y=[p["res"]]*60, mode='lines', name="水平共振線", line=dict(dash='dash')))
            
            fig.update_layout(xaxis_rangeslider_visible=False, height=400)
            st.plotly_chart(fig, use_container_width=True)
