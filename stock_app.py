import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import plotly.graph_objects as go
from datetime import date

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-純均線監控")

# --- 富果 API 設定 ---
FUGLE_KEY = "Mzk5YWVkYmMtYzVhNi00OWRhLWI5NWUtNGNjYzI3NjNjZDYyIDg0NDdhYjVmLThlMTktNDE3MC1hZDZmLThkMDcwNThiYzM1Mw=="

# --- 網頁樣式調整 ---
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    table { width: 100% !important; font-size: 18px !important; }
    th { background-color: #f0f2f6 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- Google Sheet 多分頁設定 ---
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1OGsbVKW-h8xwWq_9EO-W172WvdPbfDwjTx533WKaaX4"
MONITOR_SHEETS = [
    {"name": "主頁", "gid": "0"},
    {"name": "短均", "gid": "353487646"},
    {"name": "中均", "gid": "1032414416"},
    {"name": "長均", "gid": "1361333675"},
]

# --- 工具函數：計算移動平均線 (MA) ---
def get_ma(arr, period, offset=0):
    """
    計算指定週期的移動平均線
    arr: 價格陣列
    period: 均線週期 (例如 5, 20)
    offset: 位移格數 (0代表當前，1代表上一根)
    """
    if period <= 0 or len(arr) < offset + period:
        return None
    sub = arr[offset:offset + period]
    return sum(sub) / period if len(sub) == period else None

# --- 工具函數：Yahoo 歷史資料快取 (同一天內只向 Yahoo 發送一次請求) ---
@st.cache_data(ttl=86400, show_spinner=False)  # 快取 24 小時
def get_yahoo_history(sid: str, max_n: int, cache_date: str):
    """
    抓取 Yahoo 歷史日線資料，並用日期當 cache key。
    優先嘗試 .TW (上市)，若失敗則嘗試 .TWO (上櫃)。
    """
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d"
            res = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
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
                        
            # 回傳反轉後的陣列（讓最新資料排在最前面 index 0）
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

# --- 核心邏輯：抓取個股資料並計算技術訊號 ---
def fetch_signals(sid, short_n, long_n):
    try:
        valid_ns = [n for n in [short_n, long_n] if pd.notna(n)]
        max_n = max(int(max(valid_ns)) + 60 if valid_ns else 60, 120)
        
        # 1. 取得 Yahoo 歷史資料
        today_str = date.today().isoformat()
        hist = get_yahoo_history(sid, max_n, today_str)
        if hist is None:
            return None
            
        cls = hist["cls"][:]
        highs = hist["highs"][:]
        lows = hist["lows"][:]
        opens = hist["opens"][:]
        vols = hist["vols"][:]
        dates = hist["dates"][:]
        
        yahoo_has_today = bool(dates) and dates[0] == today_str
        req_len = int(max(valid_ns)) + 30 if valid_ns else 40
        
        if len(cls) < req_len:
            return None
            
        # 2. 獲取富果 (Fugle) API 即時價格
        f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
        f_res = requests.get(f_url, headers={"X-API-KEY": FUGLE_KEY}, timeout=5)
        
        is_fugle_active = False
        T_close = T_open = T_low = T_high = T_vol = None
        Y_close = Y_high = Y_low = Y_vol = None
        B_close = None
        
        if f_res.status_code == 200:
            f_data = f_res.json().get("data", {}).get("quote", {})
            cur_price = f_data.get("price", 0) or f_data.get("lastPrice", 0)
            if cur_price and cur_price > 0:
                is_fugle_active = True
                T_close = cur_price
                T_open = f_data.get("open", cur_price) if f_data.get("open", 0) > 0 else cur_price
                T_low = f_data.get("low", cur_price) if f_data.get("low", 0) > 0 else cur_price
                T_high = f_data.get("high", cur_price) if f_data.get("high", 0) > 0 else cur_price
                T_vol = f_data.get("total", {}).get("tradeVolume", 0) or (vols[0] if vols else 0)
                
        # 3. 整合即時價與歷史 K 線
        if is_fugle_active:
            if yahoo_has_today:
                # 若 Yahoo 已經更新今天，直接覆蓋第一根
                cls[0] = T_close
                highs[0] = T_high
                lows[0] = T_low
                opens[0] = T_open
                vols[0] = T_vol
                
                Y_close = cls[1] if len(cls) > 1 else None
                Y_high = highs[1] if len(highs) > 1 else None
                Y_low = lows[1] if len(lows) > 1 else None
                Y_vol = vols[1] if len(vols) > 1 else None
                B_close = cls[2] if len(cls) > 2 else None
            else:
                # 若 Yahoo 尚未更新今天，將即時價插入到最前面
                Y_close = cls[0]
                Y_high = highs[0]
                Y_low = lows[0]
                Y_vol = vols[0]
                B_close = cls[1] if len(cls) > 1 else None
                
                cls = [T_close] + cls
                highs = [T_high] + highs
                lows = [T_low] + lows
                opens = [T_open] + opens
                vols = [T_vol] + vols
                dates = [today_str] + dates
        else:
            # 無富果即時價時，完全使用 Yahoo 資料
            T_close = cls[0]
            T_open = opens[0]
            T_low = lows[0]
            T_high = highs[0]
            T_vol = vols[0]
            
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
        
        # 4. 建立不含當日即時價的歷史序列 (對齊 GAS 的 validCloses.slice(1))
        valid_closes = cls[1:]
        
        for label, n in ma_list:
            if pd.isna(n):
                continue
            n = int(n)
            if len(cls) < n + 30:
                continue
                
            # 計算均線：T_ma (含當日), Y_ma 與 B_ma (從歷史序列計算)
            T_ma = get_ma(cls, n, 0)
            Y_ma = get_ma(valid_closes, n, 0)
            B_ma = get_ma(valid_closes, n, 1)
            
            if T_ma is None or Y_ma is None or B_ma is None:
                continue
                
            trend = "⬆️" if T_ma > Y_ma else "↘️"
            label_str = f"{label}({n}MA:{T_ma:.2f}){trend}"
            
            # --- 訊號判斷 1：簡單突破均線 ---
            if Y_close <= Y_ma and T_close > T_ma:
                gap_note = "跳空" if is_gap_up else ""
                signals.append(f"🔥{gap_note}突破均線{label_str}")
                has_signal = True
                
            # --- 訊號判斷 2：簡單跌破均線 ---
            if Y_close >= Y_ma and T_close < T_ma:
                gap_note = "跳空" if is_gap_down else ""
                signals.append(f"📉{gap_note}跌破均線{label_str}")
                has_signal = True
                
            # --- 訊號判斷 3：2日法則 ---
            is_yesterday_breakout = (B_close < B_ma and Y_close > Y_ma)
            is_today_away = (T_low > T_ma)
            is_higher_than_yesterday = (T_close > Y_close)
            
            if is_yesterday_breakout and is_today_away and is_higher_than_yesterday:
                gap_note = "跳空" if is_gap_up else ""
                signals.append(f"🔥{gap_note}2日法則(強勢突破){label_str}")
                has_signal = True
                
            # --- 訊號判斷 4：反2日法則 (假跌破) ---
            y_break = (Y_close < Y_ma and B_close >= B_ma)
            if y_break and T_close > T_ma:
                gap_note = "跳空" if is_gap_up else ""
                if (T_close - T_ma) / T_ma > 0.005:
                    signals.append(f"🔄{gap_note}反2日(假跌破){label_str}[強勢反轉]")
                else:
                    signals.append(f"🔄{gap_note}反2日(假跌破){label_str}")
                has_signal = True
                
        # 5. 量能標籤計算
        vol_tag = ""
        if Y_vol and T_vol > Y_vol * 1.5:
            vol_tag = "🔴爆量"
        elif Y_vol and T_vol > Y_vol * 1.2:
            vol_tag = "🔴量增"
        elif Y_vol and T_vol > Y_vol:
            vol_tag = "量增"
            
        # 6. 整理近 60 根 K 線與均線繪圖資料
        plot_ma_short, plot_ma_long = [], []
        for i in range(60):
            if i >= len(cls):
                break
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
                "plot_data": p_data
            }
    except Exception:
        return None
    return None

