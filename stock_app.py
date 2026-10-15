# ==============================================================================
# 台股精選訊號監控系統（Streamlit v28.12 朱家泓戰法多頭發散 N 字重構版）
# ==============================================================================
import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import numpy as np
from plotly.subplots import make_subplots
import plotly.graph_objects as go

# 頁面基本設定
st.set_page_config(layout="wide", page_title="台股精選訊號 v28.12")

# 樣式調整
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
</style>
""", unsafe_allow_html=True)

# 雲端清單來源設定
MAIN_SHEET = {
    "base": "https://google.com",
    "gid": "0",
}

# 系統全域設定
CONFIG = {
    "MIN_VOLUME": 500000,      # 最小成交量限制：預設 500,000 (500張)
    "MAX_HISTORY": 300,        # 拉長歷史資料天數至 300 天
    "BATCH_WORKERS": 200,      # 多執行緒平行處理數量
    "CACHE_TTL": 300,          # 資料快取時間（秒）
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


def calc_bollinger_bands(closes, period=20, num_std=2.0):
    n = len(closes)
    ma = calc_ma_list(closes, period)
    upper = [None] * n
    lower = [None] * n
    bandwidth = [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        m = ma[i]
        std = np.std(window)
        u = m + num_std * std
        l = m - num_std * std
        upper[i] = u
        lower[i] = l
        bandwidth[i] = (u - l) / m if m > 0 else 0
    return ma, upper, lower, bandwidth


def is_weekly_and_daily_bullish(hist, hist_w=None):
    """共同過濾：週線多頭 + 日線多頭"""
    closes = hist["closes"]
    if len(closes) < 30:
        return False
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None or closes[-1] <= ma20[-1]:
        return False
    if hist_w is not None and len(hist_w.get("closes", [])) >= 25:
        w_ma20 = calc_ma_list(hist_w["closes"], 20)
        if w_ma20[-1] is not None:
            return hist_w["closes"][-1] > w_ma20[-1]
    ma100 = calc_ma_list(closes, 100)
    if ma100[-1] is None:
        return False
    return closes[-1] > ma100[-1]


def _current_week_key():
    t = time.localtime()
    monday_ts = time.mktime(t) - t.tm_wday * 86400
    return time.strftime("%Y-%m-%d", time.localtime(monday_ts))


def get_yahoo_history(sid: str, max_n: int = CONFIG["MAX_HISTORY"], interval: str = "1d"):
    if sid in SYMBOL_CACHE:
        suffixes = [SYMBOL_CACHE[sid]]
    else:
        suffixes = [".TW", ".TWO"]
    range_str = "5y" if interval in ("1wk", "1mo") else "2y"
    min_bars = 30 if interval in ("1wk", "1mo") else 150
    for sfx in suffixes:
        try:
            url = f"https://yahoo.com{sid}{sfx}?range={range_str}&interval={interval}"
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
            if len(t_cls) < min_bars:
                continue
            SYMBOL_CACHE[sid] = sfx
            if len(t_cls) > max_n:
                t_cls = t_cls[-max_n:]
                t_highs = t_highs[-max_n:]
                t_lows = t_lows[-max_n:]
                t_opens = t_opens[-max_n:]
                t_vols = t_vols[-max_n:]
                t_dates = t_dates[-max_n:]
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
            tasks.append({"sid": sid, "name": name, "sheet": "主要清單", "short_n": 20, "long_n": 100})
    except Exception as e:
        st.error(f"讀取主要股票清單失敗: {e}")
    return tasks


def _pack(sid, name, sheet, hist, price, signal, direction, entry, stop, target, how, side):
    return {
        "sid": sid, "name": name, "sheet": sheet, "hist": hist,
        "price": price, "signal": signal, "direction": direction,
        "entry": entry, "stop": stop, "target": target, "how": how,
        "side": side,
        "lots": int(hist["vols"][-1] // 1000),
    }


def _swing_indices(values, order=3, find_min=True):
    out = []
    n = len(values)
    for i in range(order, n - order):
        window = values[i - order:i + order + 1]
        if find_min:
            if values[i] == min(window):
                out.append(i)
        else:
            if values[i] == max(window):
                out.append(i)
    return out


# ==============================================================================
# 多頭策略函數定義
# ==============================================================================
def analyze_lin_20w_w_bottom(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 150 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma20, ma100 = calc_ma_list(closes, 20), calc_ma_list(closes, 100)
    if None in (ma20[-1], ma100[-1]) or closes[-1] <= ma100[-1] or closes[-1] <= ma20[-1]:
        return None
    recent_lows = lows[-50:]
    if min(recent_lows[25:]) < min(recent_lows[:25]) * 0.99:
        return None
    avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    if not (avg5_vol > 0 and vols[-1] >= avg5_vol * 1.3 and closes[-1] > opens[-1]):
        return None
    return {
        "signal": "林恩如20週均線W底：站上100MA+W底不再破底+站上月線帶量",
        "direction": "買進", "side": "long",
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], ma100[-1] * 0.98), 2),
        "target": round(closes[-1] * 1.12, 2),
        "how": "林恩如四大法寶：大趨勢100MA向上、W底打底不破前低、帶量站上月線表態",
        "price": closes[-1],
    }


def analyze_chujiahung_bottom(hist):
    """
    朱家泓頭頭高、底底高 ＆ 回後買上漲戰法（完全重構修正版 v28.12）
    1. 均線架構：四線多排且排除均線糾結橫盤 (要求發散斜率)
    2. 波段結構：嚴格多頭波段 N 字交替 (L1 < L2 且 H1 < H2，且時序必須正確)
    3. 回後買上漲：拉回修正未跌破前低 (L1) 且守住月線
    4. 實體紅K強勢突破5MA：收盤價 > 開盤價且過濾掉變盤十字線與長上影線
    5. 停損防線：精確守波段轉折低點
    """
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 120 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
# ---------- 1. 均線架構：四線多排 + 排除均線糾結橫盤 (要求發散斜率) ----------
ma5  = calc_ma_list(closes, 5)
ma10 = calc_ma_list(closes, 10)
ma20 = calc_ma_list(closes, 20)
ma60 = calc_ma_list(closes, 60)
if any(x is None for x in (ma5[-1], ma5[-10], ma10[-1], ma20[-1], ma20[-10], ma60[-1], ma60[-10])):
return None
is_ma_aligned = (ma5[-1] > ma10[-1] > ma20[-1] > ma60[-1])
is_ma_up = (ma20[-1] > ma20[-5]) and (ma60[-1] > ma60[-5])
# 核心修正：要求當前5MA與60MA的距離大於10天前的距離，確保均線多頭發散，排除黏合橫盤
is_expanding = (ma5[-1] - ma60[-1]) > (ma5[-10] - ma60[-10])
if not (is_ma_aligned and is_ma_up and is_expanding and closes[-1] > ma20[-1]):
return None
# ---------- 2. 波段結構：嚴格多頭波段 N 字交替 ----------
look = 90
low_swings  = _swing_indices(lows[-look:],  order=4, find_min=True)
high_swings = _swing_indices(highs[-look:], order=4, find_min=False)
base_idx = n - look
abs_low_swings  = [base_idx + i for i in low_swings]
abs_high_swings = [base_idx + i for i in high_swings]
if len(abs_low_swings) < 2 or len(abs_high_swings) < 2:
return None
idx_l1, idx_l2 = abs_low_swings[-2], abs_low_swings[-1]
idx_h1, idx_h2 = abs_high_swings[-2], abs_high_swings[-1]
l1, l2 = lows[idx_l1], lows[idx_l2]
h1, h2 = highs[idx_h1], highs[idx_h2]
# 核心修正：在時間軸上必須形成標準的交替結構，避免極值錯置 L1 -> H1 -> L2
if not (idx_l1 < idx_h1 < idx_l2):
return None
# 數值定義確認：底底高 且 收盤價或高點過前高
if not (l2 > l1 * 1.01 and closes[-1] > h1):
return None
# ---------- 3. 位階過濾 ----------
recent_low_60 = min(lows[-60:]) if n >= 60 else min(lows)
gain_from_low = (closes[-1] / recent_low_60 - 1.0) if recent_low_60 > 0 else 0.0
# 排除剛從谷底稍微反彈、大長線趨勢仍被壓制的死盤
if gain_from_low < 0.05:
return None
long_term_high = max(highs[-120:]) if n >= 120 else max(highs)
if gain_from_low > 0.55 or closes[-1] >= long_term_high * 0.95:
return None
if gain_from_low <= 0.20:
wave_label = "第1波（初升段發動）"
elif gain_from_low <= 0.40:
wave_label = "第2波（主升段攻擊）"
else:
wave_label = "第3波（高位階順勢）"
# ---------- 4. 精確「回後買上漲」與扎實攻擊紅K確認 ----------
# 條件 A：拉回修正最低點不能跌破前一波波段低點 (l1)，且守住月線(20MA)
recent_pullback_lows = lows[-15:-1] if n >= 15 else lows[:-1]
if min(recent_pullback_lows) < l1 or min(recent_pullback_lows) < ma20[-2] * 0.995:
return None
# 條件 B：當天必須是扎實的「實體紅K棒」（收盤 > 開盤）
is_bullish_candle = closes[-1] > opens[-1]
if not is_bullish_candle:
return None
body_size = closes[-1] - opens[-1]
upper_shadow = highs[-1] - closes[-1]
lower_shadow = opens[-1] - lows[-1]
# 核心修正：嚴格過濾長上影線與十字變盤線。實體K棒大小必須大於上下影線總和的 1.2 倍
is_solid_candle = body_size > (upper_shadow + lower_shadow) * 1.2
# 條件 C：精確買點—收盤價正式突破 5MA
is_above_ma5 = closes[-1] > ma5[-1] and closes[-2] <= ma5[-2]
# 條件 D：量能溫和放大（大於5日均量 1.3 倍，且非失控天量）
avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
is_volume_ok = avg5_vol > 0 and (avg5_vol * 1.3 <= vols[-1] <= avg5_vol * 3.5)
if not (is_solid_candle and is_above_ma5 and is_volume_ok):
return None
# ---------- 5. 停損與目標設定 ----------
stop_price = round(min(lows[-1], l2), 2)
target_price = round(closes[-1] * 1.15, 2)
signal_text = f"朱家泓趨勢重構｜{wave_label}｜回後買上漲突破"
how_text = (
f"【位階確認】{wave_label}，擺脫低檔無量盤整｜【精確買點】不破前低、收盤扎實紅K強勢突破5MA｜"
f"【結構特徵】均線呈現攻擊發散（非糾結）且月季線同步翻揚｜【風控停損】嚴格守波段轉折低點 {stop_price} 元。"
)
return {
"signal": signal_text,
"direction": "買進",
"side": "long",
"entry": round(closes[-1] * 1.002, 2),
"stop": stop_price,
"target": target_price,
"how": how_text,
"price": closes[-1],
}
def analyze_ashui_1(hist):
closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
n = len(closes)
if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
return None
ma20, upper, lower, bandwidth = calc_bollinger_bands(closes, period=20, num_std=2.1)
if None in (ma20[-1], upper[-1], bandwidth[-1]):
return None
is_compressed = min(bandwidth[-10:]) <= 0.2
is_volume_surge = vols[-1] >= (sum(vols[-6:-1]) / 5) * 2.0
is_break_upper = closes[-1] > opens[-1] and closes[-1] >= upper[-1] * 0.995
if not (is_compressed and is_volume_surge and is_break_upper):
return None
return {
"signal": f"阿水一式：帶寬壓縮({bandwidth[-1]:.2f}≤0.2)+2倍均量突破2.1倍上軌",
"direction": "買進", "side": "long",
"entry": round(closes[-1] * 1.005, 2),
"stop": round(min(lows[-1], ma20[-1] * 0.98), 2),
"target": round(closes[-1] * 1.10, 2),
"how": "帶寬<=0.2壓縮+2倍均量+紅K突破上軌",
"price": closes[-1],
}
def analyze_power_candle_recovery(hist):
closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
n = len(closes)
if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
return None
ma20 = calc_ma_list(closes, 20)
if ma20[-1] is None or closes[-1] < ma20[-1]:
return None
bodies = [abs(closes[i] - opens[i]) for i in range(n-20, n-1)]
avg_body = sum(bodies) / len(bodies) if bodies else 0
if avg_body == 0:
return None
big_bearish_idx = -1
for i in range(n-5, n-1):
if (opens[i] - closes[i]) >= avg_body * 2.5 and closes[i] < opens[i]:
big_bearish_idx = i
break
if big_bearish_idx == -1:
return None
if closes[-1] > highs[big_bearish_idx] and closes[-1] > opens[-1]:
return {
"signal": "大K棒強力收回：突破恐慌大陰線高點且站上月線",
"direction": "買進", "side": "long",
"entry": round(closes[-1] * 1.005, 2),
"stop": round(min(lows[-1], lows[big_bearish_idx] * 0.98), 2),
"target": round(closes[-1] * 1.10, 2),
"how": "恐慌賣壓大陰線被完全收回，停損守大陰線底下",
"price": closes[-1],
}
return None
def analyze_rsi_passivation(hist):
closes, vols = hist["closes"], hist["vols"]
n = len(closes)
if n < 40 or vols[-1] < CONFIG["MIN_VOLUME"]:
return None
ma20 = calc_ma_list(closes, 20)
if ma20[-1] is None or closes[-1] < ma20[-1]:
return None
rsi = calc_rsi(closes, 14)
if any(r is None or r < 70 for r in rsi[-5:]):
return None
ma5 = calc_ma_list(closes, 5)
if ma5[-1] is None or ma5[-2] is None or closes[-1] <= ma5[-1] or ma5[-1] <= ma5[-2]:
return None
return {
"signal": f"RSI鈍化：連續5日≥70 + 站上月線與五日線",
"direction": "買進（順勢）", "side": "long",
"entry": round(closes[-1] * 1.005, 2),
"stop": round(min(ma5[-1] * 0.99, closes[-1] * 0.97), 2),
"target": round(closes[-1] * 1.06, 2),
"how": "跌破五日線或RSI<70出場",
"price": closes[-1],
}
def _div_pairs_for_period(closes, lows, highs, rsi, look, bull=True):
n = len(closes)
base = n - look
if bull:
swings = [base + i for i in _swing_indices(lows[-look:], order=3, find_min=True)]
pairs = []
for a, b in zip(swings, swings[1:]):
if lows[b] < lows[a] and rsi[b] is not None and rsi[a] is not None and rsi[b] > rsi[a]:
pairs.append((a, b))
return pairs
swings = [base + i for i in _swing_indices(highs[-look:], order=3, find_min=False)]
pairs = []
for a, b in zip(swings, swings[1:]):
if highs[b] > highs[a] and rsi[b] is not None and rsi[a] is not None and rsi[b] < rsi[a]:
pairs.append((a, b))
return pairs
def _best_div(closes, lows, highs, bull=True):
n = len(closes)
look = min(80, n - 1)
near = n - 8
found_triple, found_double, found_single = [], [], []
for period in (5, 10):
rsi = calc_rsi(closes, period)
if any(x is None for x in rsi[-50:]):
continue
pairs = _div_pairs_for_period(closes, lows, highs, rsi, look, bull=bull)
if not pairs or pairs[-1][1] < near:
continue
last = pairs[-1]
degree = 1
if len(pairs) >= 3:
p3, p2, p1 = pairs[-3], pairs[-2], pairs[-1]
if (p2[1] == p1[0] or (p1[1] - p2[1] <= 40)) and (p3[1] == p2[0] or (p2[1] - p3[1] <= 40)):
degree = 3
elif p2[1] == p1[0] or (p1[1] - p2[1] <= 40):
degree = 2
elif len(pairs) >= 2:
p2, p1 = pairs[-2], pairs[-1]
if p2[1] == p1[0] or (p1[1] - p2[1] <= 40):
degree = 2
item = (period, last, rsi[-1], degree)
if degree == 3:
found_triple.append(item)
elif degree == 2:
found_double.append(item)
else:
found_single.append(item)
chosen = found_triple if found_triple else (found_double if found_double else found_single)
if not chosen:
return None
deg = chosen[0][3]
rsi_txt = "、".join(f"RSI{p}={rv:.1f}" for p, _, rv, _ in chosen)
last_idx = max(last for _, last, _, _ in chosen)[1]
return {"degree": deg, "rsi_txt": rsi_txt, "last_idx": last_idx}
def analyze_bull_divergence(hist):
closes, lows, highs, vols = hist["closes"], hist["lows"], hist["highs"], hist["vols"]
if len(closes) < 80 or vols[-1] < CONFIG["MIN_VOLUME"]:
return None
info = _best_div(closes, lows, highs, bull=True)
if not info:
return None
deg = info["degree"]
if deg == 3:
tag = "三度多頭背離"
elif deg == 2:
tag = "二度多頭背離"
else:
tag = "一次多頭背離"
return {
"signal": f"{tag}：價新低RSI未新低（{info['rsi_txt']}）",
"direction": "買進（觀察反轉）", "side": "long",
"entry": round(closes[-1] * 1.005, 2),
"stop": round(min(lows[info["last_idx"]] * 0.98, closes[-1] * 0.96), 2),
"target": round(closes[-1] * 1.07, 2),
"how": "停損背離低點下。RSI用5與10檢查。",
"price": closes[-1],
}
SIGNAL_KEYS = [
"林恩如20週均線W底", "朱家泓頭頭高底底高",
"阿水一式", "大K棒收回",
"RSI鈍化", "多頭背離"
]
def build_bullish_candidates(main_stocks):
candidates = []
def check_one(item):
hist = get_yahoo_history(item["sid"], interval="1d")
hist_w = get_yahoo_history(item["sid"], interval="1wk", max_n=120)
if hist is None:
return None
if is_weekly_and_daily_bullish(hist, hist_w):
return {"sid": item["sid"], "name": item["name"],
"sheet": item.get("sheet", "主要清單"), "hist": hist, "hist_w": hist_w}
return None
with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as ex:
for f in concurrent.futures.as_completed([ex.submit(check_one, i) for i in main_stocks]):
try:
res = f.result()
if res:
candidates.append(res)
except Exception:
pass
return candidates
def run_full_scan(force_refresh_candidates=False):
results = {k: [] for k in SIGNAL_KEYS}
def add(key, item, r):
if not r:
return
results[key].append(_pack(
item["sid"], item["name"], item["sheet"], item["hist"],
r["price"], r["signal"], r["direction"], r["entry"], r["stop"], r["target"],
r["how"], r["side"]
))
main_stocks = load_main_stocks()
if not main_stocks:
st.warning("目前沒有任何股票可掃描，請檢查 Google 試算表設定。")
return results
week_key = _current_week_key()
need_update = (
force_refresh_candidates
or "bullish_candidates" not in st.session_state
or st.session_state.get("candidates_week") != week_key
)
if need_update:
reason = "強制更新" if force_refresh_candidates else "本週首次/跨週"
with st.spinner(f"正在建立「週線+日線多頭」候選名單（{reason}）..."):
candidates = build_bullish_candidates(main_stocks)
st.session_state["bullish_candidates"] = candidates
st.session_state["candidates_week"] = week_key
st.session_state["candidates_built_at"] = time.strftime("%Y-%m-%d %H:%M")
st.info(f"候選名單已更新（{reason}）：共 {len(candidates)} 檔｜{st.session_state['candidates_built_at']}")
else:
candidates = st.session_state.get("bullish_candidates", [])
st.caption(f"使用本週候選名單（共 {len(candidates)} 檔，建立於 {st.session_state.get('candidates_built_at','?')}）")
if not candidates:
st.warning("目前沒有符合週線+日線多頭的股票。")
return results
def process_candidate(item):
hist = item.get("hist") or get_yahoo_history(item["sid"], interval="1d")
hist_w = item.get("hist_w")
if hist is None:
return []
if hist_w is None:
hist_w = get_yahoo_history(item["sid"], interval="1wk", max_n=120)
if not is_weekly_and_daily_bullish(hist, hist_w):
return []
found = []
mapping = [
("林恩如20週均線W底", lambda h: analyze_lin_20w_w_bottom(h)),
("朱家泓頭頭高底底高", analyze_chujiahung_bottom),
("阿水一式", analyze_ashui_1),
("大K棒收回", analyze_power_candle_recovery),
("RSI鈍化", analyze_rsi_passivation),
("多頭背離", analyze_bull_divergence),
]
for key, fn in mapping:
r = fn(hist)
if r:
found.append((key, {**item, "hist": hist, "hist_w": hist_w}, r))
return found
with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as ex:
for f in concurrent.futures.as_completed([ex.submit(process_candidate, i) for i in candidates]):
try:
for key, item, r in f.result():
add(key, item, r)
except Exception:
pass
return results
def build_conflict_table(results):
by_sid = {}
for key, items in results.items():
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
"衝突": "是" if conflict else "否",
"方向": "｜".join(f"{x['signal'].split('｜')[0]}:{x.get('direction','')}" for x in lst),
"現價": lst[0]["price"],
})
if not rows:
return pd.DataFrame()
return pd.DataFrame(rows).sort_values(["衝突", "策略數"], ascending=[True, False])
def make_chart(hist, title, is_bollinger=False):
closes = hist["closes"][-100:]
opens = hist["opens"][-100:]
highs = hist["highs"][-100:]
lows = hist["lows"][-100:]
vols = hist["vols"][-100:]
x = list(range(len(closes)))
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])
fig.add_trace(go.Candlestick(
x=x, open=opens, high=highs, low=lows, close=closes,
increasing_line_color="#FF3333", increasing_fillcolor="#FF3333",
decreasing_line_color="#00A600", decreasing_fillcolor="#00A600",
line_width=1.5, name="K線"
), row=1, col=1)
if is_bollinger:
_, upper_all, lower_all, _ = calc_bollinger_bands(hist["closes"], period=20, num_std=2.1)
ma20_all = calc_ma_list(hist["closes"], 20)
upper = upper_all[-100:]
lower = lower_all[-100:]
ma20 = ma20_all[-100:]
fig.add_trace(go.Scatter(x=x, y=upper, mode="lines", name="布林上軌(2.1v)", line=dict(color="#FF8C00", width=1.5, dash="dash")), row=1, col=1)
fig.add_trace(go.Scatter(x=x, y=ma20, mode="lines", name="布林中軌(MA20)", line=dict(color="#1E90FF", width=1.5)), row=1, col=1)
fig.add_trace(go.Scatter(x=x, y=lower, mode="lines", name="布林下軌(2.1v)", line=dict(color="#FF8C00", width=1.5, dash="dash")), row=1, col=1)
else:
# 繪製朱家泓戰法核心四線：MA5, MA10, MA20(月), MA60(季)
ma5  = calc_ma_list(hist["closes"], 5)[-100:]
ma10 = calc_ma_list(hist["closes"], 10)[-100:]
ma20 = calc_ma_list(hist["closes"], 20)[-100:]
ma60 = calc_ma_list(hist["closes"], 60)[-100:]
fig.add_trace(go.Scatter(x=x, y=ma5,  mode="lines", name="5日線(MA5)", line=dict(color="#FF1493", width=1)), row=1, col=1)
fig.add_trace(go.Scatter(x=x, y=ma10, mode="lines", name="10日線(MA10)", line=dict(color="#FF8C00", width=1)), row=1, col=1)
fig.add_trace(go.Scatter(x=x, y=ma20, mode="lines", name="月線(MA20)", line=dict(color="#1E90FF", width=1.5)), row=1, col=1)
fig.add_trace(go.Scatter(x=x, y=ma60, mode="lines", name="季線(MA60)", line=dict(color="#32CD32", width=1.5)), row=1, col=1)
colors = ["#FF3333" if closes[i] >= opens[i] else "#00A600" for i in range(len(closes))]
fig.add_trace(go.Bar(x=x, y=vols, marker_color=colors, name="量"), row=2, col=1)
fig.update_layout(title=title, xaxis_rangeslider_visible=False,
margin=dict(l=8, r=8, t=36, b=8), height=380, showlegend=True,
legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
font=dict(size=14))
fig.update_xaxes(showticklabels=False, showgrid=False)
return fig
def direction_html(direction: str) -> str:
d = direction or ""
if "賣" in d or "減碼" in d:
return f'{d}'
if "買" in d:
return f'{d}'
return d
def render_signal_tab(data_list, title, note="", is_bollinger=False):
st.markdown(f"{title}")
if note:
st.caption(note)
if not data_list:
st.info("目前沒有符合的個股。")
return
st.markdown(f"共 {len(data_list)} 檔")
rows_html = []
for d in data_list:
dir_h = direction_html(d.get("direction", ""))
pxcell = f"買{d.get('entry', '-')} 停{d.get('stop', '-')} 目{d.get('target', '-')}"
rows_html.append(
f""
f"{d['sid']}"
f"{d['name']}"
f"{d['price']:.2f}"
f"{dir_h}"
f"{d['signal']}"
f"{d.get('lots', 0)}張"
f"{pxcell}"
f""
)
table = f"""
{''.join(rows_html)}

