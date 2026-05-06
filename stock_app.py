import streamlit as st
import pandas as pd
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-分頁監控版")

SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"

# 定義分頁 ID 與名稱的對應 (你可以根據實際名稱修改)
SHEET_MAP = {
    "0": "工作表1",
    "1241939414": "工作表2",
    "534437042": "工作表3"
}

def fetch_yahoo_data_sync(sid):
    """完全同步第一個程式的 Yahoo API 讀取邏輯"""
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=200d&interval=1d"
        try:
            res = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
            
            json_data = res.json()
            r = json_data['chart']['result'][0]
            q = r['indicators']['quote'][0]
            
            # 同步 GAS 資料處理：反轉並過濾空值
            closes = [p for p in reversed(q['close']) if p is not None]
            highs = [h for h in reversed(q['high']) if h is not None]
            lows = [l for l in reversed(q['low']) if l is not None]
            vols = [v for v in reversed(q['volume']) if v is not None]
            cur_price = r['meta']['regularMarketPrice']
            
            return {
                "p_list": [cur_price] + closes[1:],
                "highs": highs, "lows": lows, "vols": vols,
                "cur_price": cur_price
            }
        except: continue
    return None

def run_scan():
    # 改用字典來存儲，Key 為分頁名稱
    grouped_results = {name: [] for name in SHEET_MAP.values()}
    
    for gid, sheet_name in SHEET_MAP.items():
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=10)
            res.encoding = 'utf-8'
            raw_df = pd.read_csv(io.StringIO(res.text))
            
            for _, row in raw_df.iterrows():
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                if not sid_raw: continue
                
                s_ma_p = pd.to_numeric(row.iloc[2], errors='coerce')
                l_ma_p = pd.to_numeric(row.iloc[3], errors='coerce')
                
                # 沒填均線就跳過
                if pd.isna(s_ma_p) and pd.isna(l_ma_p): continue
                
                # 抓取資料
                data = fetch_yahoo_data_sync(sid_raw)
                if not data: continue
                
                # --- 箱型與均線邏輯 (同步 GAS) ---
                box_signal = ""
                if len(data['highs']) >= 6:
                    r_highs = data['highs'][1:6]
                    r_lows = data['lows'][1:6]
                    box_top, box_bottom = max(r_highs), min(r_lows)
                    
                    if (box_top - box_bottom) / box_bottom < 0.03:
                        v = data['vols']
                        if data['cur_price'] > box_top and v[0] > v[1] * 1.2:
                            box_signal = "🚀突破箱型"
                        elif data['cur_price'] < box_bottom:
                            box_signal = "💀跌破箱型"
                        else:
                            box_signal = "⌛盤整中"

                # 只有當「試算表有訊號」或「計算出箱型訊號」時才顯示
                sheet_sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                
                # 過濾：只保留有訊號的
                if not sheet_sign and not box_signal:
                    continue

                # 計算 MA
                def get_ma(arr, period):
                    if pd.isna(period): return None
                    sub = arr[:int(period)]
                    return sum(sub)/len(sub) if len(sub)>=period else None

                ma_s = get_ma(data['p_list'], s_ma_p)
                ma_l = get_ma(data['p_list'], l_ma_p)

                grouped_results[sheet_name].append({
                    "代號": sid_raw,
                    "名稱": row.iloc[1] if pd.notna(row.iloc[1]) else "未命名",
                    "現價": f"{data['cur_price']:.2f}",
                    "短均": f"{ma_s:.2f}" if ma_s else "--",
                    "長均": f"{ma_l:.2f}" if ma_l else "--",
                    "試算表訊號": sheet_sign,
                    "箱型判定": box_signal,
                    "量比": f"{data['vols'][0]/data['vols'][1]:.2f}x" if len(data['vols'])>1 else "1.0x"
                })
        except: continue
    return grouped_results

# --- 3. 呈現介面 ---
st.title("🐯 金虎南-多分頁訊號監控")

if "grouped_data" not in st.session_state:
    with st.spinner('掃描全部分頁中...'):
        st.session_state["grouped_data"] = run_scan()

if st.button("🔄 重新同步所有分頁"):
    del st.session_state["grouped_data"]
    st.rerun()

grouped_data = st.session_state.get("grouped_data", {})

# 依序顯示每個分頁
has_any_signal = False
for sheet_name, signals in grouped_data.items():
    if signals: # 只顯示有訊號的分頁
        has_any_signal = True
        st.subheader(f"📊 {sheet_name} (目前有 {len(signals)} 檔訊號)")
        st.dataframe(pd.DataFrame(signals), use_container_width=True, hide_index=True)
        st.divider()

if not has_any_signal:
    st.info("目前所有分頁皆無觸發訊號。")