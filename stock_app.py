"""
================================================================================
台股精選訊號監控系統（Streamlit 朱家泓貼文件版 + 個股獨立回測勝率）
================================================================================
【核心變更 2026】
1. 移除所有硬編碼勝率（原數字無可靠公開依據）
2. 新增「回測所有個股策略勝率（2年）」獨立功能
3. 每檔個股獨立計算各策略歷史勝率與樣本數，存成 JSON 持久記憶
4. 掃描時只採用該檔勝率 ≥70% 的策略；低於70% 直接過濾
5. 樣本數再少只要發生過就計入，但會明確顯示「發生N次」並標註小樣本風險
6. 回測定義（可調整）：
   - 訊號日收盤視為進場價
   - 使用當日策略計算的停損 / 目標
   - 往後最多 LOOKAHEAD=15 個交易日
   - 先碰到目標價 → 勝；先碰到停損 → 敗
   - 都沒碰到 → 以第15日收盤相對進場價正負判斷
7. 中文詳細註解、完整使用步驟見檔案底部與 UI 說明

【朱家泓完全對齊文件】
1. 四線多排 5>10>20>60 + 月線／季線向上
2. 真正 swing 頭頭高底底高（L1→H1→L2→H2 時間順序）
3. 位階用實際波數 + 距離60MA
4. 回後買上漲（優先，嚴格）
5. 量能：≥1.2倍均量，排除 >3.5倍高潮
6. 停損：當日低點 / 最近波段低點(l2) / 約5~6%

【保留】林恩如、阿水一式、破底翻、RSI鈍化、多頭背離
================================================================================
"""

