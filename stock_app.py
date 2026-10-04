import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ==============================================================================
# 1. 網頁基本設定與樣式
# ==============================================================================
st.set_page_config(layout="wide", page_title="金虎南-純均線監控 (分頁排序版)")

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    table { width: 100% !important; font-size: 18px !important; }
    th { background-color: #f0f2f6 !important; }
    </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# 全域 HTTP Session 與代號副檔名快取 (維持高速請求)
# ==============================================================================
HTTP_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30)
HTTP_SESSION.mount("https://", adapter)
HTTP_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

SYMBOL_CACHE = {}

SHEET_BASE = "https://docs.google.com/spreadsheets/d/1OGsbVKW-h8xwWq_9EO-W172WvdPbfDwjTx533WKaaX4"
MONITOR_SHEETS = [
    {"name": "主頁", "gid": "0"},
    {"name": "分頁1", "gid": "1779050796"},
    {"name": "分頁2", "gid": "462300633"},
]

def get_ma(arr, period, offset=0):
    if period <= 0 or len(arr) < offset + period:
        return None
    sub = arr[offset:offset + period]
    return sum(sub) / period if len(sub) == period else None

# ==============================================================================
# 2. 數據抓取模組
# ==============================================================================
def get_yahoo_history(sid: str, max_n: int):
    if sid in SYMBOL_CACHE:
        suffixes = [SYMBOL_CACHE[sid]]
    else:
        suffixes = [".TW", ".TWO"]

    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d"
            res = HTTP_SESSION.get(url, timeout=4)
            if res.status_code != 200:
                continue
                
            data = res.json()["chart"]["result"][0]
            quote = data["indicators"]["quote"][0]
            timestamps = data.get("timestamp", [])
            
            raw_cls = quote.get("close", [])
            raw_high = quote.get("high", [])
            raw_low = quote.get("low", [])
            raw_op = quote.get("open", [])
            raw_vol = quote.get("volume", [])
            
            t_cls, t_highs, t_lows, t_opens, t_vols, t_dates = [], [], [], [], [], []
            for i in range(len(raw_cls)):
                if raw_cls[i] is not None and raw_high[i] is not None and raw_low[i] is not None:
                    t_cls.append(raw_cls[i])
                    t_highs.append(raw_high[i])
                    t_lows.append(raw_low[i])
                    t_opens.append(raw_op[i] if raw_op[i] is not None else raw_cls[i])
                    t_vols.append(raw_vol[i] if raw_vol[i] is not None else 0)
                    if i < len(timestamps):
                        t_dates.append(time.strftime("%Y-%m-%d", time.localtime(timestamps[i])))
                    else:
                        t_dates.append("")
            
            SYMBOL_CACHE[sid] = sfx

            return {
                "cls": t_cls[::-1],
                "highs": t_highs[::-1],
                "lows": t_lows[::-1],
                "opens": t_opens[::-1],
                "vols": t_vols[::-1],
                "dates": t_dates[::-1]
            }
        except Exception:
            continue
    return None

def fetch_signals(sid, short_n, long_n):
    try:
        valid_ns = [n for n in [short_n, long_n] if pd.notna(n)]
        max_n = max(int(max(valid_ns)) + 60 if valid_ns else 60, 120)
        
        hist = get_yahoo_history(sid, max_n)
        if hist is None:
            return None
            
        cls, highs, lows, opens, vols, dates = (
            hist["cls"], hist["highs"], hist["lows"], 
            hist["opens"], hist["vols"], hist["dates"]
        )
        
        req_len = int(max(valid_ns)) + 30 if valid_ns else 40
        if len(cls) < req_len:
            return None
            
        T_close, T_open, T_high, T_low, T_vol = cls[0], opens[0], highs[0], lows[0], vols[0]
        Y_close = cls[1] if len(cls) > 1 else None
        Y_high = highs[1] if len(highs) > 1 else None
        Y_low = lows[1] if len(lows) > 1 else None
        Y_vol = vols[1] if len(vols) > 1 else None
        B_close = cls[2] if len(cls) > 2 else None
            
        if Y_close is None or B_close is None:
            return None
            
        is_gap_up = T_open > Y_high if Y_high is not None else False
        is_gap_down = T_open < Y_low if Y_low is not None else False
        
        signals = []
        has_signal = False
        ma_list = [("短", short_n), ("長", long_n)]
        valid_closes = cls[1:]
        
        for label, n in ma_list:
            if pd.isna(n):
                continue
            n = int(n)
            if len(cls) < n + 30:
                continue
                
            T_ma = get_ma(cls, n, 0)
            Y_ma = get_ma(valid_closes, n, 0)
            B_ma = get_ma(valid_closes, n, 1)
            
            if T_ma is None or Y_ma is None or B_ma is None:
                continue
                
            trend = "⬆️" if T_ma > Y_ma else "↘"
            label_str = f"{label}({n}MA:{T_ma:.2f}){trend}"
            
            if Y_close <= Y_ma and T_close > T_ma:
                gap_note = "跳空" if is_gap_up else ""
                signals.append(f"🔥{gap_note}突破均線{label_str}")
                has_signal = True
                
            if Y_close >= Y_ma and T_close < T_ma:
                gap_note = "跳空" if is_gap_down else ""
                signals.append(f"📉{gap_note}跌破均線{label_str}")
                has_signal = True
                
            is_yesterday_breakout = (B_close < B_ma and Y_close > Y_ma)
            is_today_away = (T_low > T_ma)
            is_higher_than_yesterday = (T_close > Y_close)
            
            if is_yesterday_breakout and is_today_away and is_higher_than_yesterday:
                gap_note = "跳空" if is_gap_up else ""
                signals.append(f"🔥{gap_note}2日法則(強勢突破){label_str}")
                has_signal = True
                
            y_break = (Y_close < Y_ma and B_close >= B_ma)
            if y_break and T_close > T_ma:
                gap_note = "跳空" if is_gap_up else ""
                if (T_close - T_ma) / T_ma > 0.005:
                    signals.append(f"🔄{gap_note}反2日(假跌破){label_str}[強勢反轉]")
                else:
                    signals.append(f"🔄{gap_note}反2日(假跌破){label_str}")
                has_signal = True
                
        vol_tag = ""
        if Y_vol and T_vol > Y_vol * 1.5:
            vol_tag = "🔴爆量"
        elif Y_vol and T_vol > Y_vol * 1.2:
            vol_tag = "🔴量增"
        elif Y_vol and T_vol > Y_vol:
            vol_tag = "量增"
            
        plot_ma_short, plot_ma_long = [], []
        for i in range(60):
            if i >= len(cls):
                break
            plot_ma_short.append(get_ma(cls, int(short_n), i) if pd.notna(short_n) else None)
            plot_ma_long.append(get_ma(cls, int(long_n), i) if pd.notna(long_n) else None)
            
        slice_len = min(60, len(cls))
        
        p_data = {
            "dates": dates[:slice_len][::-1],
            "vols": vols[:slice_len][::-1],
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
                "plot_data": p_data
            }
    except Exception:
        return None
    return None

