import streamlit as st
import pandas as pd
import requests
import io
import time

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-轉折監控")

# --- API 設定檢查 ---
if "FUGLE_API_KEY" not in st.secrets:
    st.error("請在 .streamlit/secrets.toml 中設定 FUGLE_API_KEY")
    st.stop()

# 鎖定主試算表
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
TARGET_GID = "0"
TARGET_NAME = "工作表1"

# --- 核心函式 ---

def get_fugle_price(sid):
    """取得富果即時成交價"""
    try:
        # 免費版 API 使用的 URL
        url = f"https://api.fugle.tw/marketdata/v0.3/intraday/quote?symbolId={sid}&apiToken={st.secrets['FUGLE_API_KEY']}"
        res = requests.get(url, timeout=5)
        data = res.json()
        return data['data']['quote']['trade']['price']
    except:
        return None

def calc_ma_by_index(cls, end_idx, n):
    sub_list = cls if end_idx == 0 else cls[:-end_idx]
    if len(sub_list) < n or n < 1: return None
    return sum(sub_list[-n:]) / n

@st.cache_data(ttl=60, show_spinner="正在獲取行情...")
def fetch_signals(sid, short_n, long_n):
    # 1. 獲取 Yahoo 歷史資料 (計算 MA 用)
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=60d&interval=1d"
            res = requests.get(url, timeout=5)
            if res.status_code != 200: continue
            
            data = res.json()['chart']['result'][0]
            quote = data['indicators']['quote'][0]
            cls = [p for p in quote['close'] if p is not None]
            
            # 2. 替換今日價格為富果即時價
            live_price = get_fugle_price(sid)
            if live_price:
                cls[-1] = live_price
            
            p0, p1, p2 = cls[-1], cls[-2], cls[-3]
            
            # 3. 判斷邏輯
            signal_text = ""
            for label, n in [("短", short_n), ("長", long_n)]:
                if pd.isna(n): continue
                n = int(n)
                ma0 = calc_ma_by_index(cls, 0, n)
                ma1 = calc_ma_by_index(cls, 1, n)
                ma2 = calc_ma_by_index(cls, 2, n)
                
                if not all([ma0, ma1, ma2]): continue

                if p1 > ma1 and p0 > ma0 and p0 > p1 and p2 <= ma2:
                    signal_text = f"2日強勢表態{label}({n}MA:{ma0:.2f}) ⬆️"
                    break
                if p1 >= ma1 and p0 < ma0:
                    signal_text = f"跌破{label}({n}MA:{ma0:.2f}) 📉"
                    break
                if p1 <= ma1 and p0 > ma0:
                    signal_text = f"站上{label}({n}MA:{ma0:.2f}) 📈"
                    break

            if signal_text:
                return {"price": cls[-1], "signal": signal_text}
        except:
            continue
    return None

@st.cache_data(ttl=60, show_spinner=False)
def run_scan():
    results = []
    csv_url = f"{SHEET_BASE}/export?format=csv&gid={TARGET_GID}"
    try:
        df = pd.read_csv(io.StringIO(requests.get(csv_url).text))
        for _, row in df.iterrows():
            sid = str(int(float(row.iloc[0])))
            data = fetch_signals(sid, row.iloc[2], row.iloc[3])
            if data:
                results.append({"代號": sid, "名稱": row.iloc[1], "現價": f"{data['price']:.2f}", "訊號": data['signal']})
    except Exception as e:
        st.error(f"錯誤: {e}")
    return results

# --- 主介面 ---
st.title("🐯 金虎南：轉折監控 (即時版)")
if st.button("🔄 刷新即時數據"):
    st.cache_data.clear()
    st.rerun()

results = run_scan()
if results:
    st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
else:
    st.info("暫無觸發訊號。")