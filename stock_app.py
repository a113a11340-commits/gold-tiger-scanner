"""
================================================================================
台股八策略監控系統（Streamlit 完整版 v5）
================================================================================
【v5 新增】
1. 「歷史回測」分頁：過去約 3 個月各訊號「隔日收盤」勝率
2. 手動按紐才執行回測（不會每次掃描自動跑）
3. 共用掃描時已下載的 Yahoo 日線，不重複抓 API

【沿用】衝突／彙整、訊號日誌、次日勝率回填

風險：勝率為樣本觀察，未經驗證，不構成投資建議。
================================================================================
"""

import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import numpy as np
from datetime import datetime, timedelta
from plotly.subplots import make_subplots
import plotly.graph_objects as go

st.set_page_config(layout="wide", page_title="台股八策略監控系統 v5")

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
table { width: 100% !important; font-size: 13px !important; }
th { background-color: #f0f2f6 !important; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# Sheet 設定
# ==============================================================================
MAIN_SHEET = {
    "base": "https://docs.google.com/spreadsheets/d/13Mv-7uaFyR1KcxNRVrhxCGAAntElKprB7ZeWWBxS3n0",
    "gid": "0",
    "id": "13Mv-7uaFyR1KcxNRVrhxCGAAntElKprB7ZeWWBxS3n0",
}
MA_SHEET_BASE = "https://docs.google.com/spreadsheets/d/1OGsbVKW-h8xwWq_9EO-W172WvdPbfDwjTx533WKaaX4"
MA_SHEETS = [
    {"name": "主頁", "gid": "0"},
    {"name": "分頁1", "gid": "1779050796"},
    {"name": "分頁2", "gid": "462300633"},
]

# 2026 台股休市日（可每年更新；週末另判）
TW_HOLIDAYS_2026 = {
    "2026-01-01", "2026-02-28",
    "2026-04-03", "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-06-19",
    "2026-09-25", "2026-09-28",
    "2026-10-09", "2026-10-10", "2026-10-25", "2026-10-26",
    "2026-12-25",
}

CONFIG = {
    "MIN_VOLUME": 500000,
    "RSI_PERIOD": 14,
    "RSI_OVERSOLD": 15,
    "RSI_DIVERGENCE_LOOKBACK": 30,
    "RSI_PASSIVATION_DAYS": 5,
    "RSI_PASSIVATION_LEVEL": 70,
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
# 交易日工具
# ==============================================================================
def is_trading_day(d: datetime) -> bool:
    if d.weekday() >= 5:
        return False
    return d.strftime("%Y-%m-%d") not in TW_HOLIDAYS_2026

def next_trading_day(d: datetime) -> datetime:
    x = d + timedelta(days=1)
    for _ in range(15):
        if is_trading_day(x):
            return x
        x += timedelta(days=1)
    return x

def prev_trading_day(d: datetime) -> datetime:
    x = d - timedelta(days=1)
    for _ in range(15):
        if is_trading_day(x):
            return x
        x -= timedelta(days=1)
    return x

# ==============================================================================
# 技術指標與 Yahoo
# ==============================================================================
def calc_ma_list(closes, period):
    ma = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        ma[i] = sum(closes[i - period + 1:i + 1]) / period
    return ma

def calc_rsi(closes, period=14):
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
            return {
                "closes": t_cls, "highs": t_highs, "lows": t_lows,
                "opens": t_opens, "vols": t_vols, "dates": t_dates
            }
        except Exception:
            continue
    return None

def get_close_on_or_after(hist, target_date_str: str):
    """取 target_date 當日收盤；若當日無資料則取之後第一個有資料日"""
    if not hist or not hist.get("dates"):
        return None, None
    for i, d in enumerate(hist["dates"]):
        if d >= target_date_str and hist["closes"][i] is not None:
            return hist["closes"][i], d
    return None, None

@st.cache_data(ttl=CONFIG["CACHE_TTL"])
def fetch_sheet_csv(base_url, gid):
    csv_url = f"{base_url}/export?format=csv&gid={gid}"
    res = HTTP_SESSION.get(csv_url, timeout=15)
    res.encoding = "utf-8"
    return res.text

def load_main_stocks():
    tasks = []
    try:
        csv_text = fetch_sheet_csv(MAIN_SHEET["base"], MAIN_SHEET["gid"])
        df = pd.read_csv(io.StringIO(csv_text))
        for _, row in df.iterrows():
            if df.shape[1] < 2:
                continue
            sid_raw = row.iloc[0]
            if pd.isna(sid_raw):
                continue
            sid = str(sid_raw).strip()
            if not sid.replace(".", "").replace("-", "").isdigit() or len(sid) < 4:
                continue
            sid = str(int(float(sid))) if "." in sid else sid
            name = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else sid
            tasks.append({"sid": sid, "name": name, "sheet": "主要清單", "short_n": 20, "long_n": 60})
    except Exception as e:
        st.error(f"讀取主要股票清單失敗: {e}")
    return tasks

def load_ma_stocks():
    tasks = []
    for sheet in MA_SHEETS:
        try:
            csv_text = fetch_sheet_csv(MA_SHEET_BASE, sheet["gid"])
            df = pd.read_csv(io.StringIO(csv_text))
            for _, row in df.iterrows():
                if df.shape[1] < 2:
                    continue
                sid_raw = row.iloc[0]
                if pd.isna(sid_raw):
                    continue
                sid = str(sid_raw).strip()
                if not sid.replace(".", "").replace("-", "").isdigit() or len(sid) < 4:
                    continue
                sid = str(int(float(sid))) if "." in sid else sid
                name = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else sid
                sn = pd.to_numeric(row.iloc[2], errors="coerce") if df.shape[1] > 2 else 20
                ln = pd.to_numeric(row.iloc[3], errors="coerce") if df.shape[1] > 3 else 60
                tasks.append({
                    "sid": sid, "name": name, "sheet": sheet["name"],
                    "short_n": int(sn) if pd.notna(sn) else 20,
                    "long_n": int(ln) if pd.notna(ln) else 60
                })
        except Exception as e:
            st.warning(f"讀取均線分頁 {sheet['name']} 失敗: {e}")
    return tasks

# ==============================================================================
# 八大策略（含方向與價位）
# ==============================================================================
def analyze_ma_signals(hist, short_n, long_n):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < max(short_n, long_n) + 30:
        return None
    T_close, T_open, T_high, T_low, T_vol = closes[-1], opens[-1], highs[-1], lows[-1], vols[-1]
    Y_close, Y_high, Y_low, Y_vol = closes[-2], highs[-2], lows[-2], vols[-2]
    B_close = closes[-3]
    is_gap_up = T_open > Y_high
    is_gap_down = T_open < Y_low
    signals, direction = [], None
    for label, period in [("短", short_n), ("長", long_n)]:
        if n < period + 5:
            continue
        ma_list = calc_ma_list(closes, period)
        if ma_list[-1] is None or ma_list[-2] is None or ma_list[-3] is None:
            continue
        T_ma, Y_ma, B_ma = ma_list[-1], ma_list[-2], ma_list[-3]
        trend = "⬆️" if T_ma > Y_ma else "↘"
        label_str = f"{label}({period}MA:{T_ma:.2f}){trend}"
        if Y_close <= Y_ma and T_close > T_ma:
            signals.append(f"🔥{'跳空' if is_gap_up else ''}突破均線{label_str}")
            direction = "買進"
        if Y_close >= Y_ma and T_close < T_ma:
            signals.append(f"📉{'跳空' if is_gap_down else ''}跌破均線{label_str}")
            direction = "賣出／減碼"
        if (B_close < B_ma and Y_close > Y_ma) and (T_low > T_ma) and (T_close > Y_close):
            signals.append(f"🔥{'跳空' if is_gap_up else ''}2日法則{label_str}")
            direction = "買進"
        if (Y_close < Y_ma and B_close >= B_ma) and T_close > T_ma:
            signals.append(f"🔄{'跳空' if is_gap_up else ''}反2日{label_str}")
            direction = "買進"
    if not signals or direction is None:
        return None
    vol_tag = ""
    if Y_vol and T_vol > Y_vol * 1.5:
        vol_tag = "🔴爆量"
    elif Y_vol and T_vol > Y_vol * 1.2:
        vol_tag = "🔴量增"
    entry = round(T_close * 1.005, 2) if direction == "買進" else "-"
    stop = round(min(T_low, T_close * 0.97), 2) if direction == "買進" else round(T_close * 1.03, 2)
    target = round(T_close * 1.06, 2) if direction == "買進" else round(T_close * 0.94, 2)
    return {
        "price": T_close, "signal": " + ".join(signals), "vol": vol_tag,
        "strategy": "均線轉折", "direction": direction,
        "entry": entry, "stop": stop, "target": target,
        "how": "突破類→隔日開盤附近買，停損均線下；跌破→減碼或出場",
        "side": "long" if direction == "買進" else "short"
    }

def analyze_weekly_bull(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma5 = calc_ma_list(closes, 5)
    ma10 = calc_ma_list(closes, 10)
    ma20 = calc_ma_list(closes, 20)
    if None in (ma5[-1], ma10[-1], ma20[-1], ma5[-2], ma10[-2], ma20[-2]):
        return None
    bull_align = ma5[-1] > ma10[-1] > ma20[-1] and closes[-1] > ma5[-1]
    sticky = False
    if ma5[-3] and ma10[-3] and ma20[-3]:
        prev_spread = max(ma5[-3], ma10[-3], ma20[-3]) - min(ma5[-3], ma10[-3], ma20[-3])
        curr_spread = max(ma5[-1], ma10[-1], ma20[-1]) - min(ma5[-1], ma10[-1], ma20[-1])
        if prev_spread / ma20[-3] < 0.025 and curr_spread > prev_spread * 1.5 and ma5[-1] > ma10[-1]:
            sticky = True
    avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    volume_surge = avg5_vol > 0 and vols[-1] >= avg5_vol * 1.5
    d0, d1, d2 = closes[-1], closes[-2], closes[-3]
    o0, o1, o2 = opens[-1], opens[-2], opens[-3]
    k_name = ""
    if (d0 > o0 and d1 > o1 and d2 > o2 and d0 > d1 > d2 and
            o1 >= min(o2, d2) and o1 <= max(o2, d2) and o0 >= min(o1, d1) and o0 <= max(o1, d1)):
        k_name = "三白兵"
    elif (d2 < o2 and abs(d1 - o1) <= (highs[-2] - lows[-2]) * 0.35 and d0 > o0 and d0 >= (d2 + o2) / 2):
        k_name = "晨星"
    if not bull_align:
        return None
    parts = ["均線多頭排列"]
    if sticky:
        parts.append("均線黏合後打開")
    if volume_surge:
        parts.append("爆量")
    if k_name:
        parts.append(k_name)
    return {
        "price": closes[-1], "signal": " + ".join(parts),
        "vol": "🔴爆量" if volume_surge else ("量增" if vols[-1] > vols[-2] else ""),
        "strategy": "周線多頭", "direction": "買進",
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], closes[-1] * 0.97, ma10[-1] * 0.99), 2),
        "target": round(closes[-1] * 1.08, 2),
        "how": "回檔不破MA10再買；停損MA10下",
        "side": "long"
    }