# --- 讀取 Google Sheet 單一分頁並進行多執行緒掃描 ---
def run_scan_for_sheet(sheet_name, gid):
    results = []
    csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}&cb={int(time.time())}"
    try:
        res = requests.get(csv_url, timeout=10)
        res.encoding = "utf-8"
        df = pd.read_csv(io.StringIO(res.text))
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
            
        # 使用執行緒池加速平行運算
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
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

# --- 執行所有監控分頁的掃描 ---
def run_all_scans():
    all_results = []
    for sheet in MONITOR_SHEETS:
        all_results.extend(run_scan_for_sheet(sheet["name"], sheet["gid"]))
    return all_results

# ================= 主畫面 UI =================
st.title("🐯 金虎南：轉折監控系統（純均線 + 2日法則）")
update_time = time.strftime("%Y-%m-%d %H:%M:%S")
st.caption(f"最後更新時間：{update_time}｜主頁 + 4 個分頁連動｜Yahoo 歷史資料已啟用每日快取")

# 功能按鈕
col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 同步所有分頁資料", use_container_width=True):
        st.session_state["all_data"] = run_all_scans()
        st.rerun()
with col2:
    if st.button("🚀 強制刷新即時報價", type="primary", use_container_width=True):
        st.session_state["all_data"] = run_all_scans()
        st.rerun()

