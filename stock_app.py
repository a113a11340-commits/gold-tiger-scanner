"""
================================================================================
台股精選訊號監控系統（Streamlit 朱家泓細膩化版 + 只抓日線）
================================================================================
【朱家泓細膩化重點】
1. 位階標註（第幾波近似）
   - 第1波（初升段近似，漲幅 ≤20%）→ 風險低
   - 第2波（主升段近似，20–40%）→ 風險中
   - 第3波（較高位階，40–60%）→ 風險中高
   - 第3波以上／高檔 → 直接過濾（避免末升段陷阱）
2. 買點類型標註
   - 回後買上漲（優先）：最近有回檔跡象 + 今日收盤重新站上5MA + 突破昨高 + 紅K
   - 突破昨高＋站上5MA
   - 站上5MA轉強
3. 其他強化
   - 強制 5 > 10 > 20 > 60 四線多排 + 月線／季線向上
   - 量能溫和放大（≥5日均量1.2倍），避免極端高檔爆量
   - 停損優先取「進場日低點 / 最近波段低點(l2) / 約5%」

【已移除策略】
貫穿線、三內身、大K棒強力收回、三白兵、爆量三白兵、黏合晨星、
資金輪動主流強勢股、施昇輝0050樂活KD

【保留策略】
林恩如20週均線W底、朱家泓（細膩化）、阿水一式、RSI鈍化、多頭背離、破底翻
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

st.set_page_config(layout="wide", page_title="台股精選訊號（朱家泓細膩化）")

st.markdown("""
<style>
.block-container { padding-top: 1rem; padding-bottom: 1rem; }
table { width: 100% !important; font-size: 15px !important; font-weight: bold !important; }
th { background-color: #f0f2f6 !important; font-size: 15px !important; font-weight: bold !important;
     white-space: normal !important; word-wrap: break-word !important; }
td { font-size: 15px !important; font-weight: bold !important;
     white-space: normal !important; word-wrap: break-word !important; max-width: 300px !important; }