import streamlit as st
import pandas as pd
import requests
import io
import time
import concurrent.futures
import numpy as np
import json
import os
from plotly.subplots import make_subplots
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(layout="wide", page_title="台股精選訊號（個股獨立回測版）")

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
.small-sample { color: #E65100 !important; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ======================== 設定區 ========================
MAIN_SHEET = {
    "base": "https://docs.google.com/spreadsheets/d/13Mv-7uaFyR1KcxNRVrhxCGAAntElKprB7ZeWWBxS3n0",
    "gid": "0",
}

CONFIG = {
    "MIN_VOLUME": 500000,          # 最低成交量過濾
    "MAX_HISTORY": 600,            # 拉長到約2.5年，確保2年回測足夠
    "BATCH_WORKERS": 12,           # 回測時降低並行，減少 Yahoo 限流
    "CACHE_TTL": 300,
    "WINRATE_THRESHOLD": 70.0,     # 只有勝率 ≥70% 的策略才會被採用
    "LOOKAHEAD": 15,               # 回測往後觀察天數
    "MIN_SAMPLES_WARN": 10,        # 樣本少於此數會標註「小樣本風險」
    "MEMORY_FILE": "/home/workdir/artifacts/stock_strategy_memory.json",  # 持久記憶檔
}

HTTP_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
HTTP_SESSION.mount("https://", adapter)
HTTP_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
SYMBOL_CACHE = {}  # 記憶 .TW / .TWO 後綴，減少重複嘗試

SIGNAL_KEYS = [
    "林恩如20週均線W底",
    "朱家泓頭頭高底底高",
    "阿水一式",
    "破底翻",
    "RSI鈍化",
    "多頭背離",
]


# ======================== 工具函式 ========================
def calc_ma_list(closes, period):
    """計算移動平均線，回傳與 closes 等長的 list，前面不足處為 None"""
    ma = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        ma[i] = sum(closes[i - period + 1:i + 1]) / period
    return ma


def calc_rsi(closes, period=14):
    """標準 RSI 計算"""
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
    """布林通道"""
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


def swing_indices(values, order, find_min):
    """真正 swing 高低點索引（local min/max）"""
    out = []
    n = len(values)
    for i in range(order, n - order):
        ok = True
        for k in range(i - order, i + order + 1):
            if find_min:
                if values[k] < values[i]:
                    ok = False
                    break
            else:
                if values[k] > values[i]:
                    ok = False
                    break
        if ok:
            out.append(i)
    return out


def get_yahoo_history(sid: str, max_n: int = CONFIG["MAX_HISTORY"], interval: str = "1d"):
    """
    取得日線資料。
    自動嘗試 .TW / .TWO，成功後寫入 SYMBOL_CACHE 永久記憶（本次執行期間）。
    """
    if sid in SYMBOL_CACHE:
        suffixes = [SYMBOL_CACHE[sid]]
    else:
        suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=2y&interval={interval}"
            res = HTTP_SESSION.get(url, timeout=8)
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
                    t_dates.append(time.strftime("%Y-%m-%d", time.localtime(timestamps[i])) if i < len(timestamps) else "")
            if len(t_cls) < 150:
                continue
            SYMBOL_CACHE[sid] = sfx
            if len(t_cls) > max_n:
                t_cls, t_highs, t_lows = t_cls[-max_n:], t_highs[-max_n:], t_lows[-max_n:]
                t_opens, t_vols, t_dates = t_opens[-max_n:], t_vols[-max_n:], t_dates[-max_n:]
            return {"closes": t_cls, "highs": t_highs, "lows": t_lows, "opens": t_opens, "vols": t_vols, "dates": t_dates}
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
    """從 Google 試算表讀取主要股票清單"""
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


def _pack(sid, name, sheet, hist, price, signal, direction, entry, stop, target, how, side, wr_str, extra="", samples=0):
    return {
        "sid": sid, "name": name, "sheet": sheet, "hist": hist,
        "price": price, "signal": signal, "direction": direction,
        "entry": entry, "stop": stop, "target": target, "how": how,
        "side": side, "winrate_str": wr_str, "extra": extra,
        "lots": int(hist["vols"][-1] // 1000) if hist and hist.get("vols") else 0,
        "samples": samples,
    }


# ======================== 策略函式（支援 end_idx，方便回測） ========================
def analyze_chujiahung_doc(hist, end_idx=None):
    """
    朱家泓貼文件版（嚴格）
    end_idx=None 表示用最新一根；回測時傳入歷史索引。
    回傳 dict 或 None。
    """
    closes = hist["closes"]
    highs = hist["highs"]
    lows = hist["lows"]
    opens = hist["opens"]
    vols = hist["vols"]
    n = len(closes)
    if end_idx is None:
        end_idx = n - 1
    if end_idx < 120 or vols[end_idx] < CONFIG["MIN_VOLUME"] or closes[end_idx] < 15:
        return None

    # 只取到 end_idx 的資料做計算，避免前視偏差
    c = closes[:end_idx + 1]
    h = highs[:end_idx + 1]
    l = lows[:end_idx + 1]
    o = opens[:end_idx + 1]
    v = vols[:end_idx + 1]
    nn = len(c)

    ma5 = calc_ma_list(c, 5)
    ma10 = calc_ma_list(c, 10)
    ma20 = calc_ma_list(c, 20)
    ma60 = calc_ma_list(c, 60)
    if None in (ma5[-1], ma10[-1], ma20[-1], ma60[-1]):
        return None

    # 1. 四線多排
    if not (ma5[-1] > ma10[-1] > ma20[-1] > ma60[-1]):
        return None
    # 2. 月線、季線向上
    if ma20[-1] <= ma20[-5] or ma60[-1] <= ma60[-5]:
        return None
    # 3. 站上月線
    if c[-1] <= ma20[-1]:
        return None
    # 4. 距離60MA 控制位階
    dist60 = (c[-1] - ma60[-1]) / ma60[-1]
    if dist60 > 0.45:
        return None

    # 5. 真正 swing 頭頭高底底高
    look = min(90, nn)
    slice_low = l[-look:]
    slice_high = h[-look:]
    low_swings_rel = swing_indices(slice_low, 4, True)
    high_swings_rel = swing_indices(slice_high, 4, False)
    if len(low_swings_rel) < 2 or len(high_swings_rel) < 2:
        return None

    base = nn - look
    l1_idx = base + low_swings_rel[-2]
    l2_idx = base + low_swings_rel[-1]
    h1_idx = base + high_swings_rel[-2]
    h2_idx = base + high_swings_rel[-1]

    if not (l1_idx < h1_idx < l2_idx < h2_idx):
        return None
    l1v, l2v = l[l1_idx], l[l2_idx]
    h1v, h2v = h[h1_idx], h[h2_idx]
    if not (l2v > l1v and h2v > h1v):
        return None

    wave_count = len(low_swings_rel)

    if wave_count <= 2 and dist60 <= 0.25:
        wave_label = f"第{wave_count}波（初升／低位階）"
        risk = "風險低"
    elif wave_count <= 3 and dist60 <= 0.35:
        wave_label = f"第{wave_count}波（主升近似）"
        risk = "風險中"
    elif wave_count <= 4 and dist60 <= 0.45:
        wave_label = f"第{wave_count}波（較高位階）"
        risk = "風險中高"
    else:
        return None

    # 7. 實體紅K
    body = c[-1] - o[-1]
    if body <= 0:
        return None
    upper_shadow = h[-1] - max(c[-1], o[-1])
    lower_shadow = min(c[-1], o[-1]) - l[-1]
    if body < (upper_shadow + lower_shadow) * 1.15:
        return None

    # 8. 量能
    avg5 = sum(v[-6:-1]) / 5 if nn >= 6 else 0
    if avg5 <= 0 or v[-1] < avg5 * 1.2 or v[-1] > avg5 * 3.5:
        return None

    # 9. 回後買上漲判斷
    pullback_ok = l2v >= l1v and l[-1] >= l2v * 0.98 and l[-1] >= ma20[-1] * 0.97
    reclaim_5ma = c[-1] > ma5[-1]
    break_yest_high = c[-1] > h[-2]
    had_pullback = False
    for i in range(-6, -1):
        if c[i] < ma5[i] or l[i] <= ma20[i] * 1.01:
            had_pullback = True
            break

    if had_pullback and pullback_ok and reclaim_5ma and break_yest_high:
        buy_type = "回後買上漲（優先）"
    elif reclaim_5ma and break_yest_high:
        buy_type = "突破昨高＋站上5MA"
    elif reclaim_5ma:
        buy_type = "站上5MA轉強"
    else:
        return None

    stop_price = min(l[-1], l2v, c[-1] * 0.94)

    signal_txt = f"朱家泓貼文件｜{wave_label}｜{buy_type}｜{risk}"
    how_txt = (
        f"{wave_label}｜{buy_type}｜"
        f"停損取當日低點/波段低點(l2)/約5~6%｜"
        f"跌破5MA減碼；無法維持頭頭高則離場"
    )

    return {
        "signal": signal_txt,
        "direction": "買進",
        "side": "long",
        "entry": round(c[-1] * 1.005, 2),
        "stop": round(stop_price, 2),
        "target": round(c[-1] * 1.12, 2),
        "how": how_txt,
        "price": c[-1],
        "extra": f"{wave_label}｜{buy_type}｜{risk}",
    }


def analyze_lin_20w_w_bottom(hist, end_idx=None):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if end_idx is None:
        end_idx = n - 1
    if end_idx < 150 or vols[end_idx] < CONFIG["MIN_VOLUME"]:
        return None
    c = closes[:end_idx + 1]
    h = highs[:end_idx + 1]
    l = lows[:end_idx + 1]
    o = opens[:end_idx + 1]
    v = vols[:end_idx + 1]
    nn = len(c)
    ma20 = calc_ma_list(c, 20)
    ma100 = calc_ma_list(c, 100)
    if None in (ma20[-1], ma100[-1]) or c[-1] <= ma100[-1] or c[-1] <= ma20[-1]:
        return None
    recent_lows = l[-50:]
    if min(recent_lows[25:]) < min(recent_lows[:25]) * 0.99:
        return None
    avg5_vol = sum(v[-6:-1]) / 5 if nn >= 6 else 0
    if not (avg5_vol > 0 and v[-1] >= avg5_vol * 1.3 and c[-1] > o[-1]):
        return None
    return {
        "signal": "林恩如20週均線W底：站上100MA+W底不再破底+站上月線帶量",
        "direction": "買進", "side": "long",
        "entry": round(c[-1] * 1.005, 2),
        "stop": round(min(l[-1], ma100[-1] * 0.98), 2),
        "target": round(c[-1] * 1.12, 2),
        "how": "大趨勢100MA向上、W底不破前低、帶量站上月線",
        "price": c[-1], "extra": "",
    }


def analyze_ashui_1(hist, end_idx=None):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if end_idx is None:
        end_idx = n - 1
    if end_idx < 60 or vols[end_idx] < CONFIG["MIN_VOLUME"]:
        return None
    c = closes[:end_idx + 1]
    o = opens[:end_idx + 1]
    v = vols[:end_idx + 1]
    nn = len(c)
    ma20, upper, lower, bandwidth = calc_bollinger_bands(c, period=20, num_std=2.1)
    if None in (ma20[-1], upper[-1], bandwidth[-1]):
        return None
    is_compressed = min(bandwidth[-10:]) <= 0.2
    is_volume_surge = v[-1] >= (sum(v[-6:-1]) / 5) * 2.0
    is_break_upper = c[-1] > upper[-1] and c[-1] > o[-1]
    if not (is_compressed and is_volume_surge and is_break_upper):
        return None
    return {
        "signal": "阿水一式：布林壓縮後帶量突破2.1倍上軌",
        "direction": "買進", "side": "long",
        "entry": round(c[-1] * 1.005, 2),
        "stop": round(min(ma20[-1], c[-1] * 0.95), 2),
        "target": round(c[-1] * 1.12, 2),
        "how": "守20MA或跌幅5%",
        "price": c[-1], "extra": "",
    }


def analyze_break_bottom_flip(hist, end_idx=None):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if end_idx is None:
        end_idx = n - 1
    if end_idx < 60 or vols[end_idx] < CONFIG["MIN_VOLUME"]:
        return None
    c = closes[:end_idx + 1]
    l = lows[:end_idx + 1]
    nn = len(c)
    ma20 = calc_ma_list(c, 20)
    if ma20[-1] is None or c[-1] <= ma20[-1]:
        return None
    recent_low = min(l[-20:-5])
    if l[-1] >= recent_low * 0.98 or c[-1] < recent_low:
        return None
    return {
        "signal": "破底翻：破前低後快速收回+站上月線",
        "direction": "買進", "side": "long",
        "entry": round(c[-1] * 1.005, 2),
        "stop": round(min(l[-5:]), 2),
        "target": round(c[-1] * 1.10, 2),
        "how": "停損近期低點",
        "price": c[-1], "extra": "",
    }


def analyze_rsi_passivation(hist, end_idx=None):
    closes, vols = hist["closes"], hist["vols"]
    n = len(closes)
    if end_idx is None:
        end_idx = n - 1
    if end_idx < 40 or vols[end_idx] < CONFIG["MIN_VOLUME"]:
        return None
    c = closes[:end_idx + 1]
    nn = len(c)
    rsi = calc_rsi(c, 14)
    for i in range(nn - 5, nn):
        if rsi[i] is None or rsi[i] < 70:
            return None
    ma5 = calc_ma_list(c, 5)
    if ma5[-1] is None or ma5[-2] is None:
        return None
    if not (c[-1] > ma5[-1] and ma5[-1] > ma5[-2]):
        return None
    ma20 = calc_ma_list(c, 20)
    if ma20[-1] is not None and c[-1] < ma20[-1]:
        return None
    return {
        "signal": f"RSI鈍化：連續5日≥70（{rsi[-1]:.1f}）+站上五日線",
        "direction": "買進（順勢）", "side": "long",
        "entry": round(c[-1] * 1.005, 2),
        "stop": round(min(ma5[-1] * 0.99, c[-1] * 0.97), 2),
        "target": round(c[-1] * 1.06, 2),
        "how": "跌破五日線或RSI<70出場",
        "price": c[-1], "extra": "",
    }


def analyze_bull_divergence(hist, end_idx=None):
    closes, lows, highs, vols = hist["closes"], hist["lows"], hist["highs"], hist["vols"]
    n = len(closes)
    if end_idx is None:
        end_idx = n - 1
    if end_idx < 90 or vols[end_idx] < CONFIG["MIN_VOLUME"]:
        return None
    c = closes[:end_idx + 1]
    l = lows[:end_idx + 1]
    nn = len(c)
    rsi5 = calc_rsi(c, 5)
    rsi10 = calc_rsi(c, 10)
    if rsi5[-1] is None or rsi10[-1] is None:
        return None
    look = min(60, nn - 1)
    recent_low_idx = nn - 1 - l[-look:].index(min(l[-look:]))
    if recent_low_idx >= nn - 5:
        return None
    if l[-1] >= l[recent_low_idx]:
        return None
    if rsi5[-1] <= rsi5[recent_low_idx] and rsi10[-1] <= rsi10[recent_low_idx]:
        return None
    return {
        "signal": f"多頭背離：價新低RSI未新低（RSI5={rsi5[-1]:.1f}）",
        "direction": "買進（觀察反轉）", "side": "long",
        "entry": round(c[-1] * 1.005, 2),
        "stop": round(min(l[-1] * 0.98, c[-1] * 0.96), 2),
        "target": round(c[-1] * 1.07, 2),
        "how": "停損背離低點下",
        "price": c[-1], "extra": "",
    }


STRATEGY_FUNCS = {
    "林恩如20週均線W底": analyze_lin_20w_w_bottom,
    "朱家泓頭頭高底底高": analyze_chujiahung_doc,
    "阿水一式": analyze_ashui_1,
    "破底翻": analyze_break_bottom_flip,
    "RSI鈍化": analyze_rsi_passivation,
    "多頭背離": analyze_bull_divergence,
}


# ======================== 回測核心 ========================
def evaluate_trade_outcome(hist, entry_idx, entry_price, stop_price, target_price, lookahead=CONFIG["LOOKAHEAD"]):
    """
    評估單筆交易結果。
    回傳: True=勝, False=敗, None=無法判斷（資料不足）
    邏輯：往後看最多 lookahead 天，先碰到目標算勝、先碰到停損算敗；
          都沒碰到則以最後一日收盤價相對進場價判斷。
    """
    closes = hist["closes"]
    highs = hist["highs"]
    lows = hist["lows"]
    n = len(closes)
    end = min(entry_idx + lookahead, n - 1)
    if end <= entry_idx:
        return None

    for i in range(entry_idx + 1, end + 1):
        # 先看低點是否觸及停損
        if lows[i] <= stop_price:
            return False
        # 再看高點是否觸及目標
        if highs[i] >= target_price:
            return True

    # 都沒碰到，用最後收盤判斷
    return closes[end] > entry_price


def backtest_one_stock(item):
    """
    對單一股票做2年回測，回傳各策略的勝率與樣本數。
    結構: {strategy_key: {"winrate": float, "wins": int, "total": int, "samples": int}}
    """
    hist = get_yahoo_history(item["sid"], max_n=CONFIG["MAX_HISTORY"])
    if hist is None:
        return item["sid"], None

    n = len(hist["closes"])
    results = {}
    # 從足夠歷史後開始掃，預留 lookahead 天給結果評估
    start_idx = 120
    end_scan = n - CONFIG["LOOKAHEAD"] - 1

    for key, fn in STRATEGY_FUNCS.items():
        wins = 0
        total = 0
        # 每隔幾天掃一次，降低計算量與重疊訊號
        step = 3
        for idx in range(start_idx, end_scan, step):
            r = fn(hist, end_idx=idx)
            if r is None:
                continue
            outcome = evaluate_trade_outcome(
                hist, idx, r["price"], r["stop"], r["target"]
            )
            if outcome is None:
                continue
            total += 1
            if outcome:
                wins += 1
        if total > 0:
            wr = round(wins / total * 100, 1)
            results[key] = {
                "winrate": wr,
                "wins": wins,
                "total": total,
                "samples": total,
            }
        else:
            results[key] = {
                "winrate": 0.0,
                "wins": 0,
                "total": 0,
                "samples": 0,
            }
    return item["sid"], {
        "name": item["name"],
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "strategies": results,
    }


def load_memory():
    """讀取持久記憶 JSON"""
    path = CONFIG["MEMORY_FILE"]
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_memory(mem):
    """寫入持久記憶"""
    path = CONFIG["MEMORY_FILE"]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"寫入記憶檔失敗: {e}")
        return False


def run_full_backtest():
    """執行全部個股回測並更新記憶"""
    main_stocks = load_main_stocks()
    if not main_stocks:
        st.warning("目前沒有任何股票可回測，請檢查 Google 試算表設定。")
        return {}

    st.info(f"開始回測全部 {len(main_stocks)} 檔（約2年日線），請耐心等候…")
    progress = st.progress(0)
    status = st.empty()
    new_mem = {}
    done = 0
    total = len(main_stocks)

    # 降低並行數，避免 Yahoo 限流
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as ex:
        futures = {ex.submit(backtest_one_stock, item): item for item in main_stocks}
        for f in concurrent.futures.as_completed(futures):
            done += 1
            progress.progress(min(done / total, 1.0))
            status.text(f"已完成 {done}/{total}")
            try:
                sid, data = f.result()
                if data is not None:
                    new_mem[sid] = data
            except Exception:
                pass
            # 每批稍微休息，降低限流風險
            if done % 30 == 0:
                time.sleep(0.8)

    progress.progress(1.0)
    status.text(f"回測完成，共成功 {len(new_mem)} 檔")
    if new_mem:
        save_memory(new_mem)
        st.session_state["strategy_memory"] = new_mem
    return new_mem


def get_stock_strategy_stats(sid, memory):
    """取得某檔股票各策略的勝率資料"""
    if not memory or sid not in memory:
        return {}
    return memory[sid].get("strategies", {})


# ======================== 掃描（只採用 ≥70% 策略） ========================
def run_full_scan(memory):
    results = {k: [] for k in SIGNAL_KEYS}

    def add(key, item, r, wr, samples):
        if not r:
            return
        wr_str = f"{wr:.1f}%（N={samples}）"
        if samples < CONFIG["MIN_SAMPLES_WARN"]:
            wr_str += "【小樣本】"
        results[key].append(_pack(
            item["sid"], item["name"], item["sheet"], item["hist"],
            r["price"], r["signal"], r["direction"], r["entry"], r["stop"], r["target"],
            r["how"], r["side"], wr_str, r.get("extra", ""), samples
        ))

    main_stocks = load_main_stocks()
    if not main_stocks:
        st.warning("目前沒有任何股票可掃描，請檢查 Google 試算表設定。")
        return results

    st.info(f"掃描中（僅採用該檔勝率 ≥{CONFIG['WINRATE_THRESHOLD']}% 的策略），共 {len(main_stocks)} 檔")

    def process_one(item):
        hist = get_yahoo_history(item["sid"], interval="1d")
        if hist is None:
            return []
        found = []
        stats = get_stock_strategy_stats(item["sid"], memory)
        for key, fn in STRATEGY_FUNCS.items():
            # 若有記憶且該策略勝率 < 門檻，直接跳過
            if stats and key in stats:
                wr = stats[key].get("winrate", 0)
                samples = stats[key].get("samples", 0)
                if wr < CONFIG["WINRATE_THRESHOLD"]:
                    continue
            else:
                # 沒有回測資料的股票，暫時不採用任何策略（強制先回測）
                continue

            r = fn(hist)  # 最新訊號
            if r:
                found.append((key, {**item, "hist": hist}, r, wr, samples))
        return found

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG["BATCH_WORKERS"]) as ex:
        for f in concurrent.futures.as_completed([ex.submit(process_one, i) for i in main_stocks]):
            try:
                for key, item, r, wr, samples in f.result():
                    add(key, item, r, wr, samples)
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
            "代號": sid, "名稱": lst[0]["name"], "策略數": len(lst),
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
        st.info("目前沒有符合的個股（可能因勝率未達70%、尚未回測、或當日無訊號）。")
        return
    st.markdown(f"**共 {len(data_list)} 檔**")
    rows_html = []
    for d in data_list:
        dir_h = direction_html(d.get("direction", ""))
        extra = d.get("extra", "")
        pxcell = f"買{d.get('entry', '-')} 停{d.get('stop', '-')} 目{d.get('target', '-')}"
        wr_display = d.get("winrate_str", "-")
        extra_cell = f"<td>{extra}</td>" if show_extra else ""
        rows_html.append(
            f"<tr><td>{d['sid']}</td><td>{d['name']}</td><td>{d['price']:.2f}</td>"
            f"<td>{dir_h}</td><td>{d['signal']}</td>{extra_cell}"
            f"<td>{wr_display}</td><td>{d.get('lots', 0)}張</td><td>{pxcell}</td></tr>"
        )
    extra_header = "<th>位階／買點／風險</th>" if show_extra else ""
    table = f"""
    <table style="width:100%; border-collapse:collapse; font-size:15px; font-weight:bold;">
    <thead><tr style="background:#f0f2f6;">
      <th>代號</th><th>名稱</th><th>現價</th><th>方向</th><th>訊號</th>
      {extra_header}<th>個股勝率（樣本）</th><th>量能</th><th>買賣參考</th>
    </tr></thead>
    <tbody>{''.join(rows_html)}</tbody></table>
    """
    st.markdown(table, unsafe_allow_html=True)
    for idx, item in enumerate(data_list):
        with st.expander(f"{item['sid']} {item['name']}｜{item.get('winrate_str','')}｜{item.get('extra','')}", expanded=False):
            st.markdown(f"**方向：** {direction_html(item.get('direction',''))}", unsafe_allow_html=True)
            st.markdown(f"**訊號：** {item['signal']}")
            if item.get("extra"):
                st.markdown(f"**位階／買點／風險：** {item['extra']}")
            st.markdown(f"**個股歷史勝率：** {item.get('winrate_str', '-')}")
            st.markdown(f"**操作：** {item.get('how', '')}")
            st.markdown(
                f"現價 **{item['price']:.2f}**｜買進 **{item.get('entry','-')}**｜"
                f"停損 **{item.get('stop','-')}**｜目標 **{item.get('target','-')}**｜"
                f"量 **{item.get('lots',0)}張**"
            )
            fig = make_chart(item["hist"], f"{item['sid']} {item['name']}", is_bollinger=is_bollinger)
            st.plotly_chart(fig, use_container_width=True, key=f"c_{title}_{idx}_{item['sid']}")


