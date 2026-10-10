"""
================================================================================
台股九策略監控系統（Streamlit 完整版 v7）
================================================================================
【v7】
1. 第9策略：KD(9)+RSI 共振（買／賣分開用半年掃描裡樣本較可用的參數）
2. 內含半年參數比較表（RSI 6/10/12/14/24 × 20/80與30/70 × 當天/前後1天/前後2天）
3. 勝率只顯示百分比，寫在訊號文字裡
4. 買進／停損／目標合併一格；量能改顯示成交張數

風險：勝率為樣本觀察，未扣成本，不構成投資建議。
KD 週期影片沒講死，程式固定用常見的 9。
共振窗口：影片沒明確說同天或前後幾天，三種都測過。
半年掃描股票＝主要清單前 40 檔（多為傳產），不是全市場。
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

st.set_page_config(layout="wide", page_title="台股九策略 v7")

# 手機友善：字級16、粗體、換行
st.markdown("""
<style>
.block-container { padding-top: 1rem; padding-bottom: 1rem; }
table { width: 100% !important; font-size: 16px !important; font-weight: bold !important; }
th { background-color: #f0f2f6 !important; font-size: 16px !important; font-weight: bold !important;
     white-space: normal !important; word-wrap: break-word !important; }
td { font-size: 16px !important; font-weight: bold !important;
     white-space: normal !important; word-wrap: break-word !important;
     max-width: 280px !important; }
