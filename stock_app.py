import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures  # 導入多執行緒平行加速庫
import plotly.graph_objects as go  # 導入進階圖表庫

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
            max_n = max(max_n, 90)  # 確保歷史數據足夠計算
            
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d"
            res = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue
                
            data = res.json()['chart']['result'][0]
            quote = data['indicators']['quote'][0]
            timestamps = data.get('timestamp', [])
            
            # 對齊並過濾無效數據
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
                        
            # 反轉數組，讓 index 0 代表最新的一天
            cls = t_cls[::-1]
            highs = t_highs[::-1]
            lows = t_lows[::-1]
            opens = t_opens[::-1]
            vols = t_vols[::-1]
            dates = t_dates[::-1]
            
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
            
            # 用於判斷圖表畫線類型的標籤計數
            signal_types = set()

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
                        signal_types.add("MA")
                    elif T_close < min(box_bottom, maST * 0.985):
                        signals.append("📉小箱型失守")
                        has_signal = True
                        signal_types.add("MA")
                    else:
                        signals.append("⌛延續小箱型(盤整中)")
                        has_signal = True
                        signal_types.add("MA")

            # 3. 軌道一：【水平線】狀態精準判定
            res_line = get_resonance_line(cls if not is_fugle_active else cls[1:])
            is_res_out = (Y_close < res_line and T_close >= res_line)
            is_res_break = (Y_close >= res_line and T_close < res_line)
            
            if is_res_out:
                signals.append(f"🎯[水平線:共振壓力]突破({res_line:.2f})")
                has_signal = True
                signal_types.add("HORIZONTAL")
            elif is_res_break:
                signals.append(f"🎯[水平線:共振支撐]跌破({res_line:.2f})")
                has_signal = True
                signal_types.add("HORIZONTAL")
            elif abs(T_close - res_line) / res_line < 0.005:
                if T_close >= res_line:
                    signals.append(f"🎯[水平線:共振支撐]接近({res_line:.2f})")
                else:
                    signals.append(f"🎯[水平線:共振壓力]接近({res_line:.2f})")
                has_signal = True
                signal_types.add("HORIZONTAL")

            # 4. 軌道二：【斜線】趨勢線動態判定
            slopeH, slopeL = 0, 0
            hIdx1, hVal1, hIdx2, hVal2 = 0, 0, 0, 0
            lIdx1, lVal1, lIdx2, lVal2 = 0, 0, 0, 0
            
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
                    signal_types.add("SLOPE")
                elif Y_close >= diagL_Yest and T_close < diagL_Today:
                    signals.append(f"📐[斜線:趨勢支撐]跌破({diagL_Today:.2f})")
                    has_signal = True
                    signal_types.add("SLOPE")
                else:
                    if abs(T_close - diagH_Today) / diagH_Today < 0.005:
                        signals.append(f"📐[斜線:趨勢壓力]接近({diagH_Today:.2f})")
                        has_signal = True
                        signal_types.add("SLOPE")
                    if abs(T_close - diagL_Today) / diagL_Today < 0.005:
                        signals.append(f"📐[斜線:趨勢支撐]接近({diagL_Today:.2f})")
                        has_signal = True
                        signal_types.add("SLOPE")

            # 若富果活躍，將今日即時數據塞入最前端以便產出圖表
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

            # 預先生成 3 個月 (60天) 圖表所需的軌道數據線
            plot_ma_short = []
            plot_ma_long = []
            plot_diagH = []
            plot_diagL = []
            plot_res = []
            
            for i in range(60):
                if i >= len(cls): break
                plot_ma_short.append(get_ma(cls, int(short_n), i) if pd.notna(short_n) else None)
                plot_ma_long.append(get_ma(cls, int(long_n), i) if pd.notna(long_n) else None)
                plot_res.append(res_line)
                
                if len(highs) >= 51:
                    hist_idx = (i - 1) if is_fugle_active else i
                    plot_diagH.append(hVal1 + slopeH * (hist_idx - hIdx1))
                    plot_diagL.append(lVal1 + slopeL * (hist_idx - lIdx1))
                else:
                    plot_diagH.append(None)
                    plot_diagL.append(None)
                    
            slice_len = min(60, len(cls))
            p_data = {
                "dates": dates[:slice_len][::-1],
                "opens": opens[:slice_len][::-1],
                "highs": highs[:slice_len][::-1],
                "lows": lows[:slice_len][::-1],
                "closes": cls[:slice_len][::-1],
                "ma_s": plot_ma_short[:slice_len][::-1],
                "ma_l": plot_ma_long[:slice_len][::-1],
                "res": plot_res[:slice_len][::-1],
                "diagH": plot_diagH[:slice_len][::-1],
                "diagL": plot_diagL[:slice_len][::-1],
            }

            if has_signal:
                return {
                    "price": T_close, 
                    "signal": " + ".join(signals), 
                    "vol": vol_tag, 
                    "plot_data": p_data,
                    "signal_types": list(signal_types)  # 傳遞觸發的信號類型組合
                }
                
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
                            "代號": sid, "名稱": name, 
                            "短": int(sn_raw) if pd.notna(sn_raw) else "",
                            "長": int(ln_raw) if pd.notna(ln_raw) else "", 
                            "現價": f"{data['price']:.2f}",
                            "訊號": data['signal'], "量能": data['vol'],
                            "plot_data": data.get("plot_data"),
                            "signal_types": data.get("signal_types", [])
                        })
                except Exception: pass

    except Exception as e: 
        st.error(f"讀取 Google Sheet 失敗: {e}")
    return results

