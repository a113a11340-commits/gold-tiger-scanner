"""
================================================================================
台股八策略監控系統（Streamlit 完整版 v3）
================================================================================
【本次更新重點】
1. 周線多頭恢復較完整邏輯（均線黏合後爆量 + 多頭排列 + K線）
2. 八大策略全部加上：
   - 方向（買進／賣出／減碼）
   - 建議買進價
   - 建議停損價
   - 建議出場／目標價
3. 表格直接顯示方向與價位，讓普通人看得懂

【Sheet 讀取】
- 策略1 均線轉折：金虎南 Sheet
- 策略2～8：主要清單 Sheet

風險提醒：本系統僅供學習監控，不構成投資建議。所有策略未經驗證。
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

st.set_page_config(layout="wide", page_title="台股八策略監控系統 v3")

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
table { width: 100% !important; font-size: 14px !important; }
th { background-color: #f0f2f6 !important; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# Sheet 設定
# ==============================================================================
MAIN_SHEET = {
    "base": "https://docs.google.com/spreadsheets/d/13Mv-7uaFyR1KcxNRVrhxCGAAntElKprB7ZeWWBxS3n0",
    "gid": "0"
}
MA_SHEET_BASE = "https://docs.google.com/spreadsheets/d/1OGsbVKW-h8xwWq_9EO-W172WvdPbfDwjTx533WKaaX4"
MA_SHEETS = [
    {"name": "主頁", "gid": "0"},
    {"name": "分頁1", "gid": "1779050796"},
    {"name": "分頁2", "gid": "462300633"},
]

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
# 工具函式
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
# 八大策略（全部回傳方向 + 價位）
# ==============================================================================
def analyze_ma_signals(hist, short_n, long_n):
    """1. 均線轉折"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < max(short_n, long_n) + 30:
        return None

    T_close, T_open, T_high, T_low, T_vol = closes[-1], opens[-1], highs[-1], lows[-1], vols[-1]
    Y_close, Y_high, Y_low, Y_vol = closes[-2], highs[-2], lows[-2], vols[-2]
    B_close = closes[-3]
    is_gap_up = T_open > Y_high
    is_gap_down = T_open < Y_low

    signals = []
    direction = None
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
            gap = "跳空" if is_gap_up else ""
            signals.append(f"🔥{gap}突破均線{label_str}")
            direction = "買進"
        if Y_close >= Y_ma and T_close < T_ma:
            gap = "跳空" if is_gap_down else ""
            signals.append(f"📉{gap}跌破均線{label_str}")
            direction = "賣出／減碼"
        if (B_close < B_ma and Y_close > Y_ma) and (T_low > T_ma) and (T_close > Y_close):
            gap = "跳空" if is_gap_up else ""
            signals.append(f"🔥{gap}2日法則{label_str}")
            direction = "買進"
        if (Y_close < Y_ma and B_close >= B_ma) and T_close > T_ma:
            gap = "跳空" if is_gap_up else ""
            signals.append(f"🔄{gap}反2日{label_str}")
            direction = "買進"

    if not signals or direction is None:
        return None

    vol_tag = ""
    if Y_vol and T_vol > Y_vol * 1.5:
        vol_tag = "🔴爆量"
    elif Y_vol and T_vol > Y_vol * 1.2:
        vol_tag = "🔴量增"

    # 價位建議
    entry = round(T_close * 1.005, 2) if direction == "買進" else "-"
    stop = round(min(T_low, T_close * 0.97), 2) if direction == "買進" else round(T_close * 1.03, 2)
    target = round(T_close * 1.06, 2) if direction == "買進" else round(T_close * 0.94, 2)

    return {
        "price": T_close,
        "signal": " + ".join(signals),
        "vol": vol_tag,
        "strategy": "均線轉折",
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "how": "突破／2日法則／反2日 → 隔日開盤附近買，停損設在均線下方或當日低點；跌破 → 減碼或出場"
    }