def analyze_jinbaoyin(hist):
    closes, lows, vols = hist["closes"], hist["lows"], hist["vols"]
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
    has_long_down = (ma120[-1] < ma120[-7]) or (ma240[-1] is not None and ma240[-1] < ma240[-7])
    if not has_long_down:
        return None
    if ma60[-1] - ma60[-7] < -0.008 * ma60[-1]:
        return None
    if not (ma5[-1] > ma60[-1] and ma10[-1] > ma60[-1] and ma20[-1] > ma60[-1] and closes[-1] > ma60[-1]):
        return None
    if lows[-1] < min(lows[-21:-1]) * 0.995:
        return None
    return {
        "price": closes[-1], "signal": "金包銀：長天期下壓+生命線支撐", "vol": "",
        "strategy": "金包銀", "direction": "買進（中期反彈）",
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(ma60[-1] * 0.98, closes[-1] * 0.96), 2),
        "target": round(closes[-1] * 1.10, 2),
        "how": "靠近MA60承接，停損生命線下約2%",
        "side": "long"
    }

def analyze_rsi_oversold(hist):
    closes, lows, vols = hist["closes"], hist["lows"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    rsi = calc_rsi(closes, CONFIG["RSI_PERIOD"])
    if rsi[-1] is None or rsi[-2] is None:
        return None
    if rsi[-1] > CONFIG["RSI_OVERSOLD"] or rsi[-2] > CONFIG["RSI_OVERSOLD"] or rsi[-1] <= rsi[-2]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None or closes[-1] < ma20[-1]:
        return None
    return {
        "price": closes[-1], "signal": f"RSI抄底：RSI={rsi[-1]:.1f}≤{CONFIG['RSI_OVERSOLD']}且向上", "vol": "",
        "strategy": "RSI抄底", "direction": "買進（短線反彈）",
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1] * 0.98, closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.06, 2),
        "how": "隔日低點不破再買，停損當日低點下2～3%",
        "side": "long"
    }