代號
	名稱
	現價
	方向
	訊號
	量能
	買賣參考

"""
st.markdown(table, unsafe_allow_html=True)
for idx, item in enumerate(data_list):
with st.expander(f"{item['sid']} {item['name']}", expanded=False):
st.markdown(f"方向： {direction_html(item.get('direction',''))}", unsafe_allow_html=True)
st.markdown(f"訊號： {item['signal']}")
st.markdown(f"操作： {item.get('how', '')}")
st.markdown(
f"現價 {item['price']:.2f}｜買進 {item.get('entry','-')}｜"
f"停損 {item.get('stop','-')}｜目標 {item.get('target','-')}｜"
f"量 {item.get('lots',0)}張"
)
fig = make_chart(item["hist"], f"{item['sid']} {item['name']}", is_bollinger=is_bollinger)
st.plotly_chart(fig, use_container_width=True, key=f"c_{title}{idx}{item['sid']}")

==============================================================================


UI 主介面設定


==============================================================================

st.title("台股精選訊號 v28.12（朱家泓戰法精確重構＋四均線圖表）")
st.caption(f"{time.strftime('%Y-%m-%d %H:%M')}｜週線+日線雙重多頭過濾｜圖表顯示 MA5/MA10/MA20/MA60")
col1, col2, col3 = st.columns(3)
with col1:
do_scan = st.button("掃描訊號（使用本週候選）", use_container_width=True)
with col2:
force_candidates = st.button("強制更新候選名單", use_container_width=True)
with col3:
if st.button("清除快取", type="primary", use_container_width=True):
st.cache_data.clear()
SYMBOL_CACHE.clear()
for k in ("bullish_candidates", "candidates_week", "scan_results_v28"):
if k in st.session_state:
del st.session_state[k]
st.rerun()
if do_scan or force_candidates:
with st.spinner("掃描中..."):
st.session_state["scan_results_v28"] = run_full_scan(force_refresh_candidates=bool(force_candidates))
st.success("掃描完成")
results = st.session_state.get("scan_results_v28", {})
if not results:
st.info("請先按「強制更新候選名單」建立本週多頭股票，再按「掃描訊號」。")
tabs = st.tabs([
"衝突彙整",
"林恩如20週W底",
"朱家泓頭頭高",
"阿水一式",
"大K棒收回",
"RSI鈍化",
"多頭背離（含一/二/三度）",
])
with tabs[0]:
st.markdown("同一檔出現多個訊號時集中顯示。")
cdf = build_conflict_table(results)
if cdf.empty:
st.info("目前沒有跨訊號重疊個股。")
else:
try:
st.dataframe(cdf, use_container_width=True, hide_index=True)
except TypeError:
st.dataframe(cdf, use_container_width=True)
with tabs[1]:
render_signal_tab(results.get("林恩如20週均線W底", []), "林恩如 20 週均線 W 底戰法", "站上 100MA 與月線 + W 底不再破底 + 帶量")
with tabs[2]:
render_signal_tab(
results.get("朱家泓頭頭高底底高", []),
"朱家泓頭頭高底底高戰法（精確回後買上漲重構版）",
"四線多排發散向上 + 嚴格N字頭頭高底底高 + 拉回未破前低 + 扎實紅K突破5MA"
)
with tabs[3]:
render_signal_tab(results.get("阿水一式", []), "阿水一式（帶寬<=0.2壓縮突破）", "2.1倍帶寬<=0.2 + 2倍均量 + 紅K突破上軌", is_bollinger=True)
with tabs[4]:
render_signal_tab(results.get("大K棒收回", []), "大K棒強力收回", "突破恐慌陰線 + 站上月線")
with tabs[5]:
render_signal_tab(results.get("RSI鈍化", []), "RSI 鈍化", "連續5日≥70 + 站上月線與五日線")
with tabs[6]:
render_signal_tab(results.get("多頭背離", []), "一次／二度／三度多頭背離", "RSI(5) 與 RSI(10) 檢查｜支援一至三度底背離結構")
st.markdown("---")
st.caption("僅供學習監控。投資有風險，請獨立判斷並自負盈虧。")