# ======================== UI ========================
st.title("台股精選訊號（個股獨立回測勝率版）")
st.caption(f"{time.strftime('%Y-%m-%d %H:%M')}｜每檔個股獨立計算策略勝率｜僅採用 ≥70%｜真正swing頭頭高底底高")

st.warning(
    "【重要風險提示】\n"
    "1. 回測勝率僅供參考，過去表現不代表未來結果。\n"
    "2. 未扣除交易成本、滑價、漲跌停影響。\n"
    "3. 樣本數過少（N < 10）時，高勝率極不可靠，請特別注意【小樣本】標示。\n"
    "4. 本系統不構成任何投資建議，投資有風險，請獨立判斷並自負盈虧。"
)

# 載入記憶
if "strategy_memory" not in st.session_state:
    st.session_state["strategy_memory"] = load_memory()

memory = st.session_state["strategy_memory"]

with st.expander("使用說明與回測規則", expanded=True):
    st.markdown(f"""
**完整使用步驟**

**第一次使用（或想更新股性記憶時）：**
1. 點「**回測所有個股策略勝率（2年）**」按鈕  
2. 等待完成（可能需數分鐘至十幾分鐘，視股票數量與網路狀況）  
3. 完成後會自動寫入本地記憶檔 `{CONFIG['MEMORY_FILE']}`  
4. 之後掃描會自動讀取這份記憶

**平常操作：**
1. 直接點「掃描訊號（全部股票）」  
2. 系統只會顯示「該檔個股在該策略上歷史勝率 ≥ {CONFIG['WINRATE_THRESHOLD']}%」的訊號  
3. 表格會顯示「個股勝率（樣本N）」；若 N 較小會標註【小樣本】

**回測規則（可於程式 CONFIG 調整）：**
- 資料區間：約2年日線  
- 進場：訊號日收盤價  
- 停損 / 目標：使用當日策略計算值  
- 觀察期：往後最多 {CONFIG['LOOKAHEAD']} 個交易日  
- 先碰到目標 → 勝；先碰到停損 → 敗；都沒碰到 → 以第{CONFIG['LOOKAHEAD']}日收盤正負判斷  
- 掃描間隔 step=3（減少重疊訊號與計算量）

**調整方法：**
- 想改門檻：修改 CONFIG["WINRATE_THRESHOLD"]  
- 想改觀察天數：修改 CONFIG["LOOKAHEAD"]  
- 想改小樣本警示門檻：修改 CONFIG["MIN_SAMPLES_WARN"]  
    """)

