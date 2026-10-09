"""
================================================================================
台股八策略監控系統（Streamlit 完整版）
================================================================================
整合策略：
1. 金虎南均線轉折（突破/跌破/2日法則/反2日）
2. 周線多頭 + K線型態
3. 金包銀
4. RSI 抄底
5. 假突破／破底翻
6. 一夜持股（可回測版）
7. RSI 背離
8. RSI 鈍化（獨立第8策略，搭配五日均線）

設計重點：
- 資料只抓一次（Yahoo 日線），所有策略共用計算
- 八個獨立 Tab，可分別點開
- 有訊號的股票可展開 Plotly 圖表（K線 + 指標 + 成交量）
- 參數集中在 CONFIG，方便調整
- 含明確風險提醒，不宣稱任何勝率

使用方式：
1. 安裝依賴：pip install streamlit pandas requests plotly
2. 修改下方 SHEET_BASE 與 MONITOR_SHEETS 為你的 Google Sheet
3. 執行：streamlit run 台股八策略監控系統_Streamlit完整版.py

重要風險提醒：
- 本系統僅為監控與學習工具，不構成投資建議
- 所有策略歷史表現未經驗證，實盤有虧損可能
- Yahoo 資料可能缺漏或未還原股價
- 請務必自行回測並扣除交易成本後再評估
================================================================================
"""

import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import numpy as np
from plotly.subplots import make_subplots
import plotly.graph_objects as go