def analyze_fake_break(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < 800000:
        return None
    prev_low = min(lows[-23:-3])
    if any(l < prev_low * 0.995 for l in lows[-3:]) and closes[-1] > prev_low:
        return {
            "price": closes[-1], "signal": f"破底翻：跌破前低{prev_low:.2f}後站回", "vol": "",
            "strategy": "假突破破底翻", "direction": "買進",
            "entry": round(closes[-1] * 1.005, 2), "stop": round(prev_low * 0.985, 2),
            "target": round(closes[-1] * 1.07, 2),
            "how": "站回前低後買，停損前低下約1.5%", "side": "long"
        }
    prev_high = max(highs[-21:-1])
    if closes[-1] > prev_high:
        avg_vol = sum(vols[-21:-1]) / 20
        body = abs(closes[-1] - opens[-1])
        rng = highs[-1] - lows[-1]
        if avg_vol > 0 and vols[-1] >= avg_vol * 1.5 and rng > 0 and body / rng >= 0.55:
            return {
                "price": closes[-1], "signal": f"真突破：突破前高{prev_high:.2f}+放量", "vol": "🔴爆量",
                "strategy": "假突破破底翻", "direction": "買進",
                "entry": round(closes[-1] * 1.005, 2),
                "stop": round(min(lows[-1], prev_high * 0.99), 2),
                "target": round(closes[-1] * 1.08, 2),
                "how": "回測不破前高再買", "side": "long"
            }
    return None

def analyze_overnight(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 30 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    change = (closes[-1] - closes[-2]) / closes[-2]
    if not (CONFIG["OVERNIGHT_MIN_CHG"] <= change <= CONFIG["OVERNIGHT_MAX_CHG"]):
        return None
    has_limit = any(
        (closes[i] - closes[i - 1]) / closes[i - 1] >= CONFIG["OVERNIGHT_LIMIT_UP"]
        for i in range(max(-20, -n + 1), 0)
    )
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
    if closes[-1] <= opens[-1]:
        return None
    rng = highs[-1] - lows[-1]
    if rng > 0 and (highs[-1] - closes[-1]) / rng > 0.30:
        return None
    entry_min, entry_max = round(closes[-1] * 0.995, 2), round(closes[-1] * 1.010, 2)
    return {
        "price": closes[-1],
        "signal": f"一夜持股：漲{change*100:.1f}%｜隔日開盤{entry_min}~{entry_max}",
        "vol": "🔴量增", "strategy": "一夜持股", "direction": "買進（只抱一天）",
        "entry": f"{entry_min}~{entry_max}", "stop": round(closes[-1] * 0.97, 2),
        "target": round(closes[-1] * 1.04, 2),
        "how": "隔日開盤在區間才買，當日收盤前必平倉", "side": "long"
    }

def analyze_rsi_divergence(hist):
    closes, lows, highs, vols = hist["closes"], hist["lows"], hist["highs"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    rsi = calc_rsi(closes, CONFIG["RSI_PERIOD"])
    if any(x is None for x in rsi[-CONFIG["RSI_DIVERGENCE_LOOKBACK"]:]):
        return None
    recent_low_idx = n - 1 - int(np.argmin(lows[-10:]))
    prev_start = max(0, recent_low_idx - 25)
    prev_window = lows[prev_start:recent_low_idx - 3]
    if len(prev_window) >= 5:
        prev_low_idx = prev_start + int(np.argmin(prev_window))
        if (closes[recent_low_idx] < closes[prev_low_idx] and
                rsi[recent_low_idx] > rsi[prev_low_idx] and rsi[recent_low_idx] < 40):
            return {
                "price": closes[-1],
                "signal": f"底背離：價格新低RSI抬高（RSI={rsi[-1]:.1f}）", "vol": "",
                "strategy": "RSI背離", "direction": "買進（觀察反轉）",
                "entry": round(closes[-1] * 1.005, 2),
                "stop": round(min(lows[recent_low_idx] * 0.98, closes[-1] * 0.96), 2),
                "target": round(closes[-1] * 1.07, 2),
                "how": "等站上近期小高點再買，停損背離低點下", "side": "long"
            }
    recent_high_idx = n - 1 - int(np.argmax(highs[-10:]))
    prev_h_start = max(0, recent_high_idx - 25)
    prev_h_window = highs[prev_h_start:recent_high_idx - 3]
    if len(prev_h_window) >= 5:
        prev_high_idx = prev_h_start + int(np.argmax(prev_h_window))
        if (closes[recent_high_idx] > closes[prev_high_idx] and
                rsi[recent_high_idx] < rsi[prev_high_idx] and rsi[recent_high_idx] > 60):
            return {
                "price": closes[-1],
                "signal": f"頂背離：價格新高RSI降低（RSI={rsi[-1]:.1f}）", "vol": "",
                "strategy": "RSI背離", "direction": "賣出／減碼",
                "entry": "-", "stop": "-", "target": round(closes[-1] * 0.95, 2),
                "how": "持有者減碼；空手不追高", "side": "short"
            }
    return None

def analyze_rsi_passivation(hist):
    closes, vols = hist["closes"], hist["vols"]
    n = len(closes)
    if n < 40 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    rsi = calc_rsi(closes, CONFIG["RSI_PERIOD"])
    days, level = CONFIG["RSI_PASSIVATION_DAYS"], CONFIG["RSI_PASSIVATION_LEVEL"]
    if any(r is None or r < level for r in rsi[-days:]):
        return None
    ma5 = calc_ma_list(closes, 5)
    if ma5[-1] is None or ma5[-2] is None or closes[-1] <= ma5[-1] or ma5[-1] <= ma5[-2]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is not None and closes[-1] < ma20[-1]:
        return None
    return {
        "price": closes[-1],
        "signal": f"RSI鈍化：連續{days}日≥{level}（{rsi[-1]:.1f}）+站上五日線", "vol": "",
        "strategy": "RSI鈍化", "direction": "買進（順勢）",
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(ma5[-1] * 0.99, closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.06, 2),
        "how": "跌破五日線或RSI<70出場，停損約3%", "side": "long"
    }

# ==============================================================================
# 掃描 + 日誌 + 勝率
# ==============================================================================
def run_full_scan():
    """回傳 (results, hist_cache)。hist_cache 供歷史回測共用，避免重複下載。"""
    results = {s: [] for s in [
        "均線轉折", "周線多頭", "金包銀", "RSI抄底",
        "假突破破底翻", "一夜持股", "RSI背離", "RSI鈍化"
    ]}
    hist_cache = {}
    ma_stocks = load_ma_stocks()

    def process_ma(item):
        hist = get_yahoo_history(item["sid"])
        if hist is None:
            return None, None
        r = analyze_ma_signals(hist, item["short_n"], item["long_n"])
        if r:
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
        return r, (item["sid"], hist)

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as ex:
        for f in concurrent.futures.as_completed([ex.submit(process_ma, i) for i in ma_stocks]):
            try:
                res, pair = f.result()
                if pair:
                    hist_cache[pair[0]] = pair[1]
                if res:
                    results["均線轉折"].append(res)
            except Exception:
                pass

    main_stocks = load_main_stocks()

    def process_other(item):
        hist = get_yahoo_history(item["sid"])
        if hist is None:
            return [], None
        local = []
        for func, key in [
            (analyze_weekly_bull, "周線多頭"),
            (analyze_jinbaoyin, "金包銀"),
            (analyze_rsi_oversold, "RSI抄底"),
            (analyze_fake_break, "假突破破底翻"),
            (analyze_overnight, "一夜持股"),
            (analyze_rsi_divergence, "RSI背離"),
            (analyze_rsi_passivation, "RSI鈍化"),
        ]:
            r = func(hist)
            if r:
                r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
                local.append((key, r))
        return local, (item["sid"], hist)

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as ex:
        for f in concurrent.futures.as_completed([ex.submit(process_other, i) for i in main_stocks]):
            try:
                local, pair = f.result()
                if pair:
                    hist_cache[pair[0]] = pair[1]
                for key, res in local:
                    results[key].append(res)
            except Exception:
                pass
    return results, hist_cache

# ==============================================================================
# 歷史回測（共用 hist_cache，手動執行）
# ==============================================================================
def _ma_at(closes, end_idx, period):
    if end_idx + 1 < period:
        return None
    return sum(closes[end_idx - period + 1: end_idx + 1]) / period


def _rsi_to(closes, end_idx, period=14):
    """只算到 end_idx 的 RSI 序列（含 end_idx）"""
    sub = closes[: end_idx + 1]
    return calc_rsi(sub, period)


def signals_at_bar(hist, i):
    """在歷史第 i 根判斷當日會觸發哪些訊號。回傳 [(策略, 訊號名, side), ...]"""
    closes, highs, lows = hist["closes"], hist["highs"], hist["lows"]
    opens, vols = hist["opens"], hist["vols"]
    n = i + 1
    if n < 60:
        return []
    out = []
    c0, c1, c2 = closes[i], closes[i - 1], closes[i - 2]
    o0, o1, o2 = opens[i], opens[i - 1], opens[i - 2]
    h0, l0 = highs[i], lows[i]
    v0, v1, v2 = vols[i], vols[i - 1], vols[i - 2]
    ma5 = _ma_at(closes, i, 5)
    ma10 = _ma_at(closes, i, 10)
    ma20 = _ma_at(closes, i, 20)
    ma5_y = _ma_at(closes, i - 1, 5)
    ma5_3 = _ma_at(closes, i - 3, 5)
    ma10_3 = _ma_at(closes, i - 3, 10)
    ma20_3 = _ma_at(closes, i - 3, 20)

    # 周線多頭
    if ma5 and ma10 and ma20 and ma5 > ma10 > ma20 and c0 > ma5 and v0 >= CONFIG["MIN_VOLUME"]:
        avg5v = sum(vols[i - 5:i]) / 5 if i >= 5 else 0
        volume_surge = avg5v > 0 and v0 >= avg5v * 1.5
        sticky = False
        if ma5_3 and ma10_3 and ma20_3:
            prev_sp = max(ma5_3, ma10_3, ma20_3) - min(ma5_3, ma10_3, ma20_3)
            curr_sp = max(ma5, ma10, ma20) - min(ma5, ma10, ma20)
            if prev_sp / ma20_3 < 0.025 and curr_sp > prev_sp * 1.5 and ma5 > ma10:
                sticky = True
        three_white = (
            c0 > o0 and c1 > o1 and c2 > o2 and c0 > c1 > c2
            and o1 >= min(o2, c2) and o1 <= max(o2, c2)
            and o0 >= min(o1, c1) and o0 <= max(o1, c1)
        )
        morning = (
            c2 < o2 and abs(c1 - o1) <= (highs[i - 1] - lows[i - 1]) * 0.35
            and c0 > o0 and c0 >= (c2 + o2) / 2
        )
        tags = ["均線多頭排列"]
        if sticky:
            tags.append("均線黏合後打開")
        if volume_surge:
            tags.append("爆量")
        if three_white:
            tags.append("三白兵")
        if morning:
            tags.append("晨星")
        out.append(("周線多頭", " + ".join(tags), "long"))

    # 金包銀
    if n >= 250 and v0 >= 800000:
        ma60 = _ma_at(closes, i, 60)
        ma120 = _ma_at(closes, i, 120)
        ma240 = _ma_at(closes, i, 240)
        ma60_7 = _ma_at(closes, i - 7, 60)
        ma120_7 = _ma_at(closes, i - 7, 120)
        ma240_7 = _ma_at(closes, i - 7, 240)
        if ma60 and ma120 and ma60_7 and ma120_7:
            long_down = (ma120 < ma120_7) or (ma240 and ma240_7 and ma240 < ma240_7)
            if long_down and ma60 - ma60_7 >= -0.008 * ma60:
                if ma5 and ma10 and ma20 and ma5 > ma60 and ma10 > ma60 and ma20 > ma60 and c0 > ma60:
                    if i >= 20 and l0 >= min(lows[i - 20:i]) * 0.995:
                        out.append(("金包銀", "金包銀：長天期下壓+生命線支撐", "long"))

    rsi = _rsi_to(closes, i, CONFIG["RSI_PERIOD"])
    # RSI 抄底
    if len(rsi) >= 2 and rsi[-1] is not None and rsi[-2] is not None:
        if (rsi[-1] <= CONFIG["RSI_OVERSOLD"] and rsi[-2] <= CONFIG["RSI_OVERSOLD"]
                and rsi[-1] > rsi[-2] and ma20 and c0 >= ma20 and v0 >= CONFIG["MIN_VOLUME"]):
            out.append(("RSI抄底", f"RSI抄底：RSI≤{CONFIG['RSI_OVERSOLD']}且向上", "long"))

    # 假突破／破底翻
    if n >= 60 and v0 >= 800000 and i >= 23:
        prev_low = min(lows[i - 22: i - 2])
        if any(x < prev_low * 0.995 for x in lows[i - 2: i + 1]) and c0 > prev_low:
            out.append(("假突破破底翻", "破底翻：跌破前低後站回", "long"))
        prev_high = max(highs[i - 20: i])
        if c0 > prev_high:
            avg_vol = sum(vols[i - 20: i]) / 20
            body, rng = abs(c0 - o0), h0 - l0
            if avg_vol > 0 and v0 >= avg_vol * 1.5 and rng > 0 and body / rng >= 0.55:
                out.append(("假突破破底翻", "真突破：突破前高+放量", "long"))

    # 一夜持股
    if n >= 30 and v0 >= CONFIG["MIN_VOLUME"] and c1 > 0:
        chg = (c0 - c1) / c1
        if CONFIG["OVERNIGHT_MIN_CHG"] <= chg <= CONFIG["OVERNIGHT_MAX_CHG"]:
            has_limit = any(
                closes[k - 1] > 0 and (closes[k] - closes[k - 1]) / closes[k - 1] >= CONFIG["OVERNIGHT_LIMIT_UP"]
                for k in range(max(1, i - 19), i + 1)
            )
            avg5 = sum(vols[i - 5: i]) / 5 if i >= 5 else 0
            vol_ok = avg5 > 0 and v0 / avg5 >= CONFIG["OVERNIGHT_VOL_RATIO"] and v0 > v1 > v2
            ma_ok = ma5 and ma10 and ma20 and ma5 > ma10 > ma20
            shadow_ok = not (h0 - l0 > 0 and (h0 - c0) / (h0 - l0) > 0.30)
            if has_limit and vol_ok and ma_ok and c0 > o0 and shadow_ok:
                out.append(("一夜持股", "一夜持股：漲3～5%+曾漲停+量增+多頭", "long"))

    # RSI 背離
    if n >= 60 and v0 >= CONFIG["MIN_VOLUME"] and len(rsi) == n:
        if all(rsi[j] is not None for j in range(max(0, n - 30), n)):
            window_low = lows[i - 9: i + 1]
            recent_low_idx = i - 9 + int(np.argmin(window_low))
            prev_start = max(0, recent_low_idx - 25)
            prev_end = max(prev_start + 1, recent_low_idx - 3)
            if prev_end > prev_start and recent_low_idx >= i - 2:
                prev_low_idx = prev_start + int(np.argmin(lows[prev_start:prev_end]))
                if (closes[recent_low_idx] < closes[prev_low_idx]
                        and rsi[recent_low_idx] > rsi[prev_low_idx]
                        and rsi[recent_low_idx] < 40):
                    out.append(("RSI背離", "底背離：價格新低RSI抬高", "long"))
            window_high = highs[i - 9: i + 1]
            recent_high_idx = i - 9 + int(np.argmax(window_high))
            prev_h_start = max(0, recent_high_idx - 25)
            prev_h_end = max(prev_h_start + 1, recent_high_idx - 3)
            if prev_h_end > prev_h_start and recent_high_idx >= i - 2:
                prev_high_idx = prev_h_start + int(np.argmax(highs[prev_h_start:prev_h_end]))
                if (closes[recent_high_idx] > closes[prev_high_idx]
                        and rsi[recent_high_idx] < rsi[prev_high_idx]
                        and rsi[recent_high_idx] > 60):
                    out.append(("RSI背離", "頂背離：價格新高RSI降低", "short"))

    # RSI 鈍化
    if n >= 40 and v0 >= CONFIG["MIN_VOLUME"]:
        days, level = CONFIG["RSI_PASSIVATION_DAYS"], CONFIG["RSI_PASSIVATION_LEVEL"]
        ok = all(
            (rsi[i - k] is not None and rsi[i - k] >= level)
            for k in range(days) if i - k >= 0
        )
        if ok and ma5 and ma5_y and c0 > ma5 and ma5 > ma5_y:
            if ma20 is None or c0 >= ma20:
                out.append(("RSI鈍化", f"RSI鈍化：連續{days}日≥{level}+站上五日線", "long"))

    # 均線轉折（短20長60）
    for label, period in (("短", 20), ("長", 60)):
        ma_t = _ma_at(closes, i, period)
        ma_y = _ma_at(closes, i - 1, period)
        ma_b = _ma_at(closes, i - 2, period)
        if not ma_t or not ma_y or not ma_b:
            continue
        if c1 <= ma_y and c0 > ma_t:
            out.append(("均線轉折", f"突破均線({label}{period})", "long"))
        if c1 >= ma_y and c0 < ma_t:
            out.append(("均線轉折", f"跌破均線({label}{period})", "short"))
        if c2 < ma_b and c1 > ma_y and l0 > ma_t and c0 > c1:
            out.append(("均線轉折", f"2日法則({label}{period})", "long"))
        if c1 < ma_y and c2 >= ma_b and c0 > ma_t:
            out.append(("均線轉折", f"反2日({label}{period})", "long"))

    return out


def run_historical_backtest(hist_cache, signal_window=65):
    """
    用已下載的 hist_cache 做過去約 3 個月隔日勝率。
    不重新呼叫 Yahoo。
    """
    from collections import defaultdict
    stats = defaultdict(list)
    if not hist_cache:
        return pd.DataFrame()

    for sid, hist in hist_cache.items():
        closes = hist["closes"]
        n = len(closes)
        start_i = max(60, n - signal_window - 1)
        end_i = n - 2
        if start_i > end_i:
            continue
        for i in range(start_i, end_i + 1):
            sigs = signals_at_bar(hist, i)
            if not sigs:
                continue
            px0, px1 = closes[i], closes[i + 1]
            if px0 <= 0:
                continue
            ret_long = (px1 - px0) / px0 * 100.0
            for strategy, key, side in sigs:
                ret = ret_long if side == "long" else -ret_long
                stats[(strategy, key)].append(ret)

    rows = []
    for (strategy, key), rets in sorted(stats.items(), key=lambda x: (-len(x[1]), x[0][0])):
        total = len(rets)
        wins = sum(1 for r in rets if r > 0)
        rows.append({
            "策略": strategy,
            "訊號": key,
            "樣本數": total,
            "勝場": wins,
            "勝率%": round(wins / total * 100, 1) if total else 0.0,
            "平均報酬%": round(float(np.mean(rets)), 2) if rets else 0.0,
            "中位報酬%": round(float(np.median(rets)), 2) if rets else 0.0,
        })
    return pd.DataFrame(rows)


def build_log_rows(results, scan_time: str):
    """把當次掃描轉成日誌列（附加、不刪）"""
    signal_date = datetime.now().strftime("%Y-%m-%d")
    ntd = next_trading_day(datetime.now()).strftime("%Y-%m-%d")
    rows = []
    for strategy, items in results.items():
        for d in items:
            rows.append({
                "記錄時間": scan_time,
                "訊號日期": signal_date,
                "預計檢視日": ntd,
                "策略": strategy,
                "代號": d["sid"],
                "名稱": d["name"],
                "方向": d.get("direction", ""),
                "side": d.get("side", "long"),
                "訊號價": d["price"],
                "訊號內容": d["signal"],
                "建議買進": d.get("entry", "-"),
                "建議停損": d.get("stop", "-"),
                "建議目標": d.get("target", "-"),
                "次日收盤": "",
                "實際檢視日": "",
                "結果": "待檢視",  # 勝 / 負 / 待檢視
                "報酬%": "",
            })
    return rows

def evaluate_pending_logs(log_df: pd.DataFrame) -> pd.DataFrame:
    """對「待檢視」且預計檢視日已過的列，抓次日收盤判定勝負"""
    if log_df is None or log_df.empty:
        return log_df
    df = log_df.copy()
    today = datetime.now().strftime("%Y-%m-%d")
    pending_idx = df.index[
        (df["結果"].astype(str) == "待檢視") &
        (df["預計檢視日"].astype(str) <= today)
    ]
    # 按代號快取 hist
    hist_cache = {}
    for idx in pending_idx:
        sid = str(df.at[idx, "代號"])
        if sid not in hist_cache:
            hist_cache[sid] = get_yahoo_history(sid, max_n=30)
        hist = hist_cache[sid]
        target = str(df.at[idx, "預計檢視日"])
        close_px, actual_d = get_close_on_or_after(hist, target)
        if close_px is None:
            continue
        sig_px = float(df.at[idx, "訊號價"])
        side = str(df.at[idx, "side"])
        if sig_px <= 0:
            continue
        ret = (close_px - sig_px) / sig_px * 100
        if side == "short":
            ret = -ret
        # 一夜持股等：隔日收漲視為買進勝；賣出訊號：隔日收跌為勝
        win = ret > 0
        df.at[idx, "次日收盤"] = round(close_px, 2)
        df.at[idx, "實際檢視日"] = actual_d or target
        df.at[idx, "結果"] = "勝" if win else "負"
        df.at[idx, "報酬%"] = round(ret, 2)
    return df

def calc_win_rates(log_df: pd.DataFrame) -> dict:
    """各策略勝率（僅已結案）"""
    rates = {}
    if log_df is None or log_df.empty:
        return rates
    done = log_df[log_df["結果"].isin(["勝", "負"])]
    for strat, g in done.groupby("策略"):
        total = len(g)
        wins = (g["結果"] == "勝").sum()
        rates[strat] = {
            "n": total,
            "wins": int(wins),
            "rate": round(wins / total * 100, 1) if total else 0.0,
            "avg_ret": round(pd.to_numeric(g["報酬%"], errors="coerce").mean() or 0, 2)
        }
    return rates

def build_conflict_table(results) -> pd.DataFrame:
    """同一檔股票出現 ≥2 個策略 → 彙整"""
    by_sid = {}
    for strategy, items in results.items():
        for d in items:
            sid = d["sid"]
            by_sid.setdefault(sid, []).append(d)
    rows = []
    for sid, lst in by_sid.items():
        if len(lst) < 2:
            continue
        dirs = set(x.get("direction", "") for x in lst)
        conflict = any("買" in d for d in dirs) and any("賣" in d or "減碼" in d for d in dirs)
        rows.append({
            "代號": sid,
            "名稱": lst[0]["name"],
            "策略數": len(lst),
            "是否衝突(買賣相反)": "⚠️ 是" if conflict else "否（同向）",
            "方向彙整": "｜".join(f"{x['strategy']}:{x.get('direction','')}" for x in lst),
            "訊號彙整": "｜".join(f"[{x['strategy']}]{x['signal']}" for x in lst),
            "現價": lst[0]["price"],
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["是否衝突(買賣相反)", "策略數"], ascending=[False, False])

# ==============================================================================
# 圖表與 UI
# ==============================================================================
def make_chart(hist, title):
    closes = hist["closes"][-60:]
    opens = hist["opens"][-60:]
    highs = hist["highs"][-60:]
    lows = hist["lows"][-60:]
    vols = hist["vols"][-60:]
    x = list(range(len(closes)))
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(
        x=x, open=opens, high=highs, low=lows, close=closes,
        increasing_line_color="#FF3333", increasing_fillcolor="#FF3333",
        decreasing_line_color="#00A600", decreasing_fillcolor="#00A600",
        line_width=1.5, name="K線"
    ), row=1, col=1)
    ma5 = calc_ma_list(hist["closes"], 5)[-60:]
    ma20 = calc_ma_list(hist["closes"], 20)[-60:]
    fig.add_trace(go.Scatter(x=x, y=ma5, mode="lines", name="MA5", line=dict(color="#FFA500", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=ma20, mode="lines", name="MA20", line=dict(color="#1E90FF", width=1.5)), row=1, col=1)
    colors = ['#FF3333' if closes[i] >= opens[i] else '#00A600' for i in range(len(closes))]
    fig.add_trace(go.Bar(x=x, y=vols, marker_color=colors, name="成交量"), row=2, col=1)
    fig.update_layout(title=title, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=40, b=10), height=380, showlegend=True,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    fig.update_xaxes(showticklabels=False, showgrid=False)
    return fig

def render_strategy_tab(data_list, strategy_name, win_rates):
    wr = win_rates.get(strategy_name)
    if wr:
        st.caption(f"歷史勝率（次日收盤判定）：{wr['rate']}%（{wr['wins']}/{wr['n']}）｜平均報酬 {wr['avg_ret']}%")
    if not data_list:
        st.info(f"目前沒有符合【{strategy_name}】條件的個股。")
        return
    st.markdown(f"**共觸發 {len(data_list)} 檔**")
    df = pd.DataFrame([{
        "來源": d["sheet"], "代號": d["sid"], "名稱": d["name"],
        "現價": f"{d['price']:.2f}", "方向": d.get("direction", ""),
        "訊號": d["signal"],
        "建議買進價": d.get("entry", "-"), "建議停損價": d.get("stop", "-"),
        "建議目標價": d.get("target", "-"), "量能": d.get("vol", "")
    } for d in data_list])
    st.dataframe(df, use_container_width=True, hide_index=True)
    for idx, item in enumerate(data_list):
        with st.expander(f"🔍 {item['sid']} {item['name']}｜{item.get('direction','')}｜{item['signal']}", expanded=False):
            st.markdown(f"""
**操作說明**  
{item.get('how', '')}

| 項目 | 價格 |
|------|------|
| 現價 | {item['price']:.2f} |
| 建議買進價 | {item.get('entry', '-')} |
| 建議停損價 | {item.get('stop', '-')} |
| 建議目標價 | {item.get('target', '-')} |
""")
            fig = make_chart(item["hist"], f"{item['sid']} {item['name']}")
            st.plotly_chart(fig, use_container_width=True, key=f"c_{strategy_name}_{idx}_{item['sid']}")

# ==============================================================================
# 主介面
# ==============================================================================
st.title("🐯 台股八策略監控系統 v5")
st.caption(f"時間：{time.strftime('%Y-%m-%d %H:%M:%S')}｜衝突彙整 + 訊號日誌 + 歷史回測（手動）")

st.warning("所有勝率為樣本觀察、未經驗證，不構成投資建議。請自行嚴格停損。")

if "signal_log" not in st.session_state:
    st.session_state["signal_log"] = pd.DataFrame(columns=[
        "記錄時間", "訊號日期", "預計檢視日", "策略", "代號", "名稱", "方向", "side",
        "訊號價", "訊號內容", "建議買進", "建議停損", "建議目標",
        "次日收盤", "實際檢視日", "結果", "報酬%"
    ])
if "hist_cache" not in st.session_state:
    st.session_state["hist_cache"] = {}
if "backtest_df" not in st.session_state:
    st.session_state["backtest_df"] = None

col1, col2, col3 = st.columns(3)
with col1:
    do_scan = st.button("🔄 同步掃描並附加寫入日誌", use_container_width=True)
with col2:
    do_eval = st.button("📊 回填待檢視（次日勝率）", use_container_width=True)
with col3:
    if st.button("🚀 強制刷新快取", type="primary", use_container_width=True):
        st.cache_data.clear()
        SYMBOL_CACHE.clear()
        st.rerun()

if do_scan or "scan_results" not in st.session_state:
    with st.spinner("掃描八大策略中（同時快取日線供回測共用）..."):
        results, hist_cache = run_full_scan()
        st.session_state["scan_results"] = results
        st.session_state["hist_cache"] = hist_cache
        st.session_state["scan_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        new_rows = build_log_rows(results, st.session_state["scan_time"])
        if new_rows:
            add_df = pd.DataFrame(new_rows)
            st.session_state["signal_log"] = pd.concat(
                [st.session_state["signal_log"], add_df], ignore_index=True
            )
    if do_scan:
        st.success(
            f"已掃描並附加 {len(new_rows)} 筆訊號｜已快取 {len(st.session_state['hist_cache'])} 檔日線（可供歷史回測）"
        )

if do_eval:
    with st.spinner("回填次日收盤與勝負..."):
        st.session_state["signal_log"] = evaluate_pending_logs(st.session_state["signal_log"])
    st.success("已嘗試回填待檢視訊號")

results = st.session_state.get("scan_results", {})
log_df = st.session_state["signal_log"]
win_rates = calc_win_rates(log_df)

if win_rates:
    st.subheader("📈 日誌累計次日勝率（手動回填後才有）")
    wr_df = pd.DataFrame([
        {"策略": k, "樣本數": v["n"], "勝場": v["wins"], "勝率%": v["rate"], "平均報酬%": v["avg_ret"]}
        for k, v in win_rates.items()
    ]).sort_values("勝率%", ascending=False)
    st.dataframe(wr_df, use_container_width=True, hide_index=True)

tabs = st.tabs([
    "📉 歷史回測（3個月）",
    "⚡ 衝突／彙整", "📋 訊號日誌",
    "🔥 均線轉折", "⚔️ 周線多頭", "🌟 金包銀", "📉 RSI抄底",
    "🔄 假突破破底翻", "🌙 一夜持股", "📊 RSI背離", "📈 RSI鈍化"
])

with tabs[0]:
    st.markdown("""
### 過去約 3 個月「隔日收盤」勝率（手動更新）

**規則**  
- 訊號日收盤成立 → 看**下一交易日收盤**  
- 買進類：隔日上漲為勝；賣出類：隔日下跌為勝  
- **不會每次掃描自動跑**，請按下方按鈕手動執行  
- **使用掃描時已下載的日線**，不再重複向 Yahoo 抓資料  

請先按上方「同步掃描」至少一次（建立日線快取），再按回測。
""")
    n_cache = len(st.session_state.get("hist_cache") or {})
    st.caption(f"目前日線快取：{n_cache} 檔")
    do_bt = st.button("▶ 手動執行歷史回測（約3個月）", type="primary", use_container_width=True)
    if do_bt:
        if n_cache == 0:
            st.error("尚無日線快取。請先按「同步掃描並附加寫入日誌」。")
        else:
            with st.spinner(f"用已快取的 {n_cache} 檔日線計算中（不重複下載）..."):
                st.session_state["backtest_df"] = run_historical_backtest(st.session_state["hist_cache"])
                st.session_state["backtest_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            st.success("回測完成")

    bt = st.session_state.get("backtest_df")
    if bt is not None and not bt.empty:
        st.caption(f"回測完成時間：{st.session_state.get('backtest_time', '')}")
        st.dataframe(bt, use_container_width=True, hide_index=True)
        st.download_button(
            "下載回測勝率 CSV",
            bt.to_csv(index=False).encode("utf-8-sig"),
            "歷史回測_訊號勝率.csv",
            "text/csv",
        )
        st.info("樣本數太少（例如 <20）時勝率不穩定；未扣手續費／稅。")
    elif bt is not None and bt.empty:
        st.warning("回測無樣本（快取資料可能不足 60 根日K）。")
    else:
        st.info("尚未執行回測。按上方按鈕開始。")

with tabs[1]:
    st.markdown("""
**同一檔股票出現在多個策略時集中於此。**  
若一邊「買進」、一邊「賣出／減碼」會標成衝突，方便你對照，避免搞混。
""")
    conflict_df = build_conflict_table(results)
    if conflict_df.empty:
        st.info("目前沒有「同一檔出現在 ≥2 個策略」的股票。")
    else:
        st.dataframe(conflict_df, use_container_width=True, hide_index=True)

with tabs[2]:
    st.markdown("""
**訊號日誌（附加、不刪除）**  
每次按「同步掃描」會附加寫入。按「回填待檢視」用次日收盤判定勝／負。
""")
    if log_df is None or log_df.empty:
        st.info("尚無日誌。請先按「同步掃描並附加寫入日誌」。")
    else:
        st.caption(f"共 {len(log_df)} 筆｜待檢視 {(log_df['結果']=='待檢視').sum()} 筆")
        show_cols = [c for c in log_df.columns if c != "side"]
        st.dataframe(log_df[show_cols].iloc[::-1], use_container_width=True, hide_index=True)
        csv = log_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("下載完整日誌 CSV", csv, "signal_log.csv", "text/csv")

with tabs[3]:
    render_strategy_tab(results.get("均線轉折", []), "均線轉折", win_rates)
with tabs[4]:
    render_strategy_tab(results.get("周線多頭", []), "周線多頭", win_rates)
with tabs[5]:
    render_strategy_tab(results.get("金包銀", []), "金包銀", win_rates)
with tabs[6]:
    render_strategy_tab(results.get("RSI抄底", []), "RSI抄底", win_rates)
with tabs[7]:
    render_strategy_tab(results.get("假突破破底翻", []), "假突破破底翻", win_rates)
with tabs[8]:
    render_strategy_tab(results.get("一夜持股", []), "一夜持股", win_rates)
with tabs[9]:
    render_strategy_tab(results.get("RSI背離", []), "RSI背離", win_rates)
with tabs[10]:
    render_strategy_tab(results.get("RSI鈍化", []), "RSI鈍化", win_rates)

st.markdown("---")
st.caption("本系統僅供學習監控。投資有風險，請獨立判斷並自負盈虧。")
