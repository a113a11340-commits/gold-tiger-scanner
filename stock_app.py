"""
================================================================================
台股精選訊號監控系統（Streamlit v8.1）
================================================================================
【買進】
1. 周線多頭 + 三白兵          48.8%
2. 破底翻                     48.2%
3. 周線多頭 + 黏合後打開 + 晨星 46.3%
4. 周線多頭 + 爆量 + 三白兵    45.7%
5. RSI 鈍化                   45.6%
6. 一次／二度多頭背離（RSI5、RSI10）  底背離歷史約 43.4%

【賣出】僅保留勝率最高
1. RSI 頂背離（RSI5、RSI10，含二度）  54.4%

已刪除：跌破長均線及其他低勝率策略。
勝率為歷史樣本、未扣成本，不構成投資建議。
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

st.set_page_config(layout="wide", page_title="台股精選訊號 v8.1")

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

# 寫死勝率（只顯示百分比）
WINRATE = {
    "三白兵": "48.8%",
    "破底翻": "48.2%",
    "黏合晨星": "46.3%",
    "爆量三白兵": "45.7%",
    "RSI鈍化": "45.6%",
    "多頭背離": "43.4%",
    "頂背離": "54.4%",
}

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


def _pack(sid, name, sheet, hist, price, signal, direction, entry, stop, target, how, side, wr):
    return {
        "sid": sid, "name": name, "sheet": sheet, "hist": hist,
        "price": price, "signal": f"{signal}｜勝率{wr}", "direction": direction,
        "entry": entry, "stop": stop, "target": target, "how": how,
        "side": side, "winrate": wr,
        "lots": int(hist["vols"][-1] // 1000),
    }


# ---------- 買1／4：多頭排列 + 三白兵（可選爆量） ----------
def analyze_bull_sanbaibing(hist, require_volume_surge=False):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma5 = calc_ma_list(closes, 5)
    ma10 = calc_ma_list(closes, 10)
    ma20 = calc_ma_list(closes, 20)
    if None in (ma5[-1], ma10[-1], ma20[-1]):
        return None
    if not (ma5[-1] > ma10[-1] > ma20[-1] and closes[-1] > ma5[-1]):
        return None
    d0, d1, d2 = closes[-1], closes[-2], closes[-3]
    o0, o1, o2 = opens[-1], opens[-2], opens[-3]
    is_san = (
        d0 > o0 and d1 > o1 and d2 > o2 and d0 > d1 > d2 and
        o1 >= min(o2, d2) and o1 <= max(o2, d2) and
        o0 >= min(o1, d1) and o0 <= max(o1, d1)
    )
    if not is_san:
        return None
    avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    volume_surge = avg5_vol > 0 and vols[-1] >= avg5_vol * 1.5
    if require_volume_surge and not volume_surge:
        return None
    if require_volume_surge:
        sig, wr = "均線多頭排列 + 爆量 + 三白兵", WINRATE["爆量三白兵"]
    else:
        # 純三白兵：若同時爆量，讓「爆量三白兵」訊號優先，這裡不重複
        if volume_surge:
            return None
        sig, wr = "均線多頭排列 + 三白兵", WINRATE["三白兵"]
    return {
        "signal": sig, "direction": "買進", "side": "long", "winrate": wr,
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], closes[-1] * 0.97, ma10[-1] * 0.99), 2),
        "target": round(closes[-1] * 1.08, 2),
        "how": "回檔不破 MA10 再買；停損 MA10 下",
        "price": closes[-1],
    }


# ---------- 買3：多頭排列 + 黏合後打開 + 晨星 ----------
def analyze_bull_sticky_morning(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma5 = calc_ma_list(closes, 5)
    ma10 = calc_ma_list(closes, 10)
    ma20 = calc_ma_list(closes, 20)
    if None in (ma5[-1], ma10[-1], ma20[-1], ma5[-3], ma10[-3], ma20[-3]):
        return None
    if not (ma5[-1] > ma10[-1] > ma20[-1] and closes[-1] > ma5[-1]):
        return None
    prev_spread = max(ma5[-3], ma10[-3], ma20[-3]) - min(ma5[-3], ma10[-3], ma20[-3])
    curr_spread = max(ma5[-1], ma10[-1], ma20[-1]) - min(ma5[-1], ma10[-1], ma20[-1])
    sticky = prev_spread / ma20[-3] < 0.025 and curr_spread > prev_spread * 1.5 and ma5[-1] > ma10[-1]
    if not sticky:
        return None
    d0, d2 = closes[-1], closes[-3]
    o0, o1, o2 = opens[-1], opens[-2], opens[-3]
    is_morning = (
        d2 < o2 and abs(closes[-2] - o1) <= (highs[-2] - lows[-2]) * 0.35 and
        d0 > o0 and d0 >= (d2 + o2) / 2
    )
    if not is_morning:
        return None
    return {
        "signal": "均線多頭排列 + 均線黏合後打開 + 晨星",
        "direction": "買進", "side": "long", "winrate": WINRATE["黏合晨星"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], closes[-1] * 0.97, ma10[-1] * 0.99), 2),
        "target": round(closes[-1] * 1.08, 2),
        "how": "晨星＋黏合打開，回檔不破 MA10；停損 MA10 下",
        "price": closes[-1],
    }


# ---------- 買2：破底翻 ----------
def analyze_break_bottom_flip(hist):
    closes, highs, lows, vols = hist["closes"], hist["highs"], hist["lows"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < 800000:
        return None
    prev_low = min(lows[-23:-3])
    if any(l < prev_low * 0.995 for l in lows[-3:]) and closes[-1] > prev_low:
        return {
            "signal": f"破底翻：跌破前低{prev_low:.2f}後站回",
            "direction": "買進", "side": "long", "winrate": WINRATE["破底翻"],
            "entry": round(closes[-1] * 1.005, 2),
            "stop": round(prev_low * 0.985, 2),
            "target": round(closes[-1] * 1.07, 2),
            "how": "站回前低後買，停損前低下約 1.5%",
            "price": closes[-1],
        }
    return None


# ---------- 買5：RSI 鈍化 ----------
def analyze_rsi_passivation(hist):
    closes, vols = hist["closes"], hist["vols"]
    n = len(closes)
    if n < 40 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    rsi = calc_rsi(closes, 14)
    days, level = 5, 70
    if any(r is None or r < level for r in rsi[-days:]):
        return None
    ma5 = calc_ma_list(closes, 5)
    if ma5[-1] is None or ma5[-2] is None or closes[-1] <= ma5[-1] or ma5[-1] <= ma5[-2]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is not None and closes[-1] < ma20[-1]:
        return None
    return {
        "signal": f"RSI鈍化：連續{days}日≥{level}（{rsi[-1]:.1f}）+站上五日線",
        "direction": "買進（順勢）", "side": "long", "winrate": WINRATE["RSI鈍化"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(ma5[-1] * 0.99, closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.06, 2),
        "how": "跌破五日線或 RSI<70 出場，停損約 3%",
        "price": closes[-1],
    }


# ---------- RSI 背離：週期 5 與 10（一次／二度） ----------
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


def _div_pairs_for_period(closes, lows, highs, rsi, look, bull=True):
    """回傳 [(a,b), ...] 背離對；bull=True 多頭（底），False 空頭（頂）。"""
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
    """
    用 RSI(5)、RSI(10) 檢查背離。
    回傳 dict: is_double, periods(list), rsi_txt, last_idx 或 None
    優先：二度 > 一次；若兩邊都有則都標上。
    """
    n = len(closes)
    look = min(80, n - 1)
    near = n - 8
    found_double = []  # (period, last_pair, rsi_last)
    found_single = []
    for period in (5, 10):
        rsi = calc_rsi(closes, period)
        if any(x is None for x in rsi[-50:]):
            continue
        pairs = _div_pairs_for_period(closes, lows, highs, rsi, look, bull=bull)
        if not pairs or pairs[-1][1] < near:
            continue
        last = pairs[-1]
        is_double = False
        if len(pairs) >= 2:
            prev = pairs[-2]
            if prev[1] == last[0] or (last[1] - prev[1] <= 40):
                is_double = True
        item = (period, last, rsi[-1])
        if is_double:
            found_double.append(item)
        else:
            found_single.append(item)
    chosen = found_double if found_double else found_single
    if not chosen:
        return None
    is_double = bool(found_double)
    periods = [p for p, _, _ in chosen]
    rsi_txt = "、".join(f"RSI{p}={rv:.1f}" for p, _, rv in chosen)
    last_idx = max(last for _, last, _ in chosen)[1]
    return {
        "is_double": is_double,
        "periods": periods,
        "rsi_txt": rsi_txt,
        "last_idx": last_idx,
    }


def analyze_bull_divergence(hist):
    """買：一次／二度多頭背離（RSI5、RSI10）"""
    closes, lows, highs, vols = hist["closes"], hist["lows"], hist["highs"], hist["vols"]
    n = len(closes)
    if n < 80 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    info = _best_div(closes, lows, highs, bull=True)
    if not info:
        return None
    tag = "二度多頭背離" if info["is_double"] else "一次多頭背離"
    return {
        "signal": f"{tag}：價新低RSI未新低（{info['rsi_txt']}）",
        "direction": "買進（觀察反轉）", "side": "long", "winrate": WINRATE["多頭背離"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[info["last_idx"]] * 0.98, closes[-1] * 0.96), 2),
        "target": round(closes[-1] * 1.07, 2),
        "how": "二度通常較具參考。停損背離低點下。RSI 用 5 與 10 檢查。",
        "price": closes[-1],
    }


def analyze_top_divergence(hist):
    """賣：僅保留頂背離（RSI5、RSI10，含二度）"""
    closes, lows, highs, vols = hist["closes"], hist["lows"], hist["highs"], hist["vols"]
    n = len(closes)
    if n < 80 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    info = _best_div(closes, lows, highs, bull=False)
    if not info:
        return None
    tag = "二度空頭背離" if info["is_double"] else "一次空頭背離（頂背離）"
    return {
        "signal": f"{tag}：價新高RSI未新高（{info['rsi_txt']}）",
        "direction": "賣出／減碼", "side": "short", "winrate": WINRATE["頂背離"],
        "entry": "-", "stop": "-", "target": round(closes[-1] * 0.95, 2),
        "how": "持有者減碼；空手不追高。RSI 用 5 與 10 檢查。",
        "price": closes[-1],
    }


SIGNAL_KEYS = [
    "三白兵", "破底翻", "黏合晨星", "爆量三白兵", "RSI鈍化", "多頭背離", "頂背離"
]


def run_full_scan():
    results = {k: [] for k in SIGNAL_KEYS}

    def add(key, item, r):
        if not r:
            return
        results[key].append(_pack(
            item["sid"], item["name"], item["sheet"], item["hist"],
            r["price"], r["signal"], r["direction"], r["entry"], r["stop"], r["target"],
            r["how"], r["side"], r["winrate"]
        ))

    main_stocks = load_main_stocks()

    def process_main(item):
        hist = get_yahoo_history(item["sid"])
        if hist is None:
            return []
        item = {**item, "hist": hist}
        found = []
        mapping = [
            ("三白兵", lambda h: analyze_bull_sanbaibing(h, False)),
            ("爆量三白兵", lambda h: analyze_bull_sanbaibing(h, True)),
            ("黏合晨星", analyze_bull_sticky_morning),
            ("破底翻", analyze_break_bottom_flip),
            ("RSI鈍化", analyze_rsi_passivation),
            ("多頭背離", analyze_bull_divergence),
            ("頂背離", analyze_top_divergence),
        ]
        for key, fn in mapping:
            r = fn(hist)
            if r:
                found.append((key, item, r))
        return found

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as ex:
        for f in concurrent.futures.as_completed([ex.submit(process_main, i) for i in main_stocks]):
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
    colors = ["#FF3333" if closes[i] >= opens[i] else "#00A600" for i in range(len(closes))]
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


def render_signal_tab(data_list, title, note=""):
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
        pxcell = f"買{d.get('entry', '-')} 停{d.get('stop', '-')} 目{d.get('target', '-')}"
        rows_html.append(
            f"<tr>"
            f"<td>{d['sid']}</td>"
            f"<td>{d['name']}</td>"
            f"<td>{d['price']:.2f}</td>"
            f"<td>{dir_h}</td>"
            f"<td>{d['signal']}</td>"
            f"<td>{d.get('lots', 0)}張</td>"
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
    <tbody>{''.join(rows_html)}</tbody>
    </table>
    """
    st.markdown(table, unsafe_allow_html=True)
    for idx, item in enumerate(data_list):
        with st.expander(f"{item['sid']} {item['name']}｜{item.get('winrate','')}", expanded=False):
            st.markdown(f"**方向：** {direction_html(item.get('direction',''))}", unsafe_allow_html=True)
            st.markdown(f"**訊號：** {item['signal']}")
            st.markdown(f"**操作：** {item.get('how', '')}")
            st.markdown(
                f"現價 **{item['price']:.2f}**｜買進 **{item.get('entry','-')}**｜"
                f"停損 **{item.get('stop','-')}**｜目標 **{item.get('target','-')}**｜"
                f"量 **{item.get('lots',0)}張**"
            )
            fig = make_chart(item["hist"], f"{item['sid']} {item['name']}")
            st.plotly_chart(fig, use_container_width=True, key=f"c_{title}_{idx}_{item['sid']}")