def analyze_weekly_bull(hist):
    """2. 周線多頭（恢復較完整邏輯）"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None

    ma5 = calc_ma_list(closes, 5)
    ma10 = calc_ma_list(closes, 10)
    ma20 = calc_ma_list(closes, 20)
    if None in (ma5[-1], ma10[-1], ma20[-1], ma5[-2], ma10[-2], ma20[-2]):
        return None

    # 條件A：均線多頭排列 + 站上MA5
    bull_align = ma5[-1] > ma10[-1] > ma20[-1] and closes[-1] > ma5[-1]

    # 條件B：均線黏合後打開（前幾天很近，今天突然分開）
    sticky = False
    if ma5[-3] is not None and ma10[-3] is not None and ma20[-3] is not None:
        prev_spread = max(ma5[-3], ma10[-3], ma20[-3]) - min(ma5[-3], ma10[-3], ma20[-3])
        curr_spread = max(ma5[-1], ma10[-1], ma20[-1]) - min(ma5[-1], ma10[-1], ma20[-1])
        if prev_spread / ma20[-3] < 0.025 and curr_spread > prev_spread * 1.5 and ma5[-1] > ma10[-1]:
            sticky = True

    # 條件C：爆量（今天量 > 近5日均量 1.5倍）
    avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    volume_surge = avg5_vol > 0 and vols[-1] >= avg5_vol * 1.5

    # 條件D：K線型態
    d0, d1, d2 = closes[-1], closes[-2], closes[-3]
    o0, o1, o2 = opens[-1], opens[-2], opens[-3]
    k_name = ""
    if (d0 > o0 and d1 > o1 and d2 > o2 and d0 > d1 > d2 and
            o1 >= min(o2, d2) and o1 <= max(o2, d2) and
            o0 >= min(o1, d1) and o0 <= max(o1, d1)):
        k_name = "三白兵"
    elif (d2 < o2 and abs(d1 - o1) <= (highs[-2] - lows[-2]) * 0.35 and
          d0 > o0 and d0 >= (d2 + o2) / 2):
        k_name = "晨星"

    # 必須滿足多頭排列，再搭配其他加分
    if not bull_align:
        return None

    signal_parts = ["均線多頭排列"]
    if sticky:
        signal_parts.append("均線黏合後打開")
    if volume_surge:
        signal_parts.append("爆量")
    if k_name:
        signal_parts.append(k_name)

    # 至少要有多頭排列，有黏合或爆量或K線更佳
    score = 1 + (1 if sticky else 0) + (1 if volume_surge else 0) + (1 if k_name else 0)
    if score < 1:
        return None

    entry = round(closes[-1] * 1.005, 2)
    stop = round(min(lows[-1], closes[-1] * 0.97, ma10[-1] * 0.99), 2)
    target = round(closes[-1] * 1.08, 2)

    return {
        "price": closes[-1],
        "signal": " + ".join(signal_parts),
        "vol": "🔴爆量" if volume_surge else ("量增" if vols[-1] > vols[-2] else ""),
        "strategy": "周線多頭",
        "direction": "買進",
        "entry": entry,
        "stop": stop,
        "target": target,
        "how": "多頭排列成立後，回檔不破MA10再買；或突破近期高點追。停損設在MA10下方或當日低點。"
    }


def analyze_jinbaoyin(hist):
    """3. 金包銀"""
    closes, highs, lows, vols = hist["closes"], hist["highs"], hist["lows"], hist["vols"]
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

    has_long_down = (ma120[-1] is not None and ma120[-1] < ma120[-7]) or \
                    (ma240[-1] is not None and ma240[-1] < ma240[-7])
    if not has_long_down:
        return None
    if ma60[-1] - ma60[-7] < -0.008 * ma60[-1]:
        return None
    if not (ma5[-1] > ma60[-1] and ma10[-1] > ma60[-1] and ma20[-1] > ma60[-1] and closes[-1] > ma60[-1]):
        return None
    recent_low = min(lows[-21:-1])
    if lows[-1] < recent_low * 0.995:
        return None

    entry = round(closes[-1] * 1.005, 2)
    stop = round(min(ma60[-1] * 0.98, closes[-1] * 0.96), 2)
    target = round(closes[-1] * 1.10, 2)

    return {
        "price": closes[-1],
        "signal": "金包銀：長天期下壓 + 生命線支撐",
        "vol": "",
        "strategy": "金包銀",
        "direction": "買進（中期反彈）",
        "entry": entry,
        "stop": stop,
        "target": target,
        "how": "靠近生命線（MA60）附近承接。停損設在生命線下方約2%。目標可看前高或10%左右。"
    }


def analyze_rsi_oversold(hist):
    """4. RSI 抄底"""
    closes, lows, vols = hist["closes"], hist["lows"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    rsi = calc_rsi(closes, CONFIG["RSI_PERIOD"])
    if rsi[-1] is None or rsi[-2] is None:
        return None
    if rsi[-1] > CONFIG["RSI_OVERSOLD"] or rsi[-2] > CONFIG["RSI_OVERSOLD"]:
        return None
    if rsi[-1] <= rsi[-2]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None or closes[-1] < ma20[-1]:
        return None

    entry = round(closes[-1] * 1.005, 2)
    stop = round(min(lows[-1] * 0.98, closes[-1] * 0.97), 2)
    target = round(closes[-1] * 1.06, 2)

    return {
        "price": closes[-1],
        "signal": f"RSI抄底：RSI={rsi[-1]:.1f}≤{CONFIG['RSI_OVERSOLD']}且向上",
        "vol": "",
        "strategy": "RSI抄底",
        "direction": "買進（短線反彈）",
        "entry": entry,
        "stop": stop,
        "target": target,
        "how": "出現訊號後，隔日低點不破再買。停損設在訊號當日低點下方2～3%。反彈到前高或5～6%可考慮減碼。"
    }


def analyze_fake_break(hist):
    """5. 假突破／破底翻"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < 800000:
        return None

    lookback = 20
    prev_low = min(lows[-lookback-3:-3])
    broken = any(l < prev_low * 0.995 for l in lows[-3:])
    if broken and closes[-1] > prev_low:
        entry = round(closes[-1] * 1.005, 2)
        stop = round(prev_low * 0.985, 2)
        target = round(closes[-1] * 1.07, 2)
        return {
            "price": closes[-1],
            "signal": f"破底翻：跌破前低{prev_low:.2f}後站回",
            "vol": "",
            "strategy": "假突破破底翻",
            "direction": "買進",
            "entry": entry,
            "stop": stop,
            "target": target,
            "how": "站回前低後買進。停損設在前低下方約1.5%。目標看前高或7%左右。"
        }

    prev_high = max(highs[-21:-1])
    if closes[-1] > prev_high:
        avg_vol = sum(vols[-21:-1]) / 20
        body = abs(closes[-1] - opens[-1])
        range_ = highs[-1] - lows[-1]
        if avg_vol > 0 and vols[-1] >= avg_vol * 1.5 and range_ > 0 and body / range_ >= 0.55:
            entry = round(closes[-1] * 1.005, 2)
            stop = round(min(lows[-1], prev_high * 0.99), 2)
            target = round(closes[-1] * 1.08, 2)
            return {
                "price": closes[-1],
                "signal": f"真突破：收盤突破前高{prev_high:.2f}+放量",
                "vol": "🔴爆量",
                "strategy": "假突破破底翻",
                "direction": "買進",
                "entry": entry,
                "stop": stop,
                "target": target,
                "how": "突破當日或次日回測不破前高再買。停損設在前高下方或當日低點。"
            }
    return None