# ==============================================================================
# 1. 網頁設定與全域參數
# ==============================================================================
st.set_page_config(layout="wide", page_title="台股八策略監控系統")

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
table { width: 100% !important; font-size: 15px !important; }
th { background-color: #f0f2f6 !important; }
</style>
""", unsafe_allow_html=True)

# ---------- 請修改成你的 Google Sheet ----------
SHEET_BASE = "https://docs.google.com/spreadsheets/d/1OGsbVKW-h8xwWq_9EO-W172WvdPbfDwjTx533WKaaX4"
MONITOR_SHEETS = [
    {"name": "主頁", "gid": "0"},
    {"name": "分頁1", "gid": "1779050796"},
    {"name": "分頁2", "gid": "462300633"},
]

# ---------- 核心參數（全部集中這裡） ----------
CONFIG = {
    "MIN_VOLUME": 500000,          # 最小成交量（股）
    "RSI_PERIOD": 14,
    "RSI_OVERSOLD": 15,            # RSI 抄底門檻
    "RSI_DIVERGENCE_LOOKBACK": 30, # 背離尋找視窗
    "RSI_PASSIVATION_DAYS": 5,     # 鈍化最少連續天數
    "RSI_PASSIVATION_LEVEL": 70,   # 上漲鈍化門檻
    "OVERNIGHT_MIN_CHG": 0.03,
    "OVERNIGHT_MAX_CHG": 0.05,
    "OVERNIGHT_LIMIT_UP": 0.095,
    "OVERNIGHT_VOL_RATIO": 1.4,
    "BATCH_WORKERS": 20,
    "CACHE_TTL": 300,
}

HTTP_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30)
HTTP_SESSION.mount("https://", adapter)
HTTP_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
SYMBOL_CACHE = {}

# ==============================================================================
# 2. 資料抓取模組（共用一次下載）
# ==============================================================================
def get_ma(arr, period, offset=0):
    if period <= 0 or len(arr) < offset + period:
        return None
    sub = arr[offset:offset + period]
    return sum(sub) / period if len(sub) == period else None

def calc_ma_list(closes, period):
    """回傳與 closes 等長的 MA 列表（前面不足為 None）"""
    ma = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        ma[i] = sum(closes[i - period + 1:i + 1]) / period
    return ma

def calc_rsi(closes, period=14):
    """Wilder RSI，回傳與 closes 等長列表"""
    n = len(closes)
    rsi = [None] * n
    if n < period + 1:
        return rsi
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    rsi[period] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    for j in range(period + 1, n):
        d = closes[j] - closes[j - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        rsi[j] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return rsi

def get_yahoo_history(sid: str, max_n: int = 180):
    if sid in SYMBOL_CACHE:
        suffixes = [SYMBOL_CACHE[sid]]
    else:
        suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={max_n}d&interval=1d"
            res = HTTP_SESSION.get(url, timeout=5)
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
                    t_cls.append(float(raw_cls[i]))
                    t_highs.append(float(raw_high[i]))
                    t_lows.append(float(raw_low[i]))
                    t_opens.append(float(raw_op[i]) if raw_op[i] is not None else float(raw_cls[i]))
                    t_vols.append(float(raw_vol[i]) if raw_vol[i] is not None else 0.0)
                    if i < len(timestamps):
                        t_dates.append(time.strftime("%Y-%m-%d", time.localtime(timestamps[i])))
                    else:
                        t_dates.append("")
            if len(t_cls) < 60:
                continue
            SYMBOL_CACHE[sid] = sfx
            # 回傳最新在最後（方便計算）
            return {
                "closes": t_cls,
                "highs": t_highs,
                "lows": t_lows,
                "opens": t_opens,
                "vols": t_vols,
                "dates": t_dates
            }
        except Exception:
            continue
    return None

@st.cache_data(ttl=CONFIG["CACHE_TTL"])
def fetch_sheet_csv(gid):
    csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}"
    res = HTTP_SESSION.get(csv_url, timeout=10)
    res.encoding = "utf-8"
    return res.text

def load_all_stocks():
    """從所有分頁讀取股票清單"""
    tasks = []
    for sheet in MONITOR_SHEETS:
        try:
            csv_text = fetch_sheet_csv(sheet["gid"])
            df = pd.read_csv(io.StringIO(csv_text))
            for _, row in df.iterrows():
                if df.shape[1] < 2:
                    continue
                sid_raw = row.iloc[0]
                if pd.isna(sid_raw):
                    continue
                sid = str(sid_raw).strip()
                if sid.replace(".", "").replace("-", "").isdigit():
                    sid = str(int(float(sid)))
                name = str(row.iloc[1]) if df.shape[1] > 1 else sid
                # 短長均線（金虎南用）
                sn = pd.to_numeric(row.iloc[2], errors="coerce") if df.shape[1] > 2 else 20
                ln = pd.to_numeric(row.iloc[3], errors="coerce") if df.shape[1] > 3 else 60
                tasks.append({
                    "sid": sid,
                    "name": name,
                    "sheet": sheet["name"],
                    "short_n": int(sn) if pd.notna(sn) else 20,
                    "long_n": int(ln) if pd.notna(ln) else 60
                })
        except Exception as e:
            st.warning(f"讀取分頁 {sheet['name']} 失敗: {e}")
    return tasks

# ==============================================================================
# 3. 八大策略判斷函式（全部輸入同一份 hist）
# ==============================================================================
def analyze_ma_signals(hist, short_n, long_n):
    """1. 金虎南均線轉折"""
    closes = hist["closes"]
    highs = hist["highs"]
    lows = hist["lows"]
    opens = hist["opens"]
    vols = hist["vols"]
    n = len(closes)
    if n < max(short_n, long_n) + 30:
        return None

    T_close, T_open, T_high, T_low, T_vol = closes[-1], opens[-1], highs[-1], lows[-1], vols[-1]
    Y_close, Y_high, Y_low, Y_vol = closes[-2], highs[-2], lows[-2], vols[-2]
    B_close = closes[-3]

    is_gap_up = T_open > Y_high
    is_gap_down = T_open < Y_low

    signals = []
    for label, period in [("短", short_n), ("長", long_n)]:
        if n < period + 5:
            continue
        T_ma = get_ma(closes[::-1], period, 0)  # 最新在前的寫法需注意，這裡改用正確索引
        # 重新用正確方向計算
        ma_list = calc_ma_list(closes, period)
        if ma_list[-1] is None or ma_list[-2] is None or ma_list[-3] is None:
            continue
        T_ma = ma_list[-1]
        Y_ma = ma_list[-2]
        B_ma = ma_list[-3]
        trend = "⬆️" if T_ma > Y_ma else "↘"
        label_str = f"{label}({period}MA:{T_ma:.2f}){trend}"

        if Y_close <= Y_ma and T_close > T_ma:
            gap = "跳空" if is_gap_up else ""
            signals.append(f"🔥{gap}突破均線{label_str}")
        if Y_close >= Y_ma and T_close < T_ma:
            gap = "跳空" if is_gap_down else ""
            signals.append(f"📉{gap}跌破均線{label_str}")
        # 2日法則
        if (B_close < B_ma and Y_close > Y_ma) and (T_low > T_ma) and (T_close > Y_close):
            gap = "跳空" if is_gap_up else ""
            signals.append(f"🔥{gap}2日法則(強勢突破){label_str}")
        # 反2日
        if (Y_close < Y_ma and B_close >= B_ma) and T_close > T_ma:
            gap = "跳空" if is_gap_up else ""
            if (T_close - T_ma) / T_ma > 0.005:
                signals.append(f"🔄{gap}反2日(假跌破){label_str}[強勢反轉]")
            else:
                signals.append(f"🔄{gap}反2日(假跌破){label_str}")

    if not signals:
        return None

    vol_tag = ""
    if Y_vol and T_vol > Y_vol * 1.5:
        vol_tag = "🔴爆量"
    elif Y_vol and T_vol > Y_vol * 1.2:
        vol_tag = "🔴量增"
    elif Y_vol and T_vol > Y_vol:
        vol_tag = "量增"

    return {
        "price": T_close,
        "signal": " + ".join(signals),
        "vol": vol_tag,
        "strategy": "均線轉折"
    }


def analyze_weekly_bull(hist):
    """2. 周線多頭簡化版（日線近似 + K線）"""
    closes = hist["closes"]
    highs = hist["highs"]
    lows = hist["lows"]
    opens = hist["opens"]
    vols = hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None

    ma5 = calc_ma_list(closes, 5)
    ma10 = calc_ma_list(closes, 10)
    ma20 = calc_ma_list(closes, 20)
    if None in (ma5[-1], ma10[-1], ma20[-1]):
        return None
    if not (ma5[-1] > ma10[-1] > ma20[-1]):
        return None
    if closes[-1] <= ma5[-1]:
        return None

    # 簡單 K 線標記
    d0, d1, d2 = closes[-1], closes[-2], closes[-3]
    o0, o1, o2 = opens[-1], opens[-2], opens[-3]
    k_name = ""
    # 三白兵簡化
    if (d0 > o0 and d1 > o1 and d2 > o2 and d0 > d1 > d2 and
            o1 >= o2 and o1 <= d2 and o0 >= o1 and o0 <= d1):
        k_name = "三白兵"
    # 晨星簡化
    elif (d2 < o2 and abs(d1 - o1) <= (highs[-2] - lows[-2]) * 0.35 and
          d0 > o0 and d0 >= (d2 + o2) / 2):
        k_name = "晨星"

    signal = f"均線多頭排列"
    if k_name:
        signal += f" + {k_name}"
    return {
        "price": closes[-1],
        "signal": signal,
        "vol": "量能正常" if vols[-1] > vols[-2] else "",
        "strategy": "周線多頭"
    }


def analyze_jinbaoyin(hist):
    """3. 金包銀簡化版"""
    closes = hist["closes"]
    highs = hist["highs"]
    lows = hist["lows"]
    vols = hist["vols"]
    n = len(closes)
    if n < 250 or vols[-1] < 800000:
        return None

    ma5 = calc_ma_list(closes, 5)
    ma10 = calc_ma_list(closes, 10)
    ma20 = calc_ma_list(closes, 20)
    ma60 = calc_ma_list(closes, 60)
    ma120 = calc_ma_list(closes, 120)
    ma240 = calc_ma_list(closes, 240)
    if None in (ma60[-1], ma120[-1]):
        return None

    # 長天期下壓
    has_long_down = (ma120[-1] is not None and ma120[-1] < ma120[-7]) or \
                    (ma240[-1] is not None and ma240[-1] < ma240[-7])
    if not has_long_down:
        return None
    # 生命線趨平或上彎
    if ma60[-1] - ma60[-7] < -0.008 * ma60[-1]:
        return None
    # 短均線在生命線上方 + 股價站上
    if not (ma5[-1] > ma60[-1] and ma10[-1] > ma60[-1] and ma20[-1] > ma60[-1] and closes[-1] > ma60[-1]):
        return None
    # 近20日未創新低
    recent_low = min(lows[-21:-1])
    if lows[-1] < recent_low * 0.995:
        return None

    return {
        "price": closes[-1],
        "signal": "金包銀：長天期下壓 + 生命線支撐",
        "vol": "",
        "strategy": "金包銀"
    }


def analyze_rsi_oversold(hist):
    """4. RSI 抄底"""
    closes = hist["closes"]
    vols = hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    rsi = calc_rsi(closes, CONFIG["RSI_PERIOD"])
    if rsi[-1] is None or rsi[-2] is None:
        return None
    if rsi[-1] > CONFIG["RSI_OVERSOLD"] or rsi[-2] > CONFIG["RSI_OVERSOLD"]:
        return None
    if rsi[-1] <= rsi[-2]:  # 必須向上翻轉
        return None
    ma20 = get_ma(closes[::-1], 20, 0)  # 簡化
    ma20_list = calc_ma_list(closes, 20)
    if ma20_list[-1] is None or closes[-1] < ma20_list[-1]:
        return None

    return {
        "price": closes[-1],
        "signal": f"RSI抄底：RSI={rsi[-1]:.1f} ≤{CONFIG['RSI_OVERSOLD']} 且向上",
        "vol": "",
        "strategy": "RSI抄底"
    }


def analyze_fake_break(hist):
    """5. 假突破／破底翻簡化版"""
    closes = hist["closes"]
    highs = hist["highs"]
    lows = hist["lows"]
    opens = hist["opens"]
    vols = hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < 800000:
        return None

    # 破底翻
    lookback = 20
    prev_low = min(lows[-lookback-3:-3])
    broken = any(l < prev_low * 0.995 for l in lows[-3:])
    if broken and closes[-1] > prev_low:
        return {
            "price": closes[-1],
            "signal": f"破底翻：跌破前低{prev_low:.2f}後站回",
            "vol": "",
            "strategy": "假突破破底翻"
        }

    # 真突破
    prev_high = max(highs[-21:-1])
    if closes[-1] > prev_high:
        avg_vol = sum(vols[-21:-1]) / 20
        body = abs(closes[-1] - opens[-1])
        range_ = highs[-1] - lows[-1]
        if avg_vol > 0 and vols[-1] >= avg_vol * 1.5 and range_ > 0 and body / range_ >= 0.55:
            return {
                "price": closes[-1],
                "signal": f"真突破：收盤突破前高{prev_high:.2f} + 放量",
                "vol": "🔴爆量",
                "strategy": "假突破破底翻"
            }
    return None


def analyze_overnight(hist):
    """6. 一夜持股（可回測版）"""
    closes = hist["closes"]
    highs = hist["highs"]
    lows = hist["lows"]
    opens = hist["opens"]
    vols = hist["vols"]
    n = len(closes)
    if n < 30 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None

    change = (closes[-1] - closes[-2]) / closes[-2]
    if not (CONFIG["OVERNIGHT_MIN_CHG"] <= change <= CONFIG["OVERNIGHT_MAX_CHG"]):
        return None

    # 過去20日曾漲停
    has_limit = False
    for i in range(-20, 0):
        if i - 1 < -n:
            continue
        chg = (closes[i] - closes[i - 1]) / closes[i - 1]
        if chg >= CONFIG["OVERNIGHT_LIMIT_UP"]:
            has_limit = True
            break
    if not has_limit:
        return None

    avg5 = sum(vols[-6:-1]) / 5
    if avg5 <= 0 or vols[-1] / avg5 < CONFIG["OVERNIGHT_VOL_RATIO"]:
        return None
    if not (vols[-1] > vols[-2] > vols[-3]):
        return None

    ma5 = calc_ma_list(closes, 5)
    ma10 = calc_ma_list(closes, 10)
    ma20 = calc_ma_list(closes, 20)
    if None in (ma5[-1], ma10[-1], ma20[-1]) or not (ma5[-1] > ma10[-1] > ma20[-1]):
        return None

    # 實體陽線 + 上影線限制
    if closes[-1] <= opens[-1]:
        return None
    rng = highs[-1] - lows[-1]
    if rng > 0 and (highs[-1] - closes[-1]) / rng > 0.30:
        return None

    entry_min = closes[-1] * 0.995
    entry_max = closes[-1] * 1.010
    return {
        "price": closes[-1],
        "signal": f"一夜持股候選：漲幅{change*100:.1f}%｜隔日開盤確認{entry_min:.2f}~{entry_max:.2f}",
        "vol": "🔴量增",
        "strategy": "一夜持股"
    }


def analyze_rsi_divergence(hist):
    """7. RSI 背離（簡化可量化版）"""
    closes = hist["closes"]
    lows = hist["lows"]
    highs = hist["highs"]
    vols = hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None

    rsi = calc_rsi(closes, CONFIG["RSI_PERIOD"])
    lookback = CONFIG["RSI_DIVERGENCE_LOOKBACK"]
    if any(x is None for x in rsi[-lookback:]):
        return None

    # 找近 lookback 內的兩個低點（底背離）
    # 簡化：比較最近低點與前一個明顯低點
    recent_low_idx = n - 1 - np.argmin(lows[-10:])
    prev_window = lows[max(0, recent_low_idx - 25):recent_low_idx - 3]
    if len(prev_window) < 5:
        return None
    prev_low_idx = max(0, recent_low_idx - 25) + np.argmin(prev_window)

    price_ll = closes[recent_low_idx] < closes[prev_low_idx]  # 價格更低低點
    rsi_hl = rsi[recent_low_idx] > rsi[prev_low_idx]         # RSI 更高低點
    if price_ll and rsi_hl and rsi[recent_low_idx] < 40:
        return {
            "price": closes[-1],
            "signal": f"底背離：價格新低但RSI抬高（RSI={rsi[-1]:.1f}）",
            "vol": "",
            "strategy": "RSI背離"
        }

    # 頂背離簡化
    recent_high_idx = n - 1 - np.argmax(highs[-10:])
    prev_h_window = highs[max(0, recent_high_idx - 25):recent_high_idx - 3]
    if len(prev_h_window) < 5:
        return None
    prev_high_idx = max(0, recent_high_idx - 25) + np.argmax(prev_h_window)
    price_hh = closes[recent_high_idx] > closes[prev_high_idx]
    rsi_lh = rsi[recent_high_idx] < rsi[prev_high_idx]
    if price_hh and rsi_lh and rsi[recent_high_idx] > 60:
        return {
            "price": closes[-1],
            "signal": f"頂背離：價格新高但RSI降低（RSI={rsi[-1]:.1f}）",
            "vol": "",
            "strategy": "RSI背離"
        }
    return None


def analyze_rsi_passivation(hist):
    """8. RSI 鈍化（獨立第8策略，搭配五日均線）"""
    closes = hist["closes"]
    opens = hist["opens"]
    highs = hist["highs"]
    lows = hist["lows"]
    vols = hist["vols"]
    n = len(closes)
    if n < 40 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None

    rsi = calc_rsi(closes, CONFIG["RSI_PERIOD"])
    days = CONFIG["RSI_PASSIVATION_DAYS"]
    level = CONFIG["RSI_PASSIVATION_LEVEL"]

    # 連續 days 天 RSI ≥ level
    if any(r is None or r < level for r in rsi[-days:]):
        return None

    # 搭配五日均線
    ma5 = calc_ma_list(closes, 5)
    if ma5[-1] is None or ma5[-2] is None:
        return None
    if closes[-1] <= ma5[-1]:
        return None
    if ma5[-1] <= ma5[-2]:  # 五日線必須向上
        return None

    # 可選：收盤 > SMA20 過濾弱勢
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is not None and closes[-1] < ma20[-1]:
        return None

    return {
        "price": closes[-1],
        "signal": f"RSI鈍化：連續{days}日RSI≥{level}（目前{rsi[-1]:.1f}）+ 站上五日線向上",
        "vol": "量能" if vols[-1] > vols[-2] else "",
        "strategy": "RSI鈍化"
    }


# ==============================================================================
# 4. 主掃描與圖表
# ==============================================================================
def run_full_scan(stock_list):
    """一次抓資料，跑完全部八策略"""
    results = {s: [] for s in [
        "均線轉折", "周線多頭", "金包銀", "RSI抄底",
        "假突破破底翻", "一夜持股", "RSI背離", "RSI鈍化"
    ]}

    def process_one(item):
        hist = get_yahoo_history(item["sid"])
        if hist is None:
            return []
        local = []
        # 1
        r = analyze_ma_signals(hist, item["short_n"], item["long_n"])
        if r:
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
            local.append(r)
        # 2
        r = analyze_weekly_bull(hist)
        if r:
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
            local.append(r)
        # 3
        r = analyze_jinbaoyin(hist)
        if r:
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
            local.append(r)
        # 4
        r = analyze_rsi_oversold(hist)
        if r:
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
            local.append(r)
        # 5
        r = analyze_fake_break(hist)
        if r:
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
            local.append(r)
        # 6
        r = analyze_overnight(hist)
        if r:
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
            local.append(r)
        # 7
        r = analyze_rsi_divergence(hist)
        if r:
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
            local.append(r)
        # 8
        r = analyze_rsi_passivation(hist)
        if r:
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
            local.append(r)
        return local

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as executor:
        futures = [executor.submit(process_one, item) for item in stock_list]
        for f in concurrent.futures.as_completed(futures):
            try:
                for res in f.result():
                    results[res["strategy"]].append(res)
            except Exception:
                pass
    return results


def make_chart(hist, title, extra_lines=None):
    """統一 K 線 + 成交量圖表"""
    closes = hist["closes"][-60:]
    opens = hist["opens"][-60:]
    highs = hist["highs"][-60:]
    lows = hist["lows"][-60:]
    vols = hist["vols"][-60:]
    dates = hist["dates"][-60:]
    x = list(range(len(closes)))

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=[0.75, 0.25])

    fig.add_trace(go.Candlestick(
        x=x, open=opens, high=highs, low=lows, close=closes,
        increasing_line_color="#FF3333", increasing_fillcolor="#FF3333",
        decreasing_line_color="#00A600", decreasing_fillcolor="#00A600",
        line_width=1.5, name="K線"
    ), row=1, col=1)

    # 預設畫 MA5 / MA20
    ma5 = calc_ma_list(hist["closes"], 5)[-60:]
    ma20 = calc_ma_list(hist["closes"], 20)[-60:]
    fig.add_trace(go.Scatter(x=x, y=ma5, mode="lines", name="MA5",
                             line=dict(color="#FFA500", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=ma20, mode="lines", name="MA20",
                             line=dict(color="#1E90FF", width=1.5)), row=1, col=1)

    if extra_lines:
        for line in extra_lines:
            fig.add_trace(go.Scatter(x=x, y=line["y"][-60:], mode="lines",
                                     name=line["name"], line=dict(color=line.get("color", "#888"), width=1.2)),
                          row=1, col=1)

    colors = ['#FF3333' if closes[i] >= opens[i] else '#00A600' for i in range(len(closes))]
    fig.add_trace(go.Bar(x=x, y=vols, marker_color=colors, name="成交量"), row=2, col=1)

    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=40, b=10),
        height=420,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0)
    )
    fig.update_xaxes(showticklabels=False, showgrid=False)
    return fig


def render_strategy_tab(data_list, strategy_name):
    if not data_list:
        st.info(f"目前沒有符合【{strategy_name}】條件的個股。")
        return

    st.markdown(f"**共觸發 {len(data_list)} 檔**")
    df = pd.DataFrame([{
        "來源": d["sheet"],
        "代號": d["sid"],
        "名稱": d["name"],
        "現價": f"{d['price']:.2f}",
        "訊號": d["signal"],
        "量能": d.get("vol", "")
    } for d in data_list])
    st.dataframe(df, use_container_width=True, hide_index=True)

    for idx, item in enumerate(data_list):
        with st.expander(f"🔍 {item['sid']} {item['name']} — {item['signal']}", expanded=False):
            fig = make_chart(item["hist"], f"{item['sid']} {item['name']}")
            st.plotly_chart(fig, use_container_width=True,
                            key=f"chart_{strategy_name}_{idx}_{item['sid']}")


# ==============================================================================
# 5. 主介面
# ==============================================================================
st.title("🐯 台股八策略監控系統（完整整合版）")
st.caption(f"最後更新：{time.strftime('%Y-%m-%d %H:%M:%S')}｜資料來源：Yahoo Finance｜僅供學習，不構成投資建議")

st.warning("⚠️ 風險提醒：所有策略歷史表現未經驗證，實盤交易有虧損可能。請自行回測並嚴格執行停損。")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 同步所有分頁並重新掃描", use_container_width=True):
        st.cache_data.clear()
        with st.spinner("正在抓取資料並計算八大策略，請稍候..."):
            stocks = load_all_stocks()
            st.session_state["scan_results"] = run_full_scan(stocks)
            st.session_state["scan_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        st.rerun()

with col2:
    if st.button("🚀 強制刷新（清除快取）", type="primary", use_container_width=True):
        st.cache_data.clear()
        SYMBOL_CACHE.clear()
        with st.spinner("強制刷新中..."):
            stocks = load_all_stocks()
            st.session_state["scan_results"] = run_full_scan(stocks)
            st.session_state["scan_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        st.rerun()

if "scan_results" not in st.session_state:
    with st.spinner("首次載入，正在掃描..."):
        stocks = load_all_stocks()
        st.session_state["scan_results"] = run_full_scan(stocks)
        st.session_state["scan_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

results = st.session_state["scan_results"]

# 八個 Tab
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "🔥 均線轉折",
    "⚔️ 周線多頭",
    "🌟 金包銀",
    "📉 RSI抄底",
    "🔄 假突破破底翻",
    "🌙 一夜持股",
    "📊 RSI背離",
    "📈 RSI鈍化（第8）"
])

with tab1:
    render_strategy_tab(results["均線轉折"], "均線轉折")
with tab2:
    render_strategy_tab(results["周線多頭"], "周線多頭")
with tab3:
    render_strategy_tab(results["金包銀"], "金包銀")
with tab4:
    render_strategy_tab(results["RSI抄底"], "RSI抄底")
with tab5:
    render_strategy_tab(results["假突破破底翻"], "假突破破底翻")
with tab6:
    render_strategy_tab(results["一夜持股"], "一夜持股")
with tab7:
    render_strategy_tab(results["RSI背離"], "RSI背離")
with tab8:
    st.markdown("""
    **RSI 鈍化策略說明（第8策略）**  
    - 連續 5 日 RSI(14) ≥ 70（上漲鈍化）  
    - 收盤站上五日均線且五日線向上  
    - 建議搭配大盤或個股 SMA20 過濾  
    - 出場：RSI 跌破 70 或跌破五日線，停損約 3%  
    - 此為順勢策略，趨勢結束時回撤風險高，請嚴格執行停損
    """)
    render_strategy_tab(results["RSI鈍化"], "RSI鈍化")

st.markdown("---")
st.caption("本系統僅供技術分析學習與監控使用。投資有風險，請獨立判斷並自負盈虧。")