# ---------- UI ----------
st.title("台股精選訊號 v8.1")
st.caption(f"{time.strftime('%Y-%m-%d %H:%M')}｜買6（含多頭背離）｜賣只留頂背離｜RSI背離用5與10")

st.warning("勝率為歷史隔日收盤樣本，未扣成本，不構成投資建議。跌破長均已移除。")

with st.expander("保留清單", expanded=True):
    st.markdown("""
| 方向 | 訊號 | 歷史勝率 |
|------|------|----------|
| 買 | 均線多頭排列 + 三白兵 | **48.8%** |
| 買 | 破底翻 | **48.2%** |
| 買 | 均線多頭排列 + 黏合後打開 + 晨星 | **46.3%** |
| 買 | 均線多頭排列 + 爆量 + 三白兵 | **45.7%** |
| 買 | RSI 鈍化 | **45.6%** |
| 買 | 一次／二度多頭背離（RSI5、RSI10） | **43.4%** |
| 賣 | RSI 頂背離（RSI5、RSI10，含二度） | **54.4%** |
""")

col1, col2 = st.columns(2)
with col1:
    do_scan = st.button("同步掃描", use_container_width=True)
with col2:
    if st.button("強制刷新", type="primary", use_container_width=True):
        st.cache_data.clear()
        SYMBOL_CACHE.clear()
        st.rerun()