if "all_data" not in st.session_state:
    st.session_state["all_data"] = run_all_scans()

# ================= 過濾規則設定 =================
# 1. 含有「跌破」相關訊號一律不顯示
# 2. 必須符合「2日法則/反2日」或「具備量能增加」才顯示
filtered_data = []
for item in st.session_state["all_data"]:
    sig = str(item.get("訊號", ""))
    vol = str(item.get("量能", ""))
    is_two_day = "2日法則" in sig or "反2日" in sig
    is_breakdown = "跌破" in sig
    has_volume = vol in ["量增", "🔴量增", "🔴爆量"]
    
    if is_breakdown:
        continue
    if is_two_day or has_volume:
        filtered_data.append(item)

# ================= 結果呈現與繪圖 =================
if filtered_data:
    st.subheader(f"📊 綜合監控結果 (共觸發 {len(filtered_data)} 檔個股)")
    df_display = pd.DataFrame(filtered_data).drop(columns=["plot_data"], errors="ignore")
    cols = ["來源工作表"] + [c for c in df_display.columns if c != "來源工作表"]
    st.dataframe(df_display[cols], use_container_width=True, hide_index=True)
    st.markdown("---")
    
    st.subheader("📈 觸發個股 K 線軌道圖（含均線）")
    for item in filtered_data:
        p = item.get("plot_data")
        sig_text = item["訊號"]
        if p:
            with st.expander(
                f"🔍 [{item['來源工作表']}] {item['代號']} {item['名稱']} — 【{sig_text}】",
                expanded=False
            ):
                fig = go.Figure()
                # 繪製 K 線圖
                fig.add_trace(go.Candlestick(
                    x=p["dates"], open=p["opens"], high=p["highs"], low=p["lows"], close=p["closes"],
                    increasing_line_color="#FF3333", increasing_fillcolor="#FF3333",
                    decreasing_line_color="#00A600", decreasing_fillcolor="#00A600",
                    line_width=1.8, name="K線"
                ))
                # 繪製短均線
                if any(x is not None for x in p["ma_s"]):
                    fig.add_trace(go.Scatter(
                        x=p["dates"], y=p["ma_s"], mode="lines",
                        name="短均線", line=dict(color="#FFA500", width=1.8)
                    ))
                # 繪製長均線
                if any(x is not None for x in p["ma_l"]):
                    fig.add_trace(go.Scatter(
                        x=p["dates"], y=p["ma_l"], mode="lines",
                        name="長均線", line=dict(color="#1E90FF", width=1.8)
                    ))
                
                # 圖表排版設定
                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    margin=dict(l=10, r=10, t=20, b=10),
                    height=380,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
                )
                fig.update_xaxes(type="category", tickangle=-45, nticks=15)
                
                # 渲染 Plotly 圖表（帶有唯一 key 避免重複衝突）
                st.plotly_chart(
                    fig,
                    use_container_width=True,
                    config={"staticPlot": True},
                    key=f"chart_{item['來源工作表']}_{item['代號']}"
                )
else:
    st.info("目前所有監控分頁中皆無符合條件的訊號。")