def analyze_overnight(hist):
    """6. 一夜持股"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 30 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None

    change = (closes[-1] - closes[-2]) / closes[-2]
    if not (CONFIG["OVERNIGHT_MIN_CHG"] <= change <= CONFIG["OVERNIGHT_MAX_CHG"]):
        return None

    has_limit = False
    for i in range(max(-20, -n+1), 0):
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
    if closes[-1] <= opens[-1]:
        return None
    rng = highs[-1] - lows[-1]
    if rng > 0 and (highs[-1] - closes[-1]) / rng > 0.30:
        return None

    entry_min = round(closes[-1] * 0.995, 2)
    entry_max = round(closes[-1] * 1.010, 2)
    stop = round(closes[-1] * 0.97, 2)
    target = round(closes[-1] * 1.04, 2)

    return {
        "price": closes[-1],
        "signal": f"一夜持股：漲幅{change*100:.1f}%｜隔日開盤{entry_min}~{entry_max}才進場",
        "vol": "🔴量增",
        "strategy": "一夜持股",
        "direction": "買進（只抱一天）",
        "entry": f"{entry_min}~{entry_max}",
        "stop": stop,
        "target": target,
        "how": "隔日開盤落在昨日收盤99.5%～101%才買。無論盈虧，當日收盤前一定平倉。停損約3%。"
    }


def analyze_rsi_divergence(hist):
    """7. RSI 背離"""
    closes, lows, highs, vols = hist["closes"], hist["lows"], hist["highs"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None

    rsi = calc_rsi(closes, CONFIG["RSI_PERIOD"])
    lookback = CONFIG["RSI_DIVERGENCE_LOOKBACK"]
    if any(x is None for x in rsi[-lookback:]):
        return None

    # 底背離
    recent_low_idx = n - 1 - int(np.argmin(lows[-10:]))
    prev_start = max(0, recent_low_idx - 25)
    prev_window = lows[prev_start:recent_low_idx - 3]
    if len(prev_window) >= 5:
        prev_low_idx = prev_start + int(np.argmin(prev_window))
        if (closes[recent_low_idx] < closes[prev_low_idx] and
                rsi[recent_low_idx] is not None and rsi[prev_low_idx] is not None and
                rsi[recent_low_idx] > rsi[prev_low_idx] and rsi[recent_low_idx] < 40):
            entry = round(closes[-1] * 1.005, 2)
            stop = round(min(lows[recent_low_idx] * 0.98, closes[-1] * 0.96), 2)
            target = round(closes[-1] * 1.07, 2)
            return {
                "price": closes[-1],
                "signal": f"底背離：價格新低但RSI抬高（RSI={rsi[-1]:.1f}）",
                "vol": "",
                "strategy": "RSI背離",
                "direction": "買進（觀察反轉）",
                "entry": entry,
                "stop": stop,
                "target": target,
                "how": "底背離出現後，等價格站上近期小高點或均線再買。停損設在背離低點下方。不保證立刻反轉。"
            }

    # 頂背離
    recent_high_idx = n - 1 - int(np.argmax(highs[-10:]))
    prev_h_start = max(0, recent_high_idx - 25)
    prev_h_window = highs[prev_h_start:recent_high_idx - 3]
    if len(prev_h_window) >= 5:
        prev_high_idx = prev_h_start + int(np.argmax(prev_h_window))
        if (closes[recent_high_idx] > closes[prev_high_idx] and
                rsi[recent_high_idx] is not None and rsi[prev_high_idx] is not None and
                rsi[recent_high_idx] < rsi[prev_high_idx] and rsi[recent_high_idx] > 60):
            return {
                "price": closes[-1],
                "signal": f"頂背離：價格新高但RSI降低（RSI={rsi[-1]:.1f}）",
                "vol": "",
                "strategy": "RSI背離",
                "direction": "賣出／減碼",
                "entry": "-",
                "stop": "-",
                "target": round(closes[-1] * 0.95, 2),
                "how": "持有者考慮減碼或出場。空手者不宜追高。強勢股可能多次頂背離仍續漲，需搭配其他訊號。"
            }
    return None


def analyze_rsi_passivation(hist):
    """8. RSI 鈍化"""
    closes, lows, vols = hist["closes"], hist["lows"], hist["vols"]
    n = len(closes)
    if n < 40 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None

    rsi = calc_rsi(closes, CONFIG["RSI_PERIOD"])
    days = CONFIG["RSI_PASSIVATION_DAYS"]
    level = CONFIG["RSI_PASSIVATION_LEVEL"]
    if any(r is None or r < level for r in rsi[-days:]):
        return None

    ma5 = calc_ma_list(closes, 5)
    if ma5[-1] is None or ma5[-2] is None:
        return None
    if closes[-1] <= ma5[-1] or ma5[-1] <= ma5[-2]:
        return None

    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is not None and closes[-1] < ma20[-1]:
        return None

    entry = round(closes[-1] * 1.005, 2)
    stop = round(min(ma5[-1] * 0.99, closes[-1] * 0.97), 2)
    target = round(closes[-1] * 1.06, 2)

    return {
        "price": closes[-1],
        "signal": f"RSI鈍化：連續{days}日RSI≥{level}（目前{rsi[-1]:.1f}）+站上五日線",
        "vol": "量能" if vols[-1] > vols[-2] else "",
        "strategy": "RSI鈍化",
        "direction": "買進（順勢）",
        "entry": entry,
        "stop": stop,
        "target": target,
        "how": "鈍化成立且站上五日線後買。跌破五日線或RSI跌破70就出場。停損約3%。趨勢結束時回撤快，務必執行停損。"
    }


# ==============================================================================
# 主掃描
# ==============================================================================
def run_full_scan():
    results = {s: [] for s in [
        "均線轉折", "周線多頭", "金包銀", "RSI抄底",
        "假突破破底翻", "一夜持股", "RSI背離", "RSI鈍化"
    ]}

    # 策略1
    ma_stocks = load_ma_stocks()
    def process_ma(item):
        hist = get_yahoo_history(item["sid"])
        if hist is None:
            return None
        r = analyze_ma_signals(hist, item["short_n"], item["long_n"])
        if r:
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
            return r
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as executor:
        for f in concurrent.futures.as_completed([executor.submit(process_ma, i) for i in ma_stocks]):
            try:
                res = f.result()
                if res:
                    results["均線轉折"].append(res)
            except Exception:
                pass

    # 策略2～8
    main_stocks = load_main_stocks()
    def process_other(item):
        hist = get_yahoo_history(item["sid"])
        if hist is None:
            return []
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
        return local

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as executor:
        for f in concurrent.futures.as_completed([executor.submit(process_other, i) for i in main_stocks]):
            try:
                for key, res in f.result():
                    results[key].append(res)
            except Exception:
                pass
    return results


# ==============================================================================
# 圖表與顯示
# ==============================================================================
def make_chart(hist, title):
    closes = hist["closes"][-60:]
    opens = hist["opens"][-60:]
    highs = hist["highs"][-60:]
    lows = hist["lows"][-60:]
    vols = hist["vols"][-60:]
    x = list(range(len(closes)))

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(
        x=x, open=opens, high=highs, low=lows, close=closes,
        increasing_line_color="#FF3333", increasing_fillcolor="#FF3333",
        decreasing_line_color="#00A600", decreasing_fillcolor="#00A600",
        line_width=1.5, name="K線"
    ), row=1, col=1)
    ma5 = calc_ma_list(hist["closes"], 5)[-60:]
    ma20 = calc_ma_list(hist["closes"], 20)[-60:]
    fig.add_trace(go.Scatter(x=x, y=ma5, mode="lines", name="MA5",
                             line=dict(color="#FFA500", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=ma20, mode="lines", name="MA20",
                             line=dict(color="#1E90FF", width=1.5)), row=1, col=1)
    colors = ['#FF3333' if closes[i] >= opens[i] else '#00A600' for i in range(len(closes))]
    fig.add_trace(go.Bar(x=x, y=vols, marker_color=colors, name="成交量"), row=2, col=1)
    fig.update_layout(title=title, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=40, b=10), height=400, showlegend=True,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
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
        "方向": d.get("direction", ""),
        "訊號": d["signal"],
        "建議買進價": d.get("entry", "-"),
        "建議停損價": d.get("stop", "-"),
        "建議目標價": d.get("target", "-"),
        "量能": d.get("vol", "")
    } for d in data_list])
    st.dataframe(df, use_container_width=True, hide_index=True)

    for idx, item in enumerate(data_list):
        how = item.get("how", "")
        with st.expander(f"🔍 {item['sid']} {item['name']}｜{item.get('direction','')}｜{item['signal']}", expanded=False):
            st.markdown(f"""