if do_scan or "scan_results_v8" not in st.session_state:
    with st.spinner("掃描中..."):
        st.session_state["scan_results_v8"] = run_full_scan()
    if do_scan:
        st.success("掃描完成")

results = st.session_state.get("scan_results_v8", {})

tabs = st.tabs([
    "衝突彙整",
    "三白兵 48.8%",
    "破底翻 48.2%",
    "黏合晨星 46.3%",
    "爆量三白兵 45.7%",
    "RSI鈍化 45.6%",
    "多頭背離 43.4%",
    "頂背離 54.4%",
])

with tabs[0]:
    st.markdown("同一檔出現多個訊號時集中顯示。買賣相反會標衝突。")
    cdf = build_conflict_table(results)
    if cdf.empty:
        st.info("目前沒有跨訊號重疊個股。")
    else:
        st.dataframe(cdf, use_container_width=True, hide_index=True)

with tabs[1]:
    render_signal_tab(results.get("三白兵", []), "多頭排列 + 三白兵", "歷史勝率 48.8%（樣本偏少）")
with tabs[2]:
    render_signal_tab(results.get("破底翻", []), "破底翻", "歷史勝率 48.2%")
with tabs[3]:
    render_signal_tab(results.get("黏合晨星", []), "多頭排列 + 黏合打開 + 晨星", "歷史勝率 46.3%（樣本偏少）")
with tabs[4]:
    render_signal_tab(results.get("爆量三白兵", []), "多頭排列 + 爆量 + 三白兵", "歷史勝率 45.7%（樣本偏少）")
with tabs[5]:
    render_signal_tab(results.get("RSI鈍化", []), "RSI 鈍化", "歷史勝率 45.6%")
with tabs[6]:
    render_signal_tab(
        results.get("多頭背離", []),
        "一次／二度多頭背離",
        "RSI(5) 與 RSI(10) 檢查｜訊號會標一次或二度｜歷史底背離約 43.4%",
    )
with tabs[7]:
    render_signal_tab(
        results.get("頂背離", []),
        "RSI 頂背離（唯一賣出）",
        "RSI(5) 與 RSI(10) 檢查｜含二度｜歷史勝率 54.4%",
    )

st.markdown("---")
st.caption("僅供學習監控。投資有風險，請獨立判斷並自負盈虧。")