col1, col2, col3 = st.columns(3)
with col1:
    do_scan = st.button("掃描訊號（全部股票）", use_container_width=True)
with col2:
    do_backtest = st.button("回測所有個股策略勝率（2年）", type="primary", use_container_width=True)
with col3:
    if st.button("清除快取與掃描結果", use_container_width=True):
        st.cache_data.clear()
        SYMBOL_CACHE.clear()
        if "scan_results_doc" in st.session_state:
            del st.session_state["scan_results_doc"]
        st.rerun()

if do_backtest:
    with st.spinner("正在進行全市場個股策略回測（2年），請勿關閉頁面…"):
        mem = run_full_backtest()
        if mem:
            st.success(f"回測完成並已更新記憶，共 {len(mem)} 檔")
        else:
            st.error("回測失敗或無資料")

if do_scan:
    if not memory:
        st.error("尚未建立任何回測記憶，請先按「回測所有個股策略勝率（2年）」建立股性資料。")
    else:
        with st.spinner("掃描中（僅採用 ≥70% 策略）..."):
            st.session_state["scan_results_doc"] = run_full_scan(memory)
        st.success("掃描完成")

# 顯示記憶狀態
if memory:
    st.caption(f"目前記憶檔共 {len(memory)} 檔個股｜最後更新時間以各檔為準")