.buy-text { color: #E53935 !important; font-weight: bold; font-size: 16px; }
.sell-text { color: #43A047 !important; font-weight: bold; font-size: 16px; }
.stMarkdown, .stCaption, p, li { font-size: 16px !important; }
div[data-testid="stDataFrame"] { font-size: 16px !important; font-weight: bold !important; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 歷史勝率（寫死，來源：過去約3個月隔日收盤回測）
# key = 訊號文字關鍵字或部分匹配；顯示在策略旁
# ==============================================================================
HARDCODED_WINRATES = {
    # 均線轉折
    "跌破均線(短20)": {"n": 4897, "rate": 45.9, "avg": 0.03},
    "突破均線(短20)": {"n": 4812, "rate": 38.9, "avg": -0.08},
    "跌破均線(長60)": {"n": 2752, "rate": 49.9, "avg": 0.31},
    "突破均線(長60)": {"n": 2583, "rate": 39.1, "avg": -0.08},
    "2日法則(短20)": {"n": 1336, "rate": 40.0, "avg": -0.13},
    "反2日(短20)": {"n": 1306, "rate": 37.4, "avg": -0.14},
    "2日法則(長60)": {"n": 739, "rate": 41.8, "avg": -0.05},
    "反2日(長60)": {"n": 651, "rate": 39.3, "avg": -0.12},
    # 周線多頭
    "均線多頭排列": {"n": 3318, "rate": 42.6, "avg": -0.08},
    "均線多頭排列 + 爆量": {"n": 1502, "rate": 40.6, "avg": -0.19},
    "均線多頭排列 + 均線黏合後打開": {"n": 953, "rate": 41.6, "avg": -0.07},
    "均線多頭排列 + 均線黏合後打開 + 爆量": {"n": 730, "rate": 43.2, "avg": -0.08},
    "均線多頭排列 + 晨星": {"n": 310, "rate": 42.6, "avg": -0.25},
    "均線多頭排列 + 爆量 + 晨星": {"n": 144, "rate": 39.6, "avg": -0.12},
    "均線多頭排列 + 三白兵": {"n": 86, "rate": 48.8, "avg": 0.19},
    "均線多頭排列 + 均線黏合後打開 + 爆量 + 晨星": {"n": 67, "rate": 43.3, "avg": 0.48},
    "均線多頭排列 + 爆量 + 三白兵": {"n": 46, "rate": 45.7, "avg": 0.40},
    "均線多頭排列 + 均線黏合後打開 + 晨星": {"n": 41, "rate": 46.3, "avg": 0.10},
    "均線多頭排列 + 均線黏合後打開 + 三白兵": {"n": 35, "rate": 42.9, "avg": 0.05},
    "均線多頭排列 + 均線黏合後打開 + 爆量 + 三白兵": {"n": 28, "rate": 42.9, "avg": -0.41},
    # 假突破
    "破底翻：跌破前低後站回": {"n": 1691, "rate": 48.2, "avg": 0.24},
    "真突破：突破前高+放量": {"n": 892, "rate": 42.7, "avg": -0.01},
    # RSI
    "頂背離：價格新高RSI降低": {"n": 1205, "rate": 54.4, "avg": 0.33},
    "底背離：價格新低RSI抬高": {"n": 776, "rate": 43.4, "avg": -0.27},
    "RSI鈍化：連續5日≥70+站上五日線": {"n": 390, "rate": 45.6, "avg": -0.32},
    # 一夜持股
    "一夜持股：漲3～5%+曾漲停+量增+多頭": {"n": 28, "rate": 28.6, "avg": -0.36},
}

# 策略層級摘要（取代表性）
STRATEGY_SUMMARY = {
    "均線轉折": "突破短約39%｜跌破短約46%｜跌破長約50%",
    "周線多頭": "多頭排列約43%｜+三白兵約49%｜+爆量約41%",
    "金包銀": "本次回測樣本不足未列出",
    "RSI抄底": "本次回測樣本不足未列出",
    "假突破破底翻": "破底翻約48%｜真突破約43%",
    "一夜持股": "約29%（樣本僅28，極不穩）",
    "RSI背離": "頂背離約54%｜底背離約43%",
    "RSI鈍化": "約46%",
    "KD+RSI共振": "買進用RSI12、30/70、當天：48.8%；賣出用RSI14、30/70、前後1天：66.7%（賣出樣本少）",
}


def lookup_winrate(signal_text: str) -> str:
    """依訊號文字找最接近的寫死勝率"""
    if not signal_text:
        return ""
    # 精確
    if signal_text in HARDCODED_WINRATES:
        w = HARDCODED_WINRATES[signal_text]
        return f"{w['rate']}%"
    # 部分匹配（取最長 key）
    best = None
    best_len = 0
    for k, w in HARDCODED_WINRATES.items():
        if k in signal_text or signal_text in k:
            if len(k) > best_len:
                best, best_len = w, len(k)
    # 關鍵字
    if best is None:
        checks = [
            ("頂背離", "頂背離：價格新高RSI降低"),
            ("底背離", "底背離：價格新低RSI抬高"),
            ("破底翻", "破底翻：跌破前低後站回"),
            ("真突破", "真突破：突破前高+放量"),
            ("RSI鈍化", "RSI鈍化：連續5日≥70+站上五日線"),
            ("一夜持股", "一夜持股：漲3～5%+曾漲停+量增+多頭"),
            ("三白兵", "均線多頭排列 + 三白兵"),
            ("晨星", "均線多頭排列 + 晨星"),
            ("黏合", "均線多頭排列 + 均線黏合後打開"),
            ("爆量", "均線多頭排列 + 爆量"),
            ("多頭排列", "均線多頭排列"),
            ("跌破均線(短", "跌破均線(短20)"),
            ("突破均線(短", "突破均線(短20)"),
            ("跌破均線(長", "跌破均線(長60)"),
            ("突破均線(長", "突破均線(長60)"),
            ("2日法則(短", "2日法則(短20)"),
            ("反2日(短", "反2日(短20)"),
            ("2日法則(長", "2日法則(長60)"),
            ("反2日(長", "反2日(長60)"),
        ]
        for tip, key in checks:
            if tip in signal_text and key in HARDCODED_WINRATES:
                best = HARDCODED_WINRATES[key]
                break
    if best:
        return f"{best['rate']}%"
    return "—"


# ==============================================================================
# Sheet
# ==============================================================================
MAIN_SHEET = {
    "base": "https://docs.google.com/spreadsheets/d/13Mv-7uaFyR1KcxNRVrhxCGAAntElKprB7ZeWWBxS3n0",
    "gid": "0",
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
# 八大策略
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
    sig = " + ".join(signals)
    return {
        "price": T_close, "signal": sig, "vol": vol_tag,
        "strategy": "均線轉折", "direction": direction,
        "entry": entry, "stop": stop, "target": target,
        "how": "突破類→隔日開盤附近買，停損均線下；跌破→減碼或出場",
        "side": "long" if direction == "買進" else "short",
        "winrate": lookup_winrate(sig),
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
    sig = " + ".join(parts)
    return {
        "price": closes[-1], "signal": sig,
        "vol": "🔴爆量" if volume_surge else ("量增" if vols[-1] > vols[-2] else ""),
        "strategy": "周線多頭", "direction": "買進",
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], closes[-1] * 0.97, ma10[-1] * 0.99), 2),
        "target": round(closes[-1] * 1.08, 2),
        "how": "回檔不破MA10再買；停損MA10下",
        "side": "long",
        "winrate": lookup_winrate(sig),
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
    sig = "金包銀：長天期下壓+生命線支撐"
    return {
        "price": closes[-1], "signal": sig, "vol": "",
        "strategy": "金包銀", "direction": "買進（中期反彈）",
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(ma60[-1] * 0.98, closes[-1] * 0.96), 2),
        "target": round(closes[-1] * 1.10, 2),
        "how": "靠近MA60承接，停損生命線下約2%",
        "side": "long",
        "winrate": lookup_winrate(sig),
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
    sig = f"RSI抄底：RSI={rsi[-1]:.1f}≤{CONFIG['RSI_OVERSOLD']}且向上"
    return {
        "price": closes[-1], "signal": sig, "vol": "",
        "strategy": "RSI抄底", "direction": "買進（短線反彈）",
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1] * 0.98, closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.06, 2),
        "how": "隔日低點不破再買，停損當日低點下2～3%",
        "side": "long",
        "winrate": lookup_winrate(sig),
    }


def analyze_fake_break(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < 800000:
        return None
    prev_low = min(lows[-23:-3])
    if any(l < prev_low * 0.995 for l in lows[-3:]) and closes[-1] > prev_low:
        sig = f"破底翻：跌破前低{prev_low:.2f}後站回"
        return {
            "price": closes[-1], "signal": sig, "vol": "",
            "strategy": "假突破破底翻", "direction": "買進",
            "entry": round(closes[-1] * 1.005, 2), "stop": round(prev_low * 0.985, 2),
            "target": round(closes[-1] * 1.07, 2),
            "how": "站回前低後買，停損前低下約1.5%", "side": "long",
            "winrate": lookup_winrate("破底翻：跌破前低後站回"),
        }
    prev_high = max(highs[-21:-1])
    if closes[-1] > prev_high:
        avg_vol = sum(vols[-21:-1]) / 20
        body = abs(closes[-1] - opens[-1])
        rng = highs[-1] - lows[-1]
        if avg_vol > 0 and vols[-1] >= avg_vol * 1.5 and rng > 0 and body / rng >= 0.55:
            sig = f"真突破：突破前高{prev_high:.2f}+放量"
            return {
                "price": closes[-1], "signal": sig, "vol": "🔴爆量",
                "strategy": "假突破破底翻", "direction": "買進",
                "entry": round(closes[-1] * 1.005, 2),
                "stop": round(min(lows[-1], prev_high * 0.99), 2),
                "target": round(closes[-1] * 1.08, 2),
                "how": "回測不破前高再買", "side": "long",
                "winrate": lookup_winrate("真突破：突破前高+放量"),
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
    sig = f"一夜持股：漲幅{change*100:.1f}%｜隔日開盤{entry_min}~{entry_max}"
    return {
        "price": closes[-1], "signal": sig, "vol": "🔴量增",
        "strategy": "一夜持股", "direction": "買進（只抱一天）",
        "entry": f"{entry_min}~{entry_max}", "stop": round(closes[-1] * 0.97, 2),
        "target": round(closes[-1] * 1.04, 2),
        "how": "隔日開盤在區間才買，當日收盤前必平倉", "side": "long",
        "winrate": lookup_winrate("一夜持股：漲3～5%+曾漲停+量增+多頭"),
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
                "how": "等站上近期小高點再買，停損背離低點下", "side": "long",
                "winrate": lookup_winrate("底背離：價格新低RSI抬高"),
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
                "how": "持有者減碼；空手不追高", "side": "short",
                "winrate": lookup_winrate("頂背離：價格新高RSI降低"),
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
    sig = f"RSI鈍化：連續{days}日≥{level}（{rsi[-1]:.1f}）+站上五日線"
    return {
        "price": closes[-1], "signal": sig, "vol": "",
        "strategy": "RSI鈍化", "direction": "買進（順勢）",
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(ma5[-1] * 0.99, closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.06, 2),
        "how": "跌破五日線或RSI<70出場，停損約3%", "side": "long",
        "winrate": lookup_winrate("RSI鈍化：連續5日≥70+站上五日線"),
    }


def calc_kd(highs, lows, closes, n=9):
    N = len(closes)
    K = [None] * N
    D = [None] * N
    k = d = 50.0
    for i in range(N):
        if i + 1 < n:
            continue
        hh = max(highs[i - n + 1:i + 1])
        ll = min(lows[i - n + 1:i + 1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        K[i], D[i] = k, d
    return K, D


def _rsi_flags(rsi, low_th, high_th):
    n = len(rsi)
    rb = [False] * n
    rs = [False] * n
    for i in range(1, n):
        if rsi[i] is None or rsi[i - 1] is None:
            continue
        if (rsi[i - 1] < low_th <= rsi[i]) or (rsi[i - 1] < low_th and rsi[i] > rsi[i - 1]):
            rb[i] = True
        if (rsi[i - 1] > high_th >= rsi[i]) or (rsi[i - 1] > high_th and rsi[i] < rsi[i - 1]):
            rs[i] = True
    return rb, rs


def _kd_flags(K, D, low_th, high_th):
    n = len(K)
    kb = [False] * n
    ks = [False] * n
    for i in range(1, n):
        if None in (K[i], K[i - 1], D[i], D[i - 1]):
            continue
        if K[i - 1] <= D[i - 1] and K[i] > D[i] and K[i] <= low_th and D[i] <= low_th:
            kb[i] = True
        if K[i - 1] >= D[i - 1] and K[i] < D[i] and K[i] >= high_th and D[i] >= high_th:
            ks[i] = True
    return kb, ks


def _fresh_resonance(a, b, i, w):
    lo = max(0, i - w)
    if not any(a[lo:i + 1]) or not any(b[lo:i + 1]):
        return False
    if i == 0:
        return True
    plo = max(0, i - 1 - w)
    return not (any(a[plo:i]) and any(b[plo:i]))


def analyze_kd_rsi(hist):
    """第9策略。買：RSI12、門檻30、當天。賣：RSI14、門檻70、前後1天。KD=9。"""
    closes, highs, lows, vols = hist["closes"], hist["highs"], hist["lows"], hist["vols"]
    n = len(closes)
    if n < 40 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    K, D = calc_kd(highs, lows, closes, 9)
    i = n - 1
    rsi12 = calc_rsi(closes, 12)
    rsi14 = calc_rsi(closes, 14)
    rb, _ = _rsi_flags(rsi12, 30, 70)
    kb, _ = _kd_flags(K, D, 30, 70)
    _, rs = _rsi_flags(rsi14, 30, 70)
    _, ks = _kd_flags(K, D, 30, 70)
    buy = _fresh_resonance(rb, kb, i, 0)
    sell = _fresh_resonance(rs, ks, i, 1)
    if not buy and not sell:
        return None
    px = closes[-1]
    if buy and not sell:
        direction, side = "買進", "long"
        sig = "KD+RSI共振買：RSI12上穿或低檔翻揚且K上穿D（皆≤30，當天）"
        wr = "48.8%"
        entry, stop, target = round(px * 1.005, 2), round(px * 0.97, 2), round(px * 1.06, 2)
        how = "低檔共振隔日觀察。停損約3%。半年樣本43筆，只代表這批傳產股。"
    elif sell and not buy:
        direction, side = "賣出／減碼", "short"
        sig = "KD+RSI共振賣：RSI14下穿或高檔轉弱且K下穿D（皆≥70，前後1天）"
        wr = "66.7%"
        entry, stop, target = "-", round(px * 1.03, 2), round(px * 0.95, 2)
        how = "高檔共振考慮減碼。此組樣本只有18筆，勝率容易高估。"
    else:
        direction, side = "衝突（買賣都出現）", "long"
        sig = "KD+RSI同日買賣共振衝突，先不要下單"
        wr = "—"
        entry, stop, target = "-", "-", "-"
        how = "買與賣條件同時成立，訊號互相打架。"
    return {
        "price": px, "signal": sig, "vol": "",
        "strategy": "KD+RSI共振", "direction": direction,
        "entry": entry, "stop": stop, "target": target,
        "how": how, "side": side, "winrate": wr,
    }


def run_full_scan():
    results = {s: [] for s in [
        "均線轉折", "周線多頭", "金包銀", "RSI抄底",
        "假突破破底翻", "一夜持股", "RSI背離", "RSI鈍化", "KD+RSI共振"
    ]}
    ma_stocks = load_ma_stocks()

    def process_ma(item):
        hist = get_yahoo_history(item["sid"])
        if hist is None:
            return None
        r = analyze_ma_signals(hist, item["short_n"], item["long_n"])
        if r:
            r["lots"] = int(hist["vols"][-1] // 1000)
            r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
            return r
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as ex:
        for f in concurrent.futures.as_completed([ex.submit(process_ma, i) for i in ma_stocks]):
            try:
                res = f.result()
                if res:
                    results["均線轉折"].append(res)
            except Exception:
                pass

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
            (analyze_kd_rsi, "KD+RSI共振"),
        ]:
            r = func(hist)
            if r:
                r["lots"] = int(hist["vols"][-1] // 1000)
                r.update({"sid": item["sid"], "name": item["name"], "sheet": item["sheet"], "hist": hist})
                local.append((key, r))
        return local

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as ex:
        for f in concurrent.futures.as_completed([ex.submit(process_other, i) for i in main_stocks]):
            try:
                for key, res in f.result():
                    results[key].append(res)
            except Exception:
                pass
    return results


def build_conflict_table(results):
    by_sid = {}
    for strategy, items in results.items():
        for d in items:
            by_sid.setdefault(d["sid"], []).append(d)
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
            "衝突": "⚠️是" if conflict else "否",
            "方向": "｜".join(f"{x['strategy']}:{x.get('direction','')}" for x in lst),
            "歷史勝率": "｜".join(f"{x['strategy']}:{x.get('winrate','—')}" for x in lst),
            "現價": lst[0]["price"],
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["衝突", "策略數"], ascending=[False, False])


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
    fig.add_trace(go.Bar(x=x, y=vols, marker_color=colors, name="量"), row=2, col=1)
    fig.update_layout(title=title, xaxis_rangeslider_visible=False,
                      margin=dict(l=8, r=8, t=36, b=8), height=360, showlegend=True,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                      font=dict(size=14))
    fig.update_xaxes(showticklabels=False, showgrid=False)
    return fig


def direction_html(direction: str) -> str:
    d = direction or ""
    if "賣" in d or "減碼" in d:
        return f'<span class="sell-text">{d}</span>'
    if "買" in d:
        return f'<span class="buy-text">{d}</span>'
    return d


def render_strategy_tab(data_list, strategy_name):
    summary = STRATEGY_SUMMARY.get(strategy_name, "")
    if summary:
        st.markdown(f"**歷史隔日勝率參考：** {summary}")
        st.caption("※ 來自過去約3個月回測寫死數值，非即時重算；樣本少時不穩。")

    if not data_list:
        st.info(f"目前沒有符合【{strategy_name}】的個股。")
        return

    st.markdown(f"**共 {len(data_list)} 檔**")

    # 用 HTML 表格方便紅綠色 + 換行
    rows_html = []
    for d in data_list:
        dir_h = direction_html(d.get("direction", ""))
        wr = d.get("winrate") or "—"
        sig = d["signal"]
        if wr not in ("", "—") and "勝率" not in sig:
            sig = f"{sig}｜勝率{wr}"
        pxcell = f"買{d.get('entry', '-')} 停{d.get('stop', '-')} 目{d.get('target', '-')}"
        lots = d.get("lots", 0)
        rows_html.append(
            f"<tr>"
            f"<td>{d['sid']}</td>"
            f"<td>{d['name']}</td>"
            f"<td>{d['price']:.2f}</td>"
            f"<td>{dir_h}</td>"
            f"<td>{sig}</td>"
            f"<td>{lots}張</td>"
            f"<td>{pxcell}</td>"
            f"</tr>"
        )
    table = f"""
    <table style="width:100%; border-collapse:collapse; font-size:16px; font-weight:bold;">
    <thead>
    <tr style="background:#f0f2f6;">
      <th style="padding:8px; text-align:left;">代號</th>
      <th style="padding:8px; text-align:left;">名稱</th>
      <th style="padding:8px; text-align:left;">現價</th>
      <th style="padding:8px; text-align:left;">方向</th>
      <th style="padding:8px; text-align:left;">訊號</th>
      <th style="padding:8px; text-align:left;">量能</th>
      <th style="padding:8px; text-align:left;">買賣參考</th>
    </tr>
    </thead>
    <tbody>
    {''.join(rows_html)}
    </tbody>
    </table>
    """
    st.markdown(table, unsafe_allow_html=True)

    for idx, item in enumerate(data_list):
        dir_h = direction_html(item.get("direction", ""))
        with st.expander(f"{item['sid']} {item['name']}｜勝率 {item.get('winrate','—')}", expanded=False):
            st.markdown(f"**方向：** {dir_h}", unsafe_allow_html=True)
            st.markdown(f"**訊號：** {item['signal']}")
            st.markdown(f"**操作：** {item.get('how', '')}")
            st.markdown(
                f"現價 **{item['price']:.2f}**｜買進 **{item.get('entry','-')}**｜"
                f"停損 **{item.get('stop','-')}**｜目標 **{item.get('target','-')}**"
            )
            fig = make_chart(item["hist"], f"{item['sid']} {item['name']}")
            st.plotly_chart(fig, use_container_width=True, key=f"c_{strategy_name}_{idx}_{item['sid']}")


# ==============================================================================
# 主介面
# ==============================================================================
st.title("台股九策略 v7")
st.caption(f"{time.strftime('%Y-%m-%d %H:%M')}｜勝率寫在訊號｜量能為張數｜買賣停損目標同一格")

st.warning("勝率是隔日收盤樣本，未扣手續費與稅。KD+RSI 半年數字只掃主要清單前40檔，賣出高勝率樣本很少，不要當成保證。")

col1, col2 = st.columns(2)
with col1:
    do_scan = st.button("🔄 同步掃描", use_container_width=True)
with col2:
    if st.button("🚀 強制刷新", type="primary", use_container_width=True):
        st.cache_data.clear()
        SYMBOL_CACHE.clear()
        st.rerun()

if do_scan or "scan_results" not in st.session_state:
    with st.spinner("掃描中..."):
        st.session_state["scan_results"] = run_full_scan()
        st.session_state["scan_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if do_scan:
        st.success("掃描完成")

results = st.session_state.get("scan_results", {})

# 勝率速覽
with st.expander("📋 歷史勝率速覽（寫死數值）", expanded=False):
    wr_rows = [
        {"訊號": k, "樣本數": v["n"], "勝率%": v["rate"], "平均報酬%": v["avg"]}
        for k, v in HARDCODED_WINRATES.items()
    ]
    st.dataframe(pd.DataFrame(wr_rows), use_container_width=True, hide_index=True)

tabs = st.tabs([
    "KD參數比較",
    "衝突彙整",
    "均線轉折", "周線多頭", "金包銀", "RSI抄底",
    "假突破破底翻", "一夜持股", "RSI背離", "RSI鈍化", "KD+RSI"
])

KD_SWEEP = [
    ("6", "20/80", "當天", "買進", 26, 50.0),
    ("6", "20/80", "前後1天", "買進", 38, 47.4),
    ("6", "20/80", "前後2天", "買進", 41, 48.8),
    ("6", "30/70", "當天", "買進", 89, 40.4),
    ("6", "30/70", "前後1天", "買進", 125, 40.0),
    ("6", "30/70", "前後2天", "買進", 136, 42.6),
    ("10", "20/80", "當天", "買進", 12, 50.0),
    ("10", "20/80", "前後1天", "買進", 19, 36.8),
    ("10", "20/80", "前後2天", "買進", 21, 42.9),
    ("10", "30/70", "當天", "買進", 53, 43.4),
    ("10", "30/70", "前後1天", "買進", 79, 40.5),
    ("10", "30/70", "前後2天", "買進", 83, 41.0),
    ("12", "20/80", "當天", "買進", 7, 42.9),
    ("12", "20/80", "前後1天", "買進", 12, 41.7),
    ("12", "20/80", "前後2天", "買進", 13, 46.2),
    ("12", "30/70", "當天", "買進", 43, 48.8),
    ("12", "30/70", "前後1天", "買進", 63, 42.9),
    ("12", "30/70", "前後2天", "買進", 62, 43.5),
    ("14", "20/80", "當天", "買進", 4, 25.0),
    ("14", "20/80", "前後1天", "買進", 8, 37.5),
    ("14", "20/80", "前後2天", "買進", 9, 44.4),
    ("14", "30/70", "當天", "買進", 35, 42.9),
    ("14", "30/70", "前後1天", "買進", 51, 41.2),
    ("14", "30/70", "前後2天", "買進", 50, 40.0),
    ("24", "20/80", "當天", "買進", 0, None),
    ("24", "30/70", "當天", "買進", 12, 41.7),
    ("24", "30/70", "前後1天", "買進", 18, 38.9),
    ("24", "30/70", "前後2天", "買進", 19, 42.1),
    ("6", "20/80", "當天", "賣出", 6, 50.0),
    ("6", "30/70", "當天", "賣出", 33, 51.5),
    ("6", "30/70", "前後1天", "賣出", 50, 52.0),
    ("6", "30/70", "前後2天", "賣出", 53, 52.8),
    ("10", "20/80", "當天", "賣出", 4, 50.0),
    ("10", "30/70", "當天", "賣出", 20, 55.0),
    ("10", "30/70", "前後1天", "賣出", 32, 59.4),
    ("10", "30/70", "前後2天", "賣出", 34, 58.8),
    ("12", "20/80", "當天", "賣出", 3, 66.7),
    ("12", "30/70", "當天", "賣出", 19, 57.9),
    ("12", "30/70", "前後1天", "賣出", 25, 60.0),
    ("12", "30/70", "前後2天", "賣出", 28, 60.7),
    ("14", "20/80", "當天", "賣出", 2, 100.0),
    ("14", "30/70", "當天", "賣出", 13, 61.5),
    ("14", "30/70", "前後1天", "賣出", 18, 66.7),
    ("14", "30/70", "前後2天", "賣出", 22, 63.6),
    ("24", "20/80", "當天", "賣出", 0, None),
    ("24", "30/70", "當天", "賣出", 8, 50.0),
    ("24", "30/70", "前後1天", "賣出", 9, 55.6),
    ("24", "30/70", "前後2天", "賣出", 9, 55.6),
]

with tabs[0]:
    st.markdown("""
**半年、隔日收盤。KD 固定 9。** 影片沒講 RSI 天數、20/80 或 30/70、也沒講必須同天還是前後幾天，所以全部都測。

目前第 9 策略採用：
- **買進：RSI 12、門檻 30/70、當天共振，勝率 48.8%**（樣本 43，平均報酬 +0.40%）
- **賣出：RSI 14、門檻 30/70、前後 1 天，勝率 66.7%**（樣本只有 18，不可當真）

買進若只看樣本較多：RSI 6、30/70、前後 2 天是 42.6%（樣本 136）。
賣出若排除樣本少於 30：RSI 10、30/70、前後 1 天是 59.4%（樣本 32）。
20/80 的 100% 只有 2 筆，不要用。
""")
    sdf = pd.DataFrame(KD_SWEEP, columns=["RSI", "門檻", "窗口", "方向", "樣本", "勝率%"])
    st.dataframe(sdf.sort_values(["方向", "勝率%"], ascending=[True, False]), use_container_width=True, hide_index=True)

with tabs[1]:
    st.markdown("**同一檔出現在多個策略時集中顯示。** 買賣相反會標衝突。")
    conflict_df = build_conflict_table(results)
    if conflict_df.empty:
        st.info("目前沒有跨策略重疊個股。")
    else:
        # HTML 顯示方向顏色
        st.dataframe(conflict_df, use_container_width=True, hide_index=True)

with tabs[2]:
    render_strategy_tab(results.get("均線轉折", []), "均線轉折")
with tabs[3]:
    render_strategy_tab(results.get("周線多頭", []), "周線多頭")
with tabs[4]:
    render_strategy_tab(results.get("金包銀", []), "金包銀")
with tabs[5]:
    render_strategy_tab(results.get("RSI抄底", []), "RSI抄底")
with tabs[6]:
    render_strategy_tab(results.get("假突破破底翻", []), "假突破破底翻")
with tabs[7]:
    render_strategy_tab(results.get("一夜持股", []), "一夜持股")
with tabs[8]:
    render_strategy_tab(results.get("RSI背離", []), "RSI背離")
with tabs[9]:
    render_strategy_tab(results.get("RSI鈍化", []), "RSI鈍化")
with tabs[10]:
    render_strategy_tab(results.get("KD+RSI共振", []), "KD+RSI共振")

st.markdown("---")
st.caption("僅供學習監控。投資有風險，請獨立判斷並自負盈虧。")
