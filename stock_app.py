import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import plotly.graph_objects as go

st.set_page_config(layout="wide", page_title="金虎南-純均線監控")

FUGLE_KEY = "Mzk5YWVkYmMtYzVhNi00OWRhLWI5NWUtNGNjYzI3NjNjZDYyIDg0NDdhYjVmLThlMTktNDE3MC1hZDZmLThkMDcwNThiYzM1Mw=="

# 加大字體
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    body, p, div, span, h1, h2, h3, h4 { font-size: 1.15rem !important; }
    table { width: 100% !important; font-size: 24px !important; }
    th, td { font-size: 24px !important; padding: 14px 8px !important; line-height: 1.45 !important; }
    th { background-color: #f0f2f6 !important; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

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
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=200d&interval=1d"
            res = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if res.status_code != 200: continue

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

            if len(cls) < 20: continue

            # 富果即時價
            f_res = requests.get(f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}", 
                               headers={"X-API-KEY": FUGLE_KEY}, timeout=5)
            
            is_fugle_active = False
            T_close = cls[0]
            T_low = lows[0] if lows else T_close
            Y_close = cls[1] if len(cls) > 1 else T_close
            B_close = cls[2] if len(cls) > 2 else Y_close

            if f_res.status_code == 200:
                try:
                    f_data = f_res.json().get('data', {}).get('quote', {})
                    cur = f_data.get('price')
                    if cur and cur > 0:
                        is_fugle_active = True
                        T_close = cur
                        T_low = f_data.get('low') or T_close
                        Y_close = cls[0]
                        B_close = cls[1] if len(cls) > 1 else Y_close
                except:
                    pass

            signals = []
            has_signal = False
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

                if (B_close < B_ma and Y_close > Y_ma) and (T_low > T_ma) and (T_close > Y_close):
                    signals.append(f"🔥2日法則(強勢突破){label_str}")
                    has_signal = True
                if (Y_close < Y_ma and B_close >= B_ma) and (T_close > T_ma):
                    signals.append(f"🔄反2日(假跌破){label_str}")
                    has_signal = True
                if Y_close >= Y_ma and T_close < T_ma:
                    signals.append(f"跌破{label_str}[停損]")
                    has_signal = True
                elif Y_close < Y_ma and T_close > T_ma:
                    signals.append(f"突破{label_str}[進場1/2]")
                    has_signal = True

            vol_tag = "🔴量增" if len(vols) >= 2 and vols[0] > vols[1] * 1.25 else ""

            # K線圖資料 - 使用簡單序號，避免顯示錯誤
            slice_len = min(60, len(cls) + (1 if is_fugle_active else 0))
            dummy_dates = list(range(slice_len))

            p_data = {
                "dates": dummy_dates,
                "opens": [0] * slice_len,
                "highs": highs[:slice_len][::-1] if highs else [T_close] * slice_len,
                "lows": lows[:slice_len][::-1] if lows else [T_close * 0.95] * slice_len,
                "closes": ([T_close] + cls)[:slice_len][::-1] if is_fugle_active else cls[:slice_len][::-1],
                "ma_s": [get_ma([T_close] + cls if is_fugle_active else cls, int(short_n), i) if pd.notna(short_n) else None for i in range(slice_len)],
                "ma_l": [get_ma([T_close] + cls if is_fugle_active else cls, int(long_n), i) if pd.notna(long_n) else None for i in range(slice_len)]
            }

            if has_signal:
                return {
                    "price": T_close,
                    "signal": " + ".join(signals),
                    "vol": vol_tag,
                    "plot_data": p_data
                }
        except:
            continue
    return None

# run_scan_for_sheet 和 run_all_scans（保持不變）
def run_scan_for_sheet(sheet_name, gid):
    results = []
    csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}&cb={int(time.time())}"
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
                            "plot_data": data.get("plot_data")
                        })
                except:
                    pass
    except Exception as e:
        st.error(f"讀取分頁失敗: {e}")
    return results

def run_all_scans():
    all_results = []
    for sheet in MONITOR_SHEETS:
        all_results.extend(run_scan_for_sheet(sheet["name"], sheet["gid"]))
    return all_results

# 主畫面
st.title("🐯 金虎南：轉折監控系統 (純均線與2日法則版)")
st.caption("最後更新時間：" + time.strftime("%Y-%m-%d %H:%M:%S"))

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
    
    df_display = pd.DataFrame(st.session_state["all_data"]).drop(columns=["plot_data"], errors="ignore")
    
    # 突破紅色、跌破綠色
    def color_signal(val):
        if isinstance(val, str):
            if "突破" in val:
                return f'<span style="color:red; font-weight:bold;">{val}</span>'
            elif "跌破" in val:
                return f'<span style="color:green; font-weight:bold;">{val}</span>'
        return val
    
    df_display['訊號'] = df_display['訊號'].apply(color_signal)
    st.html(df_display.to_html(escape=False, index=False))
    
    st.markdown("---")
    st.subheader("📈 觸發個股 K 線軌道圖")
    
    for item in st.session_state["all_data"]:
        p = item.get("plot_data")
        if p and len(p["closes"]) > 5:
            with st.expander(f"🔍 [{item['來源工作表']}] {item['代號']} {item.get('名稱','')} — 【{item['訊號']}】", expanded=False):
                fig = go.Figure()
                fig.add_trace(go.Candlestick(
                    x=p["dates"], 
                    open=p["opens"], 
                    high=p["highs"], 
                    low=p["lows"], 
                    close=p["closes"],
                    increasing_line_color='#FF3333', 
                    increasing_fillcolor='#FF3333',
                    decreasing_line_color='#00A600', 
                    decreasing_fillcolor='#00A600',
                    line_width=1.8, 
                    name='K線'
                ))
                fig.add_trace(go.Scatter(x=p["dates"], y=p["ma_s"], mode='lines', name='短均線', line=dict(color='#FFA500', width=2)))
                fig.add_trace(go.Scatter(x=p["dates"], y=p["ma_l"], mode='lines', name='長均線', line=dict(color='#1E90FF', width=2)))
                
                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    margin=dict(l=10, r=10, t=30, b=10),
                    height=450,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
                )
                fig.update_xaxes(showticklabels=False)   # 不顯示日期
                st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
else:
    st.info("目前所有監控分頁中皆無觸發訊號。")