else:
    st.info("目前沒有回測記憶，請先執行「回測所有個股策略勝率（2年）」。")

results = st.session_state.get("scan_results_doc", {})
if not results and memory:
    st.info("請按「掃描訊號（全部股票）」開始計算（只會出現該檔勝率≥70%的策略）。")

tabs = st.tabs([
    "衝突彙整",
    "朱家泓貼文件",
    "林恩如20週W底",
    "阿水一式",
    "破底翻",
    "RSI鈍化",
    "多頭背離",
    "個股策略記憶總覽",
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
        "朱家泓貼文件版（真正swing + 回後買上漲）",
        "L1→H1→L2→H2｜回後買上漲優先｜高檔過濾｜僅顯示該檔勝率≥70%",
        show_extra=True
    )
with tabs[2]:
    render_signal_tab(results.get("林恩如20週均線W底", []), "林恩如 20 週均線 W 底", "站上100MA + W底不再破底 + 帶量｜僅≥70%")
with tabs[3]:
    render_signal_tab(results.get("阿水一式", []), "阿水一式", "2.1倍帶寬≤0.2 + 2倍均量 + 紅K突破上軌｜僅≥70%", is_bollinger=True)
with tabs[4]:
    render_signal_tab(results.get("破底翻", []), "破底翻", "破前低後快速收回 + 站上月線｜僅≥70%")
with tabs[5]:
    render_signal_tab(results.get("RSI鈍化", []), "RSI 鈍化", "連續5日≥70 + 站上五日線｜僅≥70%")
with tabs[6]:
    render_signal_tab(results.get("多頭背離", []), "多頭背離", "RSI5／RSI10 價新低RSI未新低｜僅≥70%")

with tabs[7]:
    st.markdown("### 個股策略記憶總覽（來自最近一次回測）")
    if not memory:
        st.info("尚無記憶資料。")
    else:
        rows = []
        for sid, data in sorted(memory.items()):
            name = data.get("name", sid)
            updated = data.get("updated", "-")
            for skey, sdata in data.get("strategies", {}).items():
                wr = sdata.get("winrate", 0)
                samples = sdata.get("samples", 0)
                flag = "✅可用" if wr >= CONFIG["WINRATE_THRESHOLD"] else "❌過濾"
                if samples < CONFIG["MIN_SAMPLES_WARN"] and samples > 0:
                    flag += "【小樣本】"
                rows.append({
                    "代號": sid,
                    "名稱": name,
                    "策略": skey,
                    "勝率%": wr,
                    "樣本數N": samples,
                    "狀態": flag,
                    "更新時間": updated,
                })
        if rows:
            dfm = pd.DataFrame(rows)
            st.dataframe(dfm, use_container_width=True, hide_index=True)
            st.download_button(
                "下載記憶總覽 CSV",
                dfm.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"strategy_memory_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )
        else:
            st.info("記憶檔存在但無策略資料。")

st.markdown("---")
st.caption("僅供學習監控。投資有風險，請獨立判斷並自負盈虧。回測有諸多限制，不可作為唯一決策依據。")
