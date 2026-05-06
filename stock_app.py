import streamlit as st
import pandas as pd
import requests
import io
import time

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-戰情監控版")

# 強制優化網頁邊距，讓表格佔滿畫面
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    </style>
    """, unsafe_allow_html=True)

SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
SHEET_MAP = {
    "0": "工作表1",
    "1241939414": "工作表2",
    "534437042": "工作表3"
}

def fetch_yahoo_data_sync(sid):
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        # 加入 time 參數防止抓到舊的 API 暫存
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=200d&interval=1d&t={time.time()}"
        try:
            res = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
            r = res.json()['chart']['result'][0]
            q = r['indicators']['quote'][0]
            closes = [p for p in reversed(q['close']) if p is not None]
            highs = [h for h in reversed(q['high']) if h is not None]
            lows = [l for l in reversed(q['low']) if l is not None]
            vols = [v for v in reversed(q['volume']) if v is not None]
            cur_price = r['meta']['regularMarketPrice']
            # p_list 同步第一個程式邏輯: [現價] + [歷史收盤1...]
            return {"p_list": [cur_price] + closes[1:], "highs": highs, "lows": lows, "vols": vols, "cur_price": cur_price}
        except: continue
    return None

def run_scan():
    grouped_results = {name: [] for name in SHEET_MAP.values()}
    for gid, sheet_name in SHEET_MAP.items():
        # 強制 Google Sheets 刷新暫存
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}&cb={time.time()}"
        try:
            res = requests.get(csv_url, timeout=10)
            res.encoding = 'utf-8'
            raw_df = pd.read_csv(io.StringIO(res.text))
            for _, row in raw_df.iterrows():
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                if not sid_raw: continue
                
                s_ma_p = pd.to_numeric(row.iloc[2], errors='coerce')
                l_ma_p = pd.to_numeric(row.iloc[3], errors='coerce')
                if pd.isna(s_ma_p) and pd.isna(l_ma_p): continue
                
                data = fetch_yahoo_data_sync(sid_raw)
                if not data: continue
                
                # 箱型判定邏輯 (同步第一個程式)
                box_status = ""
                if len(data['highs']) >= 6:
                    r_h, r_l = data['highs'][1:6], data['lows'][1:6]
                    bt, bb = max(r_h), min(r_l)
                    if (bt - bb) / bb < 0.03:
                        v = data['vols']
                        if data['cur_price'] > bt and v[0] > v[1] * 1.2:
                            box_status = "🚀突破箱型"
                        elif data['cur_price'] < bb:
                            box_status = "💀跌破箱型"
                        else:
                            box_status = "⌛盤整中"

                sheet_sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                
                # 只保留有訊號的
                if not sheet_sign and not box_status: continue

                vol_tag = "🔴量增" if (len(data['vols'])>1 and data['vols'][0] > data['vols'][1]*1.2) else ""

                grouped_results[sheet_name].append({
                    "代號": sid_raw,
                    "名稱": row.iloc[1] if pd.notna(row.iloc[1]) else "未命名",
                    "現價": f"{data['cur_price']:.2f}",
                    "試算表訊號": sheet_sign,
                    "箱型判定": box_status,
                    "成交量": vol_tag
                })
        except: continue
    return grouped_results

# --- 介面呈現 ---
st.title("🐯 金虎南-全訊號監控 (自動撐開版)")

if "data" not in st.session_state:
    st.session_state["data"] = run_scan()

# 顯示清除暫存按鈕
if st.button("🔄 徹底清除暫存並重新抓取資料"):
    if "data" in st.session_state:
        del st.session_state["data"]
    st.rerun()

gd = st.session_state["data"]
has_any = False

for s_name, signals in gd.items():
    if signals:
        has_any = True
        st.subheader(f"📊 {s_name} (有 {len(signals)} 檔訊號)")
        
        # 使用 st.dataframe 並設定 height=None，會根據內容自動撐開高度，不產生內部捲軸
        st.dataframe(
            pd.DataFrame(signals),
            use_container_width=True,
            hide_index=True,
            height=None  # 關鍵設定：讓表格有多少行就長多高
        )
        st.divider()

if not has_any:
    st.info("目前所有分頁皆無觸發訊號。")