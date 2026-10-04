import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import plotly.graph_objects as go
from datetime import date

# ==============================================================================
# 1. 網頁基本設定與 CSS 樣式調整
# ==============================================================================
# 【說明】設定 Streamlit 頁面標題與佈局（全寬模式）
st.set_page_config(
    layout="wide", 
    page_title="金虎南-純均線監控"
)

# 【說明】利用 CSS 注入自訂樣式：減少上方留白、設定表格全寬與字體大小
st.markdown("""
    <style>
    /* 【調整說明】padding-top 可以調整網頁最頂端的留白高度 */
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    /* 【調整說明】字體大小 (font-size) 可依個人需求調整 */
    table { width: 100% !important; font-size: 18px !important; }
    th { background-color: #f0f2f6 !important; }
    </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# 2. Google Sheet 數據源設定
# ==============================================================================
# 【可調整位置】替換成您自己的 Google Sheet 共用網址（需開啟「知道連結的人皆可存取」）
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1OGsbVKW-h8xwWq_9EO-W172WvdPbfDwjTx533WKaaX4"

# 【可調整位置】工作表分頁設定：gid 為網址最後面的 gid=xxxx 數字
# 若新增分頁，只需依照格式新增 {"name": "分頁名稱", "gid": "分頁GID"} 即可
MONITOR_SHEETS = [
    {"name": "主頁", "gid": "0"},
    {"name": "分頁1", "gid": "1779050796"},
    {"name": "分頁2", "gid": "462300633"},
]

# ==============================================================================
# 3. 技術指標工具函數：計算移動平均線 (MA)
# ==============================================================================
def get_ma(arr, period, offset=0):
    """
    【說明】計算移動平均線 (Moving Average)
    :param arr: 價格列表（資料排序：index 0 為最新日期，index 1 為前一日，以此類推）
    :param period: 均線週期（例如：5MA, 20MA, 60MA）
    :param offset: 時間位移格數 (0代表當前，1代表前一日，2代表前二日)
    :return: 均線數值 (float) 或 None
    """
    if period <= 0 or len(arr) < offset + period:
        return None
    # 切片取得指定區間的價格
    sub = arr[offset:offset + period]
    # 計算平均值
    return sum(sub) / period if len(sub) == period else None

# ==============================================================================
# 4. 即時與歷史資料抓取 (Yahoo Finance API)
# ==============================================================================
def get_yahoo_history(sid: str, max_n: int):
    """
    【說明】向 Yahoo Finance API 抓取指定股票的歷史與即時日線數據
    :param sid: 股票代號 (例如 "2330")
    :param max_n: 預備抓取的歷史天數
    :return: 包含開高低收量與日期的字典，排序已轉置為 [0] = 最新一天
    """
    # 台股分為上市 (.TW) 與上櫃 (.TWO)，這裡會自動嘗試兩種字尾
    suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d"
            # 加上 User-Agent 避免被 Yahoo 判定為爬蟲擋封包
            res = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code != 200:
                continue
                
            data = res.json()["chart"]["result"][0]
            quote = data["indicators"]["quote"][0]
            timestamps = data.get("timestamp", [])
            
            # 提取原始 K 線數據
            raw_cls = quote.get("close", [])
            raw_high = quote.get("high", [])
            raw_low = quote.get("low", [])
            raw_op = quote.get("open", [])
            raw_vol = quote.get("volume", [])
            
            t_cls, t_highs, t_lows, t_opens, t_vols, t_dates = [], [], [], [], [], []
            for i in range(len(raw_cls)):
                # 過濾掉無效的空資料 (None)
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
                        
            # 【關鍵說明】將陣列反轉 [::-1]，讓 index 0 永遠代表最新一天的資料
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

# ==============================================================================
# 5. 核心邏輯：計算轉折與均線突破/跌破訊號
# ==============================================================================
def fetch_signals(sid, short_n, long_n):
    """
    【說明】判斷個股是否符合突破、跌破、2日法則、反2日法則等技術訊號
    """
    try:
        # 計算需要的歷史資料天數
        valid_ns = [n for n in [short_n, long_n] if pd.notna(n)]
        # 【可調整】60 代表除了 MA 以外多抓 60 天預備區間，最小抓 120 天
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
            
        # ----------------------------------------------------------------------
        # 定義時間點資料：
        # T (Today/Current)   : 當日前價/量 (index 0)
        # Y (Yesterday)       : 昨日價/量 (index 1)
        # B (Before-Yesterday): 前日價/量 (index 2)
        # ----------------------------------------------------------------------
        T_close, T_open, T_high, T_low, T_vol = cls[0], opens[0], highs[0], lows[0], vols[0]
        Y_close = cls[1] if len(cls) > 1 else None
        Y_high = highs[1] if len(highs) > 1 else None
        Y_low = lows[1] if len(lows) > 1 else None
        Y_vol = vols[1] if len(vols) > 1 else None
        B_close = cls[2] if len(cls) > 2 else None
            
        if Y_close is None or B_close is None:
            return None
            
        # 判斷今日開盤是否發生跳空缺口
        is_gap_up = T_open > Y_high if Y_high is not None else False
        is_gap_down = T_open < Y_low if Y_low is not None else False
        
        signals = []
        has_signal = False
        ma_list = [("短", short_n), ("長", long_n)]
        
        valid_closes = cls[1:]  # 排除當日價位的過去收盤價陣列
        
        for label, n in ma_list:
            if pd.isna(n):
                continue
            n = int(n)
            if len(cls) < n + 30:
                continue
                
            # 計算當日(T_ma)、昨日(Y_ma)與前日(B_ma)的移動平均線
            T_ma = get_ma(cls, n, 0)
            Y_ma = get_ma(valid_closes, n, 0)
            B_ma = get_ma(valid_closes, n, 1)
            
            if T_ma is None or Y_ma is None or B_ma is None:
                continue
                
            trend = "⬆️" if T_ma > Y_ma else "↘"
            label_str = f"{label}({n}MA:{T_ma:.2f}){trend}"
            
            # --- 【訊號 1：標準突破均線】昨日在均線下，今日收盤站上均線 ---
            if Y_close <= Y_ma and T_close > T_ma:
                gap_note = "跳空" if is_gap_up else ""
                signals.append(f"🔥{gap_note}突破均線{label_str}")
                has_signal = True
                
            # --- 【訊號 2：標準跌破均線】昨日在均線上，今日收盤跌破均線 ---
            if Y_close >= Y_ma and T_close < T_ma:
                gap_note = "跳空" if is_gap_down else ""
                signals.append(f"📉{gap_note}跌破均線{label_str}")
                has_signal = True
                
            # --- 【訊號 3：2日法則 (強勢突破)】昨日已突破，今日最低價仍高於均線且持續創新高 ---
            is_yesterday_breakout = (B_close < B_ma and Y_close > Y_ma)
            is_today_away = (T_low > T_ma)
            is_higher_than_yesterday = (T_close > Y_close)
            
            if is_yesterday_breakout and is_today_away and is_higher_than_yesterday:
                gap_note = "跳空" if is_gap_up else ""
                signals.append(f"🔥{gap_note}2日法則(強勢突破){label_str}")
                has_signal = True
                
            # --- 【訊號 4：反2日法則 (假跌破強勢洗盤)】昨日跌破均線，今日快速拉回站上均線 ---
            y_break = (Y_close < Y_ma and B_close >= B_ma)
            if y_break and T_close > T_ma:
                gap_note = "跳空" if is_gap_up else ""
                # 【可調整】0.005 代表高出均線 0.5% 以上視為強勢反轉
                if (T_close - T_ma) / T_ma > 0.005:
                    signals.append(f"🔄{gap_note}反2日(假跌破){label_str}[強勢反轉]")
                else:
                    signals.append(f"🔄{gap_note}反2日(假跌破){label_str}")
                has_signal = True
                
        # ----------------------------------------------------------------------
        # 【量能變化標籤判斷】
        # 【可調整】可依個人偏好調整量增倍數閾值（如 1.5 倍、1.2 倍）
        # ----------------------------------------------------------------------
        vol_tag = ""
        if Y_vol and T_vol > Y_vol * 1.5:
            vol_tag = "🔴爆量"     # 今日成交量 > 昨日的 1.5 倍
        elif Y_vol and T_vol > Y_vol * 1.2:
            vol_tag = "🔴量增"     # 今日成交量 > 昨日的 1.2 倍
        elif Y_vol and T_vol > Y_vol:
            vol_tag = "量增"       # 今日成交量 > 昨日
            
        # ----------------------------------------------------------------------
        # 【繪圖數據整理】預備近 60 根 K 線的歷史數據
        # ----------------------------------------------------------------------
        plot_ma_short, plot_ma_long = [], []
        for i in range(60):
            if i >= len(cls):
                break
            plot_ma_short.append(get_ma(cls, int(short_n), i) if pd.notna(short_n) else None)
            plot_ma_long.append(get_ma(cls, int(long_n), i) if pd.notna(long_n) else None)
            
        slice_len = min(60, len(cls))
        # 轉回正向時間軸（[0]為最舊，[-1]為最新，符合 K 線繪圖慣例）
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

# ==============================================================================
# 6. 多執行緒多頁面掃描 (ThreadPoolExecutor)
# ==============================================================================
def run_scan_for_sheet(sheet_name, gid):
    """
    【說明】下載單一 Google Sheet 分頁，並利用多執行緒進行股票技術面平行掃描
    """
    results = []
    # 利用時間戳記 cb 防範 Google Sheet 快取未更新問題
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
            # 清理股票代號格式 (例如將 "2330.0" 轉成 "2330")
            if sid.replace(".", "").replace("-", "").isdigit():
                sid = str(int(float(sid)))
            sn_raw = pd.to_numeric(row.iloc[2], errors="coerce")
            ln_raw = pd.to_numeric(row.iloc[3], errors="coerce")
            name = row.iloc[1]
            tasks.append((sid, sn_raw, ln_raw, name))
            
        # 【可調整】max_workers 控制同時抓取 Yahoo 資料的線程數量（建議 5~15）
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

def run_all_scans():
    """【說明】循環所有設定的分頁並合併掃描結果"""
    all_results = []
    for sheet in MONITOR_SHEETS:
        all_results.extend(run_scan_for_sheet(sheet["name"], sheet["gid"]))
    return all_results

# ==============================================================================
# 7. Streamlit 主介面渲染與對話互動
# ==============================================================================
st.title("🐯 金虎南：轉折監控系統（純均線 + 2日法則）")
update_time = time.strftime("%Y-%m-%d %H:%M:%S")
st.caption(f"最後更新時間：{update_time}｜全 Yahoo Finance 即時 API 數據驅動")

# 按鈕區塊
col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 同步所有分頁資料", use_container_width=True):
        st.session_state["all_data"] = run_all_scans()
        st.rerun()
with col2:
    if st.button("🚀 強制刷新即時報價", type="primary", use_container_width=True):
        st.session_state["all_data"] = run_all_scans()
        st.rerun()

# 首次載入時自動執行一次全區掃描
if "all_data" not in st.session_state:
    st.session_state["all_data"] = run_all_scans()

# ==============================================================================
# 8. 訊號二次過濾規則設定
# ==============================================================================
filtered_data = []
for item in st.session_state["all_data"]:
    sig = str(item.get("訊號", ""))
    vol = str(item.get("量能", ""))
    
    is_two_day = "2日法則" in sig or "反2日" in sig
    is_breakdown = "跌破" in sig
    has_volume = vol in ["量增", "🔴量增", "🔴爆量"]
    
    # 【可調整】預設過濾條件：
    # 1. 忽略所有純單日「跌破」訊號
    if is_breakdown:
        continue
    # 2. 保留具備「2日法則/反2日」或「有放量」的強勢標的
    if is_two_day or has_volume:
        filtered_data.append(item)

# ==============================================================================
# 9. 結果表格呈現與 Plotly 互動圖表繪製
# ==============================================================================
if filtered_data:
    st.subheader(f"📊 綜合監控結果 (共觸發 {len(filtered_data)} 檔個股)")
    
    # 隱藏繪圖專用的內部數據欄位再做表格顯示
    df_display = pd.DataFrame(filtered_data).drop(columns=["plot_data"], errors="ignore")
    cols = ["來源工作表"] + [c for c in df_display.columns if c != "來源工作表"]
    st.dataframe(df_display[cols], use_container_width=True, hide_index=True)
    st.markdown("---")
    
    # K 線圖摺疊選單
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
                
                # 【繪圖設定】台灣股市慣例：漲為紅 (Red #FF3333)、跌為綠 (Green #00A600)
                fig.add_trace(go.Candlestick(
                    x=p["dates"], 
                    open=p["opens"], 
                    high=p["highs"], 
                    low=p["lows"], 
                    close=p["closes"],
                    increasing_line_color="#FF3333", 
                    increasing_fillcolor="#FF3333",
                    decreasing_line_color="#00A600", 
                    decreasing_fillcolor="#00A600",
                    line_width=1.8, 
                    name="K線"
                ))
                
                # 繪製短均線 (橘色 #FFA500)
                if any(x is not None for x in p["ma_s"]):
                    fig.add_trace(go.Scatter(
                        x=p["dates"], y=p["ma_s"], mode="lines",
                        name="短均線", line=dict(color="#FFA500", width=1.8)
                    ))
                    
                # 繪製長均線 (藍色 #1E90FF)
                if any(x is not None for x in p["ma_l"]):
                    fig.add_trace(go.Scatter(
                        x=p["dates"], y=p["ma_l"], mode="lines",
                        name="長均線", line=dict(color="#1E90FF", width=1.8)
                    ))
                
                # 【可調整】圖表高度 (height) 與圖例佈局設定
                fig.update_layout(
                    xaxis_rangeslider_visible=False,  # 隱藏下方預設滑塊以省空間
                    margin=dict(l=10, r=10, t=20, b=10),
                    height=380,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
                )
                fig.update_xaxes(type="category", tickangle=-45, nticks=15)
                
                # 渲染 Plotly 圖表
                st.plotly_chart(
                    fig,
                    use_container_width=True,
                    config={"staticPlot": True}  # 關閉靜態模式可恢復互動縮放功能
                )
else:
    st.info("目前沒有符合過濾條件的個股訊號。")
