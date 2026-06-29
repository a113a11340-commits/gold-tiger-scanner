import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures  # 導入多執行緒平行加速庫
import plotly.graph_objects as go  # 導入進階圖表庫

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
            # 【修正點 1】拉大歷史資料範圍至 120 天，確保計算長天期均線時有足夠後方數據，均線才不會斷掉
            max_n = max(int(max(valid_ns)) + 60 if valid_ns else 60, 120)
            
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
                    t_highs.append(raw_high[i])
                    t_lows.append(raw_low[i])
                    t_opens.append(raw_op[i])
                    t_vols.append(raw_vol[i] if raw_vol[i] is not None else 0)
                    if i < len(timestamps):
                        t_dates.append(time.strftime('%Y-%m-%d', time.localtime(timestamps[i])))
                    else:
                        t_dates.append("")
            
            # 先保持正序（歷史到最新）來計算訊號
            cls = t_cls[::-1]
            highs = t_highs[::-1]
            lows = t_lows[::-1]
            opens = t_opens[::-1]
            vols = t_vols[::-1]
            dates = t_dates[::-1]
            
            req_len = int(max(valid_ns)) + 3 if valid_ns else 10
            if len(cls) < req_len: continue

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
            signal_types = set()
            
            # 核心：均線與二日法則判定
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
                
                is_yesterday_breakout = (B_close < B_ma and Y_close > Y_ma)
                is_today_away = (T_low > T_ma)
                is_higher_than_yesterday = (T_close > Y_close)
                
                if is_yesterday_breakout and is_today_away and is_higher_than_yesterday:
                    signals.append(f"🔥2日法則(強勢突破){label_str}")
                    has_signal = True
                    signal_types.add("MA")
                
                y_break = (Y_close < Y_ma and B_close >= B_ma)
                if y_break and T_close > T_ma:
                    if (T_close - T_ma) / T_ma > 0.005:
                        signals.append(f"🔄反2日(假跌破){label_str}[強勢反轉]")
                    else:
                        signals.append(f"🔄反2日(假跌破){label_str}")
                    has_signal = True
                    signal_types.add("MA")
                
                if Y_close >= Y_ma and T_close < T_ma:
                    signals.append(f"跌破{label_str}[停損]")
                    has_signal = True
                    signal_types.add("MA")
                elif Y_close < Y_ma and T_close > T_ma and not any("假跌破" in s or "2日法則" in s for s in signals):
                    signals.append(f"突破{label_str}[進場1/2]")
                    has_signal = True
                    signal_types.add("MA")

            # 將即時數據合併進去
            if is_fugle_active:
                cls = [T_close] + cls
                highs = [T_high] + highs
                lows = [T_low] + lows
                opens = [f_data.get('open', T_close)] + opens
                dates = [time.strftime('%Y-%m-%d')] + dates
                vols = [f_data.get('volume', 0)] + vols

            vol_tag = ""
            if len(vols) >= 2 and vols[0] > vols[1] * 1.25:
                vol_tag = "🔴量增"

            # 【修正點 2】重新設計均線畫圖陣列：從最新的 K 線往前算 60 根，因為有 120 天歷史當後盾，這 60 根均線絕不會變短或斷掉
            plot_ma_short, plot_ma_long = [], []
            for i in range(60):
                if i >= len(cls): break
                plot_ma_short.append(get_ma(cls, int(short_n), i) if pd.notna(short_n) else None)
                plot_ma_long.append(get_ma(cls, int(long_n), i) if pd.notna(long_n) else None)
                    
            slice_len = min(60, len(cls))
            p_data = {
                "dates": dates[:slice_len][::-1],
                "opens": opens[:slice_len][::-1],
                "highs": highs[:slice_len][::-1],
                "lows": lows[:slice_len][::-1],
                "closes": cls[:slice_len][::-1],
                "ma_s": plot_ma_short[:slice_len][::-1],
                "ma_l": plot_ma_long[:slice_len][::-1]
            }

            if has_signal:
                return {
                    "price": T_close, 
                    "signal": " + ".join(signals), 
                    "vol": vol_tag, 
                    "plot_data": p_data,
                    "signal_types": list(signal_types)
                }
        except Exception: continue
    return None