st.title("🐯 金虎南：轉折監控系統 (智慧動態圖表版)")
update_time = time.strftime("%Y-%m-%d %H:%M:%S")
st.caption(f"最後更新時間：{update_time}（快取60秒｜智慧連動：精準繪製觸發線條與排除假日）")

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
    
    df_display = pd.DataFrame(st.session_state["data"]).drop(columns=["plot_data", "signal_types"], errors="ignore")
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    st.subheader("📈 觸發個股 K 線軌道圖 (智慧連動顯示)")
    
    for item in st.session_state["data"]:
        p = item.get("plot_data")
        sig_text = item["訊號"]
        sig_types = item.get("signal_types", [])
        
        if p:
            with st.expander(f"🔍 {item['代號']} {item['名稱']} — 【{sig_text}】", expanded=False):
                fig = go.Figure()
                
                # 1. 台灣標準 K 線 (上漲紅、下跌綠，邊框加粗)
                fig.add_trace(go.Candlestick(
                    x=p["dates"], open=p["opens"], high=p["highs"], low=p["lows"], close=p["closes"],
                    increasing_line_color='#FF3333', increasing_fillcolor='#FF3333',
                    decreasing_line_color='#00A600', decreasing_fillcolor='#00A600',
                    line_width=2.2, name='K線'
                ))
                
                # ⚡ 修正後的繪圖機制：
                # 如果該股票「同時觸發了多個不同類型的指標」，才把對應的指標一起畫在圖上。
                # 如果只有單一類型訊號觸發，就只畫該類型的線條，確保畫面乾淨。
                
                # 均線繪製：訊號內包含 MA
                if "MA" in sig_types:
                    if any(x is not None for x in p["ma_s"]):
                        fig.add_trace(go.Scatter(x=p["dates"], y=p["ma_s"], mode='lines', name='短均線', line=dict(color='#FFA500', width=3.5)))
                    if any(x is not None for x in p["ma_l"]):
                        fig.add_trace(go.Scatter(x=p["dates"], y=p["ma_l"], mode='lines', name='長均線', line=dict(color='#1E90FF', width=3.5)))
                
                # 水平共振線繪製：訊號內包含 HORIZONTAL
                if "HORIZONTAL" in sig_types:
                    fig.add_trace(go.Scatter(x=p["dates"], y=p["res"], mode='lines', name='水平共振', line=dict(color='#BA55D3', width=3.5, dash='dash')))
                
                # 對稱趨勢斜線繪製：訊號內包含 SLOPE
                if "SLOPE" in sig_types:
                    if any(x is not None for x in p["diagH"]):
                        fig.add_trace(go.Scatter(x=p["dates"], y=p["diagH"], mode='lines', name='趨勢壓力', line=dict(color='#B22222', width=3.5, dash='dot')))
                    if any(x is not None for x in p["diagL"]):
                        fig.add_trace(go.Scatter(x=p["dates"], y=p["diagL"], mode='lines', name='趨勢支撐', line=dict(color='#228B22', width=3.5, dash='dot')))
                
                # 圖表佈局優化 & 🔴【核心修改：排除六日假日】
                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    margin=dict(l=10, r=10, t=20, b=10),
                    height=380,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
                )
                
                # 藉由 rangebreaks 移除週六 (sat) 與週日 (mon 之前) 的時間軸空白
                fig.update_xaxes(
                    type='date',
                    rangebreaks=[dict(bounds=["sat", "mon"])]
                )
                
                st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
else: 
    st.info(f"目前 {TARGET_NAME} 監控名單中無觸發訊號。")