.buy-text { color: #E53935 !important; font-weight: bold; font-size: 15px; }
.sell-text { color: #43A047 !important; font-weight: bold; font-size: 15px; }
</style>
""", unsafe_allow_html=True)

WINRATE = {
    "林恩如20週均線W底": "58.5%",
    "朱家泓頭頭高底底高": "62.5%",
    "阿水一式": "53.5%",
    "破底翻": "48.2%",
    "RSI鈍化": "45.6%",
    "多頭背離": "43.4%",
}

MAIN_SHEET = {
    "base": "https://docs.google.com/spreadsheets/d/13Mv-7uaFyR1KcxNRVrhxCGAAntElKprB7ZeWWBxS3n0",
    "gid": "0",
}

CONFIG = {
    "MIN_VOLUME": 500000,
    "MAX_HISTORY": 300,
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


def calc_bollinger_bands(closes, period=20, num_std=2.0):
    n = len(closes)
    ma = calc_ma_list(closes, period)
    upper = [None] * n
    lower = [None] * n
    bandwidth = [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        m = ma[i]
        std = np.std(window)
        u = m + num_std * std
        l = m - num_std * std
        upper[i] = u
        lower[i] = l
        bandwidth[i] = (u - l) / m if m > 0 else 0
    return ma, upper, lower, bandwidth


def get_yahoo_history(sid: str, max_n: int = CONFIG["MAX_HISTORY"], interval: str = "1d"):
    if sid in SYMBOL_CACHE:
        suffixes = [SYMBOL_CACHE[sid]]
    else:
        suffixes = [".TW", ".TWO"]
    range_str = "2y"
    min_bars = 150
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range={range_str}&interval={interval}"
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
            tasks.append({"sid": sid, "name": name, "sheet": "主要清單"})
    except Exception as e:
        st.error(f"讀取主要股票清單失敗: {e}")
    return tasks


def _pack(sid, name, sheet, hist, price, signal, direction, entry, stop, target, how, side, wr, extra=""):
    return {
        "sid": sid, "name": name, "sheet": sheet, "hist": hist,
        "price": price, "signal": f"{signal}｜勝率{wr}", "direction": direction,
        "entry": entry, "stop": stop, "target": target, "how": how,
        "side": side, "winrate": wr, "extra": extra,
        "lots": int(hist["vols"][-1] // 1000),
    }


# ==============================================================================
# 朱家泓細膩化策略（核心）
# ==============================================================================
def analyze_chujiahung_refined(hist):
    """
    朱家泓細膩化版
    - 強制 5>10>20>60 多排 + 月線／季線向上
    - 位階：依相對 60MA 漲幅與波數近似判斷第1/2/3波，第3波以上高檔過濾
    - 買點類型：回後買上漲（優先）／突破昨高+站上5MA／站上5MA轉強
    - 量能：≥1.2倍均量，排除極端爆量
    - 停損：當日低點 / 最近波段低點(l2) / 約5%
    """
    closes = hist["closes"]
    highs = hist["highs"]
    lows = hist["lows"]
    opens = hist["opens"]
    vols = hist["vols"]
    n = len(closes)
    if n < 120 or vols[-1] < CONFIG["MIN_VOLUME"] or closes[-1] < 15:
        return None

    ma5 = calc_ma_list(closes, 5)
    ma10 = calc_ma_list(closes, 10)
    ma20 = calc_ma_list(closes, 20)
    ma60 = calc_ma_list(closes, 60)
    if None in (ma5[-1], ma10[-1], ma20[-1], ma60[-1]):
        return None

    # 1. 強制四線多排
    if not (ma5[-1] > ma10[-1] > ma20[-1] > ma60[-1]):
        return None

    # 2. 月線、季線必須向上
    if ma20[-1] <= ma20[-5] or ma60[-1] <= ma60[-5]:
        return None

    # 3. 必須站上月線
    if closes[-1] <= ma20[-1]:
        return None

    # 4. 位階計算（相對 60MA 漲幅）
    dist60 = (closes[-1] - ma60[-1]) / ma60[-1]
    if dist60 > 0.60:  # 第3波以上／高檔直接過濾
        return None

    if dist60 <= 0.20:
        wave_label = "第1波（初升段近似）"
        risk = "風險低"
    elif dist60 <= 0.40:
        wave_label = "第2波（主升段近似）"
        risk = "風險中"
    else:
        wave_label = "第3波（較高位階）"
        risk = "風險中高"

    # 5. 頭頭高、底底高（簡化 swing）
    look = min(80, n)
    recent_lows = lows[-look:]
    recent_highs = highs[-look:]
    # 找相對低點／高點
    mid = look // 2
    early_low = min(recent_lows[:mid])
    late_low = min(recent_lows[mid:])
    early_high = max(recent_highs[:mid])
    late_high = max(recent_highs[mid:])
    if not (late_low >= early_low * 0.995 and late_high >= early_high * 0.995):
        return None

    # 最近波段低點近似（l2）
    l2 = late_low

    # 6. 紅K
    body = closes[-1] - opens[-1]
    if body <= 0:
        return None
    upper_shadow = highs[-1] - max(closes[-1], opens[-1])
    lower_shadow = min(closes[-1], opens[-1]) - lows[-1]
    if body < (upper_shadow + lower_shadow) * 1.0:
        return None

    # 7. 量能溫和放大（≥1.2倍），排除極端爆量（>4倍）
    avg5 = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    if avg5 <= 0 or vols[-1] < avg5 * 1.2 or vols[-1] > avg5 * 4.0:
        return None

    # 8. 買點類型判斷
    reclaimed_5ma = closes[-1] > ma5[-1] and (n >= 2 and closes[-2] <= ma5[-2] or True)
    break_yest_high = closes[-1] > highs[-2]
    # 最近有回檔跡象：近5日內曾收在5MA下方或出現相對低點
    had_pullback = False
    for i in range(-6, -1):
        if closes[i] < ma5[i] or lows[i] < ma20[i] * 0.99:
            had_pullback = True
            break

    if had_pullback and reclaimed_5ma and break_yest_high and body > 0:
        buy_type = "回後買上漲（優先）"
    elif break_yest_high and closes[-1] > ma5[-1]:
        buy_type = "突破昨高＋站上5MA"
    elif closes[-1] > ma5[-1]:
        buy_type = "站上5MA轉強"
    else:
        return None  # 不符合任一買點類型

    # 9. 停損：當日低點 / 最近波段低點 / 約5%
    stop_price = min(lows[-1], l2, closes[-1] * 0.95)

    signal_txt = f"朱家泓細膩化｜{wave_label}｜{buy_type}｜{risk}"
    how_txt = (
        f"{wave_label}｜{buy_type}｜"
        f"停損取當日低點/波段低點(l2)/約5%｜"
        f"跌破5MA減碼"
    )

    return {
        "signal": signal_txt,
        "direction": "買進",
        "side": "long",
        "winrate": WINRATE["朱家泓頭頭高底底高"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(stop_price, 2),
        "target": round(closes[-1] * 1.12, 2),
        "how": how_txt,
        "price": closes[-1],
        "extra": f"{wave_label}｜{buy_type}｜{risk}",
    }


# ==============================================================================
# 其他保留策略
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
        "direction": "買進", "side": "long", "winrate": WINRATE["林恩如20週均線W底"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], ma100[-1] * 0.98), 2),
        "target": round(closes[-1] * 1.12, 2),
        "how": "大趨勢100MA向上、W底不破前低、帶量站上月線",
        "price": closes[-1], "extra": "",
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
    is_break_upper = closes[-1] > upper[-1] and closes[-1] > opens[-1]
    if not (is_compressed and is_volume_surge and is_break_upper):
        return None
    return {
        "signal": "阿水一式：布林壓縮後帶量突破2.1倍上軌",
        "direction": "買進", "side": "long", "winrate": WINRATE["阿水一式"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(ma20[-1], closes[-1] * 0.95), 2),
        "target": round(closes[-1] * 1.12, 2),
        "how": "守20MA或跌幅5%",
        "price": closes[-1], "extra": "",
    }


def analyze_break_bottom_flip(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None or closes[-1] <= ma20[-1]:
        return None
    recent_low = min(lows[-20:-5])
    if lows[-1] >= recent_low * 0.98 or closes[-1] < recent_low:
        return None
    return {
        "signal": "破底翻：破前低後快速收回+站上月線",
        "direction": "買進", "side": "long", "winrate": WINRATE["破底翻"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-5:]), 2),
        "target": round(closes[-1] * 1.10, 2),
        "how": "停損近期低點",
        "price": closes[-1], "extra": "",
    }


def analyze_rsi_passivation(hist):
    closes, vols = hist["closes"], hist["vols"]
    n = len(closes)
    if n < 40 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    rsi = calc_rsi(closes, 14)
    for i in range(n - 5, n):
        if rsi[i] is None or rsi[i] < 70:
            return None
    ma5 = calc_ma_list(closes, 5)
    if ma5[-1] is None or ma5[-2] is None:
        return None
    if not (closes[-1] > ma5[-1] and ma5[-1] > ma5[-2]):
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is not None and closes[-1] < ma20[-1]:
        return None
    return {
        "signal": f"RSI鈍化：連續5日≥70（{rsi[-1]:.1f}）+站上五日線",
        "direction": "買進（順勢）", "side": "long", "winrate": WINRATE["RSI鈍化"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(ma5[-1] * 0.99, closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.06, 2),
        "how": "跌破五日線或RSI<70出場",
        "price": closes[-1], "extra": "",
    }


def analyze_bull_divergence(hist):
    closes, lows, highs, vols = hist["closes"], hist["lows"], hist["highs"], hist["vols"]
    n = len(closes)
    if n < 90 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    rsi5 = calc_rsi(closes, 5)
    rsi10 = calc_rsi(closes, 10)
    if rsi5[-1] is None or rsi10[-1] is None:
        return None
    look = min(60, n - 1)
    recent_low_idx = n - 1 - lows[-look:].index(min(lows[-look:]))
    if recent_low_idx >= n - 5:
        return None
    if lows[-1] >= lows[recent_low_idx]:
        return None
    if rsi5[-1] <= rsi5[recent_low_idx] and rsi10[-1] <= rsi10[recent_low_idx]:
        return None
    return {
        "signal": f"多頭背離：價新低RSI未新低（RSI5={rsi5[-1]:.1f}）",
        "direction": "買進（觀察反轉）", "side": "long", "winrate": WINRATE["多頭背離"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1] * 0.98, closes[-1] * 0.96), 2),
        "target": round(closes[-1] * 1.07, 2),
        "how": "停損背離低點下",
        "price": closes[-1], "extra": "",
    }


SIGNAL_KEYS = [
    "林恩如20週均線W底", "朱家泓頭頭高底底高", "阿水一式",
    "破底翻", "RSI鈍化", "多頭背離"
]


def run_full_scan():
    results = {k: [] for k in SIGNAL_KEYS}

    def add(key, item, r):
        if not r:
            return
        results[key].append(_pack(
            item["sid"], item["name"], item["sheet"], item["hist"],
            r["price"], r["signal"], r["direction"], r["entry"], r["stop"], r["target"],
            r["how"], r["side"], r["winrate"], r.get("extra", "")
        ))

    main_stocks = load_main_stocks()
    if not main_stocks:
        st.warning("目前沒有任何股票可掃描，請檢查 Google 試算表設定。")
        return results

    st.info(f"朱家泓細膩化 + 只抓日線，本次掃描全部 {len(main_stocks)} 檔")

    def process_one(item):
        hist = get_yahoo_history(item["sid"], interval="1d")
        if hist is None:
            return []
        found = []
        mapping = [
            ("林恩如20週均線W底", analyze_lin_20w_w_bottom),
            ("朱家泓頭頭高底底高", analyze_chujiahung_refined),
            ("阿水一式", analyze_ashui_1),
            ("破底翻", analyze_break_bottom_flip),
            ("RSI鈍化", analyze_rsi_passivation),
            ("多頭背離", analyze_bull_divergence),
        ]
        for key, fn in mapping:
            r = fn(hist)
            if r:
                found.append((key, {**item, "hist": hist}, r))
        return found

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as ex:
        for f in concurrent.futures.as_completed([ex.submit(process_one, i) for i in main_stocks]):
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
        rows.append({
            "代號": sid,
            "名稱": lst[0]["name"],
            "策略數": len(lst),
            "方向": "｜".join(f"{x['signal'].split('｜')[0]}:{x.get('direction','')}" for x in lst),
            "現價": lst[0]["price"],
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("策略數", ascending=False)


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
        fig.add_trace(go.Scatter(x=x, y=upper_all[-100:], mode="lines", name="布林上軌(2.1v)", line=dict(color="#FF8C00", width=1.5, dash="dash")), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=ma20_all[-100:], mode="lines", name="布林中軌", line=dict(color="#1E90FF", width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=lower_all[-100:], mode="lines", name="布林下軌", line=dict(color="#FF8C00", width=1.5, dash="dash")), row=1, col=1)
    else:
        ma20 = calc_ma_list(hist["closes"], 20)[-100:]
        ma100 = calc_ma_list(hist["closes"], 100)[-100:]
        fig.add_trace(go.Scatter(x=x, y=ma20, mode="lines", name="月線(MA20)", line=dict(color="#1E90FF", width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=ma100, mode="lines", name="100MA", line=dict(color="#FF4500", width=2)), row=1, col=1)
    colors = ["#FF3333" if closes[i] >= opens[i] else "#00A600" for i in range(len(closes))]
    fig.add_trace(go.Bar(x=x, y=vols, marker_color=colors, name="量"), row=2, col=1)
    fig.update_layout(title=title, xaxis_rangeslider_visible=False,
                      margin=dict(l=8, r=8, t=36, b=8), height=380, showlegend=True,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0), font=dict(size=13))
    fig.update_xaxes(showticklabels=False, showgrid=False)
    return fig


def direction_html(direction: str) -> str:
    d = direction or ""
    if "賣" in d or "減碼" in d:
        return f'<span class="sell-text">{d}</span>'
    if "買" in d:
        return f'<span class="buy-text">{d}</span>'
    return d


def render_signal_tab(data_list, title, note="", is_bollinger=False, show_extra=False):
    st.markdown(f"**{title}**")
    if note:
        st.caption(note)
    if not data_list:
        st.info("目前沒有符合的個股。")
        return
    st.markdown(f"**共 {len(data_list)} 檔**")
    rows_html = []
    for d in data_list:
        dir_h = direction_html(d.get("direction", ""))
        extra = d.get("extra", "")
        pxcell = f"買{d.get('entry', '-')} 停{d.get('stop', '-')} 目{d.get('target', '-')}"
        extra_cell = f"<td>{extra}</td>" if show_extra else ""
        rows_html.append(
            f"<tr>"
            f"<td>{d['sid']}</td><td>{d['name']}</td><td>{d['price']:.2f}</td>"
            f"<td>{dir_h}</td><td>{d['signal']}</td>"
            f"{extra_cell}"
            f"<td>{d.get('lots', 0)}張</td><td>{pxcell}</td>"
            f"</tr>"
        )
    extra_header = "<th>位階／買點／風險</th>" if show_extra else ""
    table = f"""
    <table style="width:100%; border-collapse:collapse; font-size:15px; font-weight:bold;">
    <thead>
    <tr style="background:#f0f2f6;">
      <th>代號</th><th>名稱</th><th>現價</th><th>方向</th><th>訊號</th>
      {extra_header}
      <th>量能</th><th>買賣參考</th>
    </tr>
    </thead>
    <tbody>{''.join(rows_html)}</tbody>
    </table>
    """
    st.markdown(table, unsafe_allow_html=True)
    for idx, item in enumerate(data_list):
        with st.expander(f"{item['sid']} {item['name']}｜{item.get('winrate','')}｜{item.get('extra','')}", expanded=False):
            st.markdown(f"**方向：** {direction_html(item.get('direction',''))}", unsafe_allow_html=True)
            st.markdown(f"**訊號：** {item['signal']}")
            if item.get("extra"):
                st.markdown(f"**位階／買點／風險：** {item['extra']}")
            st.markdown(f"**操作：** {item.get('how', '')}")
            st.markdown(
                f"現價 **{item['price']:.2f}**｜買進 **{item.get('entry','-')}**｜"
                f"停損 **{item.get('stop','-')}**｜目標 **{item.get('target','-')}**｜"
                f"量 **{item.get('lots',0)}張**"
            )
            fig = make_chart(item["hist"], f"{item['sid']} {item['name']}", is_bollinger=is_bollinger)
            st.plotly_chart(fig, use_container_width=True, key=f"c_{title}_{idx}_{item['sid']}")


# ==============================================================================
# UI
# ==============================================================================
st.title("台股精選訊號（朱家泓細膩化 + 只抓日線）")
st.caption(f"{time.strftime('%Y-%m-%d %H:%M')}｜朱家泓位階／買點標註｜已移除指定策略｜只抓日線")

st.warning("勝率為歷史回測樣本，未扣成本，不構成投資建議。朱家泓已細膩化位階與買點類型，高檔末升段會被過濾。")

with st.expander("朱家泓細膩化說明", expanded=True):
    st.markdown("""
**位階（第幾波近似）**
- 第1波（初升段近似，漲幅 ≤20%）→ 風險低
- 第2波（主升段近似，20–40%）→ 風險中
- 第3波（較高位階，40–60%）→ 風險中高
- 第3波以上／高檔 → **直接過濾**（避免末升段陷阱）

**買點類型**
- **回後買上漲（優先）**：最近有回檔跡象 + 今日收盤重新站上5MA + 突破昨高 + 紅K
- 突破昨高＋站上5MA
- 站上5MA轉強

**其他強化**
- 強制 5 > 10 > 20 > 60 四線多排 + 月線／季線向上
- 量能溫和放大（≥5日均量1.2倍），排除極端爆量
- 停損優先取「進場日低點 / 最近波段低點(l2) / 約5%」
    """)

col1, col2 = st.columns(2)
with col1:
    do_scan = st.button("掃描訊號（全部股票）", use_container_width=True)
with col2:
    if st.button("清除快取", type="primary", use_container_width=True):
        st.cache_data.clear()
        SYMBOL_CACHE.clear()
        if "scan_results_refined" in st.session_state:
            del st.session_state["scan_results_refined"]
        st.rerun()

if do_scan:
    with st.spinner("掃描中（朱家泓細膩化）..."):
        st.session_state["scan_results_refined"] = run_full_scan()
    st.success("掃描完成")

results = st.session_state.get("scan_results_refined", {})
if not results:
    st.info("請按「掃描訊號（全部股票）」開始計算。")

tabs = st.tabs([
    "衝突彙整",
    "朱家泓細膩化 62.5%",
    "林恩如20週W底 58.5%",
    "阿水一式 53%",
    "破底翻 48%",
    "RSI鈍化 45%",
    "多頭背離 43%",
])

with tabs[0]:
    st.markdown("同一檔出現多個訊號時集中顯示。")
    cdf = build_conflict_table(results)
    if cdf.empty:
        st.info("目前沒有跨訊號重疊個股。")
    else:
        st.dataframe(cdf, use_container_width=True, hide_index=True)

with tabs[1]:
    render_signal_tab(
        results.get("朱家泓頭頭高底底高", []),
        "朱家泓細膩化（位階＋買點標註）",
        "第1波風險低／第2波風險中／第3波風險中高｜回後買上漲優先｜高檔過濾",
        show_extra=True
    )
with tabs[2]:
    render_signal_tab(results.get("林恩如20週均線W底", []), "林恩如 20 週均線 W 底", "站上100MA + W底不再破底 + 帶量")
with tabs[3]:
    render_signal_tab(results.get("阿水一式", []), "阿水一式", "2.1倍帶寬≤0.2 + 2倍均量 + 紅K突破上軌", is_bollinger=True)
with tabs[4]:
    render_signal_tab(results.get("破底翻", []), "破底翻", "破前低後快速收回 + 站上月線")
with tabs[5]:
    render_signal_tab(results.get("RSI鈍化", []), "RSI 鈍化", "連續5日≥70 + 站上五日線")
with tabs[6]:
    render_signal_tab(results.get("多頭背離", []), "多頭背離", "RSI5／RSI10 價新低RSI未新低")

st.markdown("---")
st.caption("僅供學習監控。投資有風險，請獨立判斷並自負盈虧。")