**操作說明（普通人版）**  
{how}

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
st.title("🐯 台股八策略監控系統 v3")
st.caption(f"最後更新：{time.strftime('%Y-%m-%d %H:%M:%S')}｜含方向 + 買進／停損／目標價")

st.warning("⚠️ 風險提醒：所有策略歷史表現未經驗證，實盤有虧損可能。建議買進價、停損價僅供參考，請依自身風險承受度調整。")

col1, col2 = st.columns(2)
with col1:
    if st.button("🔄 同步並重新掃描", use_container_width=True):
        st.cache_data.clear()
        with st.spinner("掃描中（約20～50秒）..."):
            st.session_state["scan_results"] = run_full_scan()
            st.session_state["scan_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        st.rerun()
with col2:
    if st.button("🚀 強制刷新", type="primary", use_container_width=True):
        st.cache_data.clear()
        SYMBOL_CACHE.clear()
        with st.spinner("強制刷新中..."):
            st.session_state["scan_results"] = run_full_scan()
            st.session_state["scan_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        st.rerun()

if "scan_results" not in st.session_state:
    with st.spinner("首次載入..."):
        st.session_state["scan_results"] = run_full_scan()
        st.session_state["scan_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

results = st.session_state["scan_results"]

tabs = st.tabs([
    "🔥 均線轉折", "⚔️ 周線多頭", "🌟 金包銀", "📉 RSI抄底",
    "🔄 假突破破底翻", "🌙 一夜持股", "📊 RSI背離", "📈 RSI鈍化"
])

with tabs[0]:
    st.caption("資料來源：金虎南 Sheet")
    render_strategy_tab(results["均線轉折"], "均線轉折")
with tabs[1]:
    st.caption("已恢復：多頭排列 + 均線黏合後打開 + 爆量 + K線")
    render_strategy_tab(results["周線多頭"], "周線多頭")
with tabs[2]:
    render_strategy_tab(results["金包銀"], "金包銀")
with tabs[3]:
    render_strategy_tab(results["RSI抄底"], "RSI抄底")
with tabs[4]:
    render_strategy_tab(results["假突破破底翻"], "假突破破底翻")
with tabs[5]:
    render_strategy_tab(results["一夜持股"], "一夜持股")
with tabs[6]:
    render_strategy_tab(results["RSI背離"], "RSI背離")
with tabs[7]:
    st.markdown("**RSI鈍化**：連續5日RSI≥70 + 站上五日線 → 順勢買進，跌破五日線或RSI<70出場")
    render_strategy_tab(results["RSI鈍化"], "RSI鈍化")

st.markdown("---")
st.caption("本系統僅供學習監控。投資有風險，請獨立判斷並自負盈虧。")
