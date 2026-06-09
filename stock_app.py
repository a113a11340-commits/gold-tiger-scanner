cat > /home/workdir/attachments/stock_app.py << 'EOF'
import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import plotly.graph_objects as go

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

def get_ma(arr, period, offset=0):
    sub = arr[offset:offset + period]
    return sum(sub) / period if len(sub) == period else None

@st.cache_data(ttl=60, show_spinner=False)
def fetch_signals(sid, short_n, long_n):
    # 以試算表邏輯為主，抓取較多歷史資料
    max_n = 200
    suffixes = [".TW", ".TWO"]
    
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d"
            res = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200:
                continue

            data = res.json()['chart']['result'][0]
            quote = data['indicators']['quote'][0]
            
            raw_cls = [x for x in quote.get('close', []) if x is not None]
            raw_high = [x for x in quote.get('high', []) if x is not None]
            raw_low = [x for x in quote.get('low', []) if x is not None]
            raw_vol = [x for x in quote.get('volume', []) if x is not None]
            
            cls = raw_cls[::-1]
            highs = raw_high[::-1]
            lows = raw_low[::-1]
            vols = raw_vol[::-1]
            
            if len(cls) < 10:
                continue

            # 富果即時價格
            f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
            f_res = requests.get(f_url, headers={"X-API-KEY": FUGLE_KEY}, timeout=5)
            
            is_fugle_active = False
            if f_res.status_code == 200:
                f_data = f_res.json().get('data', {}).get('quote', {})
                cur_price = f_data.get('price')
                if cur_price and cur_price > 0:
                    is_fugle_active = True
                    T_close = cur_price
                    T_low = f_data.get('low') or cur_price
                    T_high = f_data.get('high') or cur_price
                    Y_close = cls[0]
                    B_close = cls[1] if len(cls) > 1 else Y_close
                else:
                    is_fugle_active = False
            
            if not is_fugle_active:
                T_close = cls[0]
                T_low = lows[0] if lows else T_close
                Y_close = cls[1] if len(cls) > 1 else T_close
                B_close = cls[2] if len(cls) > 2 else Y_close

            signals = []
            has_signal = False
            signal_types = set()
            ma_list = [("短", short_n), ("長", long_n)]

            for label, n in ma_list:
                if pd.isna(n) or n <= 0: continue
                n = int(n)
                if len(cls) < n + 3: continue

                if is_fugle_active:
                    Y_ma = get_ma(cls, n, 0)
                    B_ma = get_ma(cls, n, 1)
                    T_ma = get_ma([T_close] + cls, n, 0)
                else:
                    T_ma = get_ma(cls, n, 0)
                    Y_ma = get_ma(cls, n, 1)
                    B_ma = get_ma(cls, n, 2)

                if None in (T_ma, Y_ma, B_ma): continue

                trend = "⬆️" if T_ma > Y_ma else "↘️"
                label_str = f"{label}({n}MA:{T_ma:.2f}){trend}"

                # 2日法則
                if (B_close < B_ma and Y_close > Y_ma) and (T_low > T_ma) and (T_close > Y_close):
                    signals.append(f"🔥2日法則(強勢突破){label_str}")
                    has_signal = True
                    signal_types.add("MA")

                # 反2日 (假跌破)
                if (Y_close < Y_ma and B_close >= B_ma) and (T_close > T_ma):
                    if (T_close - T_ma) / T_ma > 0.005:
                        signals.append(f"🔄反2日(假跌破){label_str}[強勢反轉]")
                    else:
                        signals.append(f"🔄反2日(假跌破){label_str}")
                    has_signal = True
                    signal_types.add("MA")

                # 跌破 / 突破
                if Y_close >= Y_ma and T_close < T_ma:
                    signals.append(f"跌破{label_str}[停損]")
                    has_signal = True
                elif Y_close < Y_ma and T_close > T_ma and not any("假跌破" in s or "2日法則" in s for s in signals):
                    signals.append(f"突破{label_str}[進場1/2]")
                    has_signal = True

            # 量增判斷
            vol_tag = ""
            if len(vols) >= 2 and vols[0] > vols[1] * 1.25:
                vol_tag = "🔴量增"

            # 繪圖資料
            plot_ma_short, plot_ma_long = [], []
            for i in range(60):
                if i >= len(cls): break
                plot_ma_short.append(get_ma([T_close] + cls if is_fugle_active else cls, int(short_n), i) if pd.notna(short_n) else None)
                plot_ma_long.append(get_ma([T_close] + cls if is_fugle_active else cls, int(long_n), i) if pd.notna(long_n) else None)

            slice_len = min(60, len(cls) + (1 if is_fugle_active else 0))
            dates = [time.strftime('%Y-%m-%d')] + ["" for _ in range(len(cls)-1)] if is_fugle_active else ["" for _ in cls]
            
            p_data = {
                "dates": dates[:slice_len][::-1],
                "opens": [0]*slice_len,
                "highs": highs[:slice_len][::-1] if highs else [0]*slice_len,
                "lows": lows[:slice_len][::-1] if lows else [0]*slice_len,
                "closes": ([T_close] + cls)[:slice_len][::-1] if is_fugle_active else cls[:slice_len][::-1],
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
        except Exception:
            continue
    return None

# 後續函數維持不變（僅調整表格顯示）
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
            future_to_stock = {executor.submit(fetch_signals, t[0], t[1], t[2]): t for t in tasks}
            
            for future in concurrent.futures.as_completed(future_to_stock):
                t = future_to_stock[future]
                try:
                    data = future.result()
                    if data:
                        results.append({
                            "來源工作表": sheet_name, 
                            "代號": t[0], 
                            "名稱": t[3],
                            "現價": f"{data['price']:.2f}", 
                            "訊號": data['signal'], 
                            "量能": data['vol'],
                            "plot_data": data.get("plot_data"), 
                            "signal_types": data.get("signal_types", [])
                        })
                except Exception:
                    pass
    except Exception as e:
        st.error(f"讀取分頁【{sheet_name}】失敗: {e}")
    return results

def run_all_scans():
    all_results = []
    for sheet in MONITOR_SHEETS:
        all_results.extend(run_scan_for_sheet(sheet["name"], sheet["gid"]))
    return all_results

# UI 部分
st.title("🐯 金虎南：轉折監控系統 (純均線與2日法則版)")
update_time = time.strftime("%Y-%m-%d %H:%M:%S")
st.caption(f"最後更新時間：{update_time}（已盡量與試算表邏輯對齊）")

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

if "all_data" not in st.session_state:
    st.session_state["all_data"] = run_all_scans()

if st.session_state["all_data"]:
    st.subheader(f"📊 綜合監控結果 (共觸發 {len(st.session_state['all_data'])} 檔個股)")
    
    df_display = pd.DataFrame(st.session_state["all_data"]).drop(
        columns=["plot_data", "signal_types", "短", "長"], errors="ignore"
    )
    cols = ['來源工作表'] + [col for col in df_display.columns if col != '來源工作表']
    st.table(df_display[cols])   # 完全展開顯示
    
    # 圖表部分維持原樣
    st.markdown("---")
    st.subheader("📈 觸發個股 K 線軌道圖")
    for item in st.session_state["all_data"]:
        p = item.get("plot_data")
        if p:
            with st.expander(f"🔍 [{item['來源工作表']}] {item['代號']} {item.get('名稱','')} — 【{item['訊號']}】", expanded=False):
                fig = go.Figure()
                fig.add_trace(go.Candlestick(
                    x=p["dates"], open=p.get("opens",[]), high=p["highs"], low=p["lows"], close=p["closes"],
                    increasing_line_color='#FF3333', increasing_fillcolor='#FF3333',
                    decreasing_line_color='#00A600', decreasing_fillcolor='#00A600',
                    line_width=1.8, name='K線'
                ))
                if "MA" in item.get("signal_types", []):
                    if any(x is not None for x in p["ma_s"]):
                        fig.add_trace(go.Scatter(x=p["dates"], y=p["ma_s"], mode='lines', name='短均線', line=dict(color='#FFA500', width=1.8)))
                    if any(x is not None for x in p["ma_l"]):
                        fig.add_trace(go.Scatter(x=p["dates"], y=p["ma_l"], mode='lines', name='長均線', line=dict(color='#1E90FF', width=1.8)))
                
                fig.update_layout(xaxis_rangeslider_visible=False, height=380, margin=dict(l=10,r=10,t=20,b=10))
                fig.update_xaxes(type='category', tickangle=-45)
                st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
else:
    st.info("目前無觸發訊號。")
EOF