def run_scan_for_sheet(sheet_name, gid):
    results = []
    csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}&cb={int(time.time())}"
    try:
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df = pd.read_csv(io.StringIO(res.text))
        
        tasks = []
        for _, row in df.iterrows():
            if df.shape[1] < 4: continue
            sid_raw = row.iloc[0]
            if pd.isna(sid_raw): continue
            sid = str(sid_raw).strip()
            if sid.replace('.', '').replace('-', '').isdigit():
                sid = str(int(float(sid)))
            
            sn_raw = pd.to_numeric(row.iloc[2], errors='coerce')
            ln_raw = pd.to_numeric(row.iloc[3], errors='coerce')
            name = row.iloc[1]
            tasks.append((sid, sn_raw, ln_raw, name))
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_stock = {}
            for t in tasks:
                f_obj = executor.submit(fetch_signals, t[0], t[1], t[2])
                future_to_stock[f_obj] = t
            
            for future in concurrent.futures.as_completed(future_to_stock):
                t = future_to_stock[future]
                sid, sn_raw, ln_raw, name = t[0], t[1], t[2], t[3]
                try:
                    data = future.result()
                    if data:
                        results.append({
                            "來源工作表": sheet_name, "代號": sid, "名稱": name, 
                            "短": int(sn_raw) if pd.notna(sn_raw) else "",
                            "長": int(ln_raw) if pd.notna(ln_raw) else "", 
                            "現價": f"{data['price']:.2f}", "訊號": data['signal'], "量能": data['vol'],
                            "plot_data": data.get("plot_data"), "signal_types": data.get("signal_types", [])
                        })
                except Exception: pass
    except Exception as e:
        st.error(f"讀取分頁【{sheet_name}】失敗: {e}")
    return results

def run_all_scans():
    all_results = []
    for sheet in MONITOR_SHEETS:
        all_results.extend(run_scan_for_sheet(sheet["name"], sheet["gid"]))
    return all_results

st.title("🐯 金虎南：轉折監控系統 (純均線與2日法則版)")
update_time = time.strftime("%Y-%m-%d %H:%M:%S")
st.caption(f"最後更新時間：{update_time}（主頁+工作表20連動｜已移除小箱型、共振線、動態斜線）")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 同步所有分頁資料", use_container_width=True):
        st.session_state["all_data"] = run_all_scans()
        st.rerun()
with col2:
    if st.button("🚀 強制刷新即時報價", type="primary", use_container_width=True):
        fetch_signals.clear()
        st.session_state["all_data"] = run_all_scans()
        st.rerun()

if "all_data" not in st.session_state: st.session_state["all_data"] = run_all_scans()

if st.session_state["all_data"]:
    st.subheader(f"📊 綜合監控結果 (共觸發 {len(st.session_state['all_data'])} 檔個股)")
    df_display = pd.DataFrame(st.session_state["all_data"]).drop(columns=["plot_data", "signal_types"], errors="ignore")
    cols = ['來源工作表'] + [col for col in df_display.columns if col != '來源工作表']
    st.dataframe(df_display[cols], use_container_width=True, hide_index=True)
    
    st.markdown("---")
    st.subheader("📈 觸發個股 K 線軌道圖 (純均線軌道指標)")
    
    for item in st.session_state["all_data"]:
        p = item.get("plot_data")
        sig_text = item["訊號"]
        
        if p:
            with st.expander(f"🔍 [{item['來源工作表']}] {item['代號']} {item['名稱']} — 【{sig_text}】", expanded=False):
                fig = go.Figure()
                
                # 1. 台灣標準 K 線
                fig.add_trace(go.Candlestick(
                    x=p["dates"], open=p["opens"], high=p["highs"], low=p["lows"], close=p["closes"],
                    increasing_line_color='#FF3333', increasing_fillcolor='#FF3333',
                    decreasing_line_color='#00A600', decreasing_fillcolor='#00A600',
                    line_width=1.8, name='K線'
                ))
                
                # 2. 均線繪製：不管有沒有觸發均線訊號，只要有設定天期，都強制畫滿 60 根
                if any(x is not None for x in p["ma_s"]):
                    fig.add_trace(go.Scatter(x=p["dates"], y=p["ma_s"], mode='lines', name='短均線', line=dict(color='#FFA500', width=1.8)))
                if any(x is not None for x in p["ma_l"]):
                    fig.add_trace(go.Scatter(x=p["dates"], y=p["ma_l"], mode='lines', name='長均線', line=dict(color='#1E90FF', width=1.8)))
                
                # 圖表佈局優化
                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    margin=dict(l=10, r=10, t=20, b=10),
                    height=380,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
                )
                
                # 徹底去除假日空白
                fig.update_xaxes(type='category', tickangle=-45, nticks=15)
                
                # 保持為原本的靜態網頁圖表（staticPlot: True），無滑鼠點擊互動與縮放
                st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
else: 
    st.info("目前所有監控分頁中皆無觸發訊號。")