@st.cache_data(ttl=300)
def fetch_sheet_csv(gid):
    csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}"
    res = HTTP_SESSION.get(csv_url, timeout=10)
    res.encoding = "utf-8"
    return res.text

def run_scan_for_sheet(sheet_name, gid):
    results = []
    try:
        csv_text = fetch_sheet_csv(gid)
        df = pd.read_csv(io.StringIO(csv_text))
        tasks = []
        for _, row in df.iterrows():
            if df.shape[1] < 4:
                continue
            sid_raw = row.iloc[0]
            if pd.isna(sid_raw):
                continue
            sid = str(sid_raw).strip()
            if sid.replace(".", "").replace("-", "").isdigit():
                sid = str(int(float(sid)))
            sn_raw = pd.to_numeric(row.iloc[2], errors="coerce")
            ln_raw = pd.to_numeric(row.iloc[3], errors="coerce")
            name = row.iloc[1]
            tasks.append((sid, sn_raw, ln_raw, name))
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
            future_to_stock = {
                executor.submit(fetch_signals, t[0], t[1], t[2]): t
                for t in tasks
            }
            for future in concurrent.futures.as_completed(future_to_stock):
                t = future_to_stock[future]
                sid, sn_raw, ln_raw, name = t[0], t[1], t[2], t[3]
                try:
                    data = future.result()
                    if data:
                        results.append({
                            "來源工作表": sheet_name,
                            "代號": sid,
                            "名稱": name,
                            "短": int(sn_raw) if pd.notna(sn_raw) else "",
                            "長": int(ln_raw) if pd.notna(ln_raw) else "",
                            "現價": f"{data['price']:.2f}",
                            "訊號": data["signal"],
                            "量能": data["vol"],
                            "plot_data": data.get("plot_data")
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

# ==============================================================================
# 3. 排序與圖表渲染模組
# ==============================================================================
def get_vol_score(vol_str):
    """【調整說明】量能評分機制：爆量給 3 分、🔴量增給 2 分、量增給 1 分，用於優先排序"""
    if "🔴爆量" in vol_str: return 3
    if "🔴量增" in vol_str: return 2
    if "量增" in vol_str: return 1
    return 0

def render_signal_group(data_list, group_name):
    """【調整說明】渲染特定訊號分類的表格與上下子圖表（已移除日期與成交量文字）"""
    if not data_list:
        st.info(f"目前沒有符合【{group_name}】條件的個股訊號。")
        return
        
    st.markdown(f"**共觸發 {len(data_list)} 檔個股**")
    
    # 顯示 DataFrame 表格
    df_display = pd.DataFrame(data_list).drop(columns=["plot_data"], errors="ignore")
    cols = ["來源工作表"] + [c for c in df_display.columns if c != "來源工作表"]
    st.dataframe(df_display[cols], use_container_width=True, hide_index=True)
    
    # 繪製圖表迴圈
    for idx, item in enumerate(data_list):
        p = item.get("plot_data")
        sig_text = item["訊號"]
        if p:
            with st.expander(f"🔍 [{item['來源工作表']}] {item['代號']} {item['名稱']} — 【{sig_text}】", expanded=False):
                
                # 【調整說明】使用 make_subplots 建立上下兩格：上方 K 線 (75%)、下方成交量柱狀圖 (25%)
                fig = make_subplots(
                    rows=2, cols=1, 
                    shared_xaxes=True, 
                    vertical_spacing=0.03, 
                    row_heights=[0.75, 0.25]
                )
                
                x_indices = list(range(len(p["dates"])))
                
                # ========== 上半部 (Row 1): K線與均線 ==========
                fig.add_trace(go.Candlestick(
                    x=x_indices, open=p["opens"], high=p["highs"], low=p["lows"], close=p["closes"],
                    increasing_line_color="#FF3333", increasing_fillcolor="#FF3333",
                    decreasing_line_color="#00A600", decreasing_fillcolor="#00A600",
                    line_width=1.8, name="K線"
                ), row=1, col=1)
                
                if any(x is not None for x in p["ma_s"]):
                    fig.add_trace(go.Scatter(
                        x=x_indices, y=p["ma_s"], mode="lines",
                        name="短均線", line=dict(color="#FFA500", width=1.8)
                    ), row=1, col=1)
                    
                if any(x is not None for x in p["ma_l"]):
                    fig.add_trace(go.Scatter(
                        x=x_indices, y=p["ma_l"], mode="lines",
                        name="長均線", line=dict(color="#1E90FF", width=1.8)
                    ), row=1, col=1)
                
                # ========== 下半部 (Row 2): 成交量獨立柱狀圖 ==========
                # 依照收盤價大於等於開盤價來決定成交量柱體顏色（紅漲綠跌）
                vol_colors = ['#FF3333' if p["closes"][i] >= p["opens"][i] else '#00A600' for i in range(len(p["closes"]))]
                
                fig.add_trace(go.Bar(
                    x=x_indices, y=p["vols"], 
                    marker_color=vol_colors, 
                    name="成交量"
                ), row=2, col=1)
                
                # ========== 版面與 X 軸隱藏設定 ==========
                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    xaxis2_rangeslider_visible=False,
                    margin=dict(l=10, r=10, t=20, b=10),
                    height=450,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                    showlegend=True
                )
                
                # 【調整說明】完全隱藏上下圖表的 X 軸刻度與日期文字
                fig.update_xaxes(showticklabels=False, showgrid=False, row=1, col=1)
                fig.update_xaxes(showticklabels=False, showgrid=False, row=2, col=1)
                
                # 【調整說明】加上唯一的 key 避免 StreamlitDuplicateElementId 錯誤
                st.plotly_chart(
                    fig, 
                    use_container_width=True, 
                    config={"staticPlot": True}, 
                    key=f"chart_{group_name}_{idx}_{item['代號']}"
                )

# ==============================================================================
# 4. 主介面與執行流程
# ==============================================================================
st.title("🐯 金虎南：轉折監控系統（多標籤分類與量增優先版）")
update_time = time.strftime("%Y-%m-%d %H:%M:%S")
st.caption(f"最後更新時間：{update_time}｜全 Yahoo Finance 即時 API 數據驅動")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 同步所有分頁資料", use_container_width=True):
        st.cache_data.clear()
        st.session_state["all_data"] = run_all_scans()
        st.rerun()
with col2:
    if st.button("🚀 強制刷新即時報價", type="primary", use_container_width=True):
        st.session_state["all_data"] = run_all_scans()
        st.rerun()

if "all_data" not in st.session_state:
    st.session_state["all_data"] = run_all_scans()

# ==============================================================================
# 5. 資料分流與量增排序邏輯
# ==============================================================================
list_breakout = []
list_breakdown = []
list_2day = []
list_anti2day = []

# 將資料分類至對應的清單
for item in st.session_state["all_data"]:
    sig = str(item.get("訊號", ""))
    
    if "突破均線" in sig:
        list_breakout.append(item)
    if "跌破均線" in sig:
        list_breakdown.append(item)
    if "2日法則" in sig and "反2日" not in sig:
        list_2day.append(item)
    if "反2日" in sig:
        list_anti2day.append(item)

# 【調整說明】套用量能評分進行排序，確保有量增的個股排在最前面
list_breakout.sort(key=lambda x: get_vol_score(x.get("量能", "")), reverse=True)
list_breakdown.sort(key=lambda x: get_vol_score(x.get("量能", "")), reverse=True)
list_2day.sort(key=lambda x: get_vol_score(x.get("量能", "")), reverse=True)
list_anti2day.sort(key=lambda x: get_vol_score(x.get("量能", "")), reverse=True)

# ==============================================================================
# 6. 建立四個獨立標籤頁 (Tabs) 顯示
# ==============================================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "🔥 突破均線", 
    "📉 跌破均線", 
    "🔥 2日法則(續強)", 
    "🔄 反2日(假跌破)"
])

with tab1:
    render_signal_group(list_breakout, "突破均線")
with tab2:
    render_signal_group(list_breakdown, "跌破均線")
with tab3:
    render_signal_group(list_2day, "2日法則")
with tab4:
    render_signal_group(list_anti2day, "反2日法則")
