"""
================================================================================
台股精選訊號監控系統（Streamlit 朱家泓貼文件版 + 個股獨立回測勝率）
================================================================================
【核心變更 2026】
1. 移除所有硬編碼勝率（原數字無可靠公開依據）
2. 新增「回測所有個股策略勝率（2年）」獨立功能
3. 每檔個股獨立計算各策略歷史勝率與樣本數，存成 JSON 持久記憶
4. 掃描時只採用該檔勝率 ≥51% 的策略；低於51% 直接過濾
5. 樣本數再少只要發生過就計入，但會明確顯示「發生N次」並標註小樣本風險
6. 回測規則（2026 新版，全策略統一）：
   - 訊號出現後，隔日收盤上漲 ≥ 3% → 算勝
   - 隔日收盤上漲 < 3% → 算敗
   - 樣本數 = 1 也算（只要發生過就計入）
   - 沒有隔日資料則不計入樣本
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

# 策略記憶用 Google 試算表（設成「知道連結的任何人可檢視」即可用 CSV 公開讀取）
# 使用方式：回測完成 → 下載 CSV → 全選貼上覆蓋此試算表 → 之後程式自動讀取
MEMORY_SHEET = {
    "base": "https://docs.google.com/spreadsheets/d/1Ba3vWS9vf2dP9fgPQIp6nJSwYYacNsNPFz7jIAOGhe8",
    "gid": "0",
}

CONFIG = {
    "MIN_VOLUME": 500000,          # 最低成交量過濾
    "MAX_HISTORY": 1000,            # 拉長到約2.5年，確保2年回測足夠
    "BATCH_WORKERS": 200,           # 回測時降低並行，減少 Yahoo 限流  原本20
    "CACHE_TTL": 300,
    "WINRATE_THRESHOLD": 51.0,     # 只有勝率 ≥51% 的策略才會被採用  
    "LOOKAHEAD": 1,               # 回測往後觀察天數 原本15
    "MIN_SAMPLES_WARN": 10,        # 樣本少於此數會標註「小樣本風險」
    # 本地 JSON 僅作備援（Cloud 重啟可能消失）；主要靠 MEMORY_SHEET 持久化
    "MEMORY_FILE": "stock_strategy_memory.json",
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


# ======================== 回測核心（統一：隔日收盤上漲 ≥ 3%） ========================
# 所有策略統一用同一套簡單規則，方便驗證與比較
# 勝：訊號日收盤後，隔日收盤上漲 ≥ 3%
# 敗：隔日收盤上漲 < 3%
# 樣本數 = 1 也算（只要發生過就計入）

def evaluate_strategy_outcome(strategy_key, hist, entry_idx, signal_result):
    """
    統一評估規則（2026 新版）：
    - 訊號出現在 entry_idx（以當日收盤價為基準）
    - 看隔日（entry_idx + 1）收盤
    - 若隔日收盤上漲 ≥ 3% → 勝 (True)
    - 若隔日收盤上漲 < 3% → 敗 (False)
    - 若沒有隔日資料 → 不計入樣本 (None)

    次數只要 1 次也算。
    """
    closes = hist["closes"]
    n = len(closes)
    entry_price = float(signal_result["price"])

    next_idx = entry_idx + 1
    if next_idx >= n:
        return None  # 沒有隔日資料，不計入

    next_close = closes[next_idx]
    if next_close is None or entry_price <= 0:
        return None

    ret = next_close / entry_price - 1.0
    return ret >= 0.03  # ≥ 3% 算勝


def backtest_one_stock(item):
    """
    對單一股票做2年回測，回傳各策略的勝率與樣本數。
    結構: {strategy_key: {"winrate": float, "wins": int, "total": int, "samples": int}}

    新規則：訊號出現後，隔日收盤上漲 ≥ 3% 算勝；< 3% 算敗。
    只要發生 1 次也計入樣本。
    沒有隔日資料則不計入。
    """
    hist = get_yahoo_history(item["sid"], max_n=CONFIG["MAX_HISTORY"])
    if hist is None:
        return item["sid"], None

    n = len(hist["closes"])
    results = {}
    # 統一只看隔日，預留 2 天即可
    start_idx = 120
    end_scan = n - 2

    for key, fn in STRATEGY_FUNCS.items():
        wins = 0
        total = 0
        step = 3
        for idx in range(start_idx, max(start_idx + 1, end_scan), step):
            r = fn(hist, end_idx=idx)
            if r is None:
                continue
            outcome = evaluate_strategy_outcome(key, hist, idx, r)
            if outcome is None:
                # 沒有隔日資料 → 不計入樣本
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


def memory_to_dataframe(mem: dict) -> pd.DataFrame:
    """把記憶 dict 轉成扁平 DataFrame，方便下載 CSV 與貼上試算表"""
    rows = []
    for sid, data in sorted(mem.items()):
        name = data.get("name", sid)
        updated = data.get("updated", "")
        for skey, sdata in data.get("strategies", {}).items():
            rows.append({
                "代號": sid,
                "名稱": name,
                "策略": skey,
                "勝率": sdata.get("winrate", 0),
                "樣本數": sdata.get("samples", 0),
                "更新時間": updated,
            })
    if not rows:
        return pd.DataFrame(columns=["代號", "名稱", "策略", "勝率", "樣本數", "更新時間"])
    return pd.DataFrame(rows)


def load_memory_from_public_sheet():
    """
    從公開 Google 試算表（CSV export）讀取策略記憶。
    試算表需設成「知道連結的任何人可檢視」。
    回傳與 JSON 相同結構的 dict，失敗或空資料回傳 None / {}。
    """
    try:
        csv_text = fetch_sheet_csv(MEMORY_SHEET["base"], MEMORY_SHEET["gid"])
        if not csv_text or len(csv_text.strip()) < 10:
            return {}
        df = pd.read_csv(io.StringIO(csv_text))
        # 欄位容錯：名稱模糊比對 + 固定欄序備援
        # 預期欄序：代號,名稱,策略,勝率,樣本數,更新時間
        col_map = {}
        for c in df.columns:
            c_str = str(c).strip().replace("%", "").replace(" ", "")
            if c_str in ("代號", "sid", "股票代號", "代碼"):
                col_map["sid"] = c
            elif c_str in ("名稱", "name", "股票名稱"):
                col_map["name"] = c
            elif "策略" in c_str or c_str in ("strategy", "訊號"):
                col_map["strategy"] = c
            elif "勝率" in c_str or c_str in ("winrate",):
                col_map["winrate"] = c
            elif "樣本" in c_str or c_str in ("samples", "N", "次數", "樣本數N"):
                col_map["samples"] = c
            elif "更新" in c_str or c_str in ("updated", "時間"):
                col_map["updated"] = c
        cols = list(df.columns)
        if "sid" not in col_map and len(cols) >= 1:
            col_map["sid"] = cols[0]
        if "name" not in col_map and len(cols) >= 2:
            col_map["name"] = cols[1]
        if "strategy" not in col_map and len(cols) >= 3:
            col_map["strategy"] = cols[2]
        if "winrate" not in col_map and len(cols) >= 4:
            col_map["winrate"] = cols[3]
        if "samples" not in col_map and len(cols) >= 5:
            col_map["samples"] = cols[4]
        if "updated" not in col_map and len(cols) >= 6:
            col_map["updated"] = cols[5]
        if "sid" not in col_map or "strategy" not in col_map:
            return {}

        mem = {}
        for _, row in df.iterrows():
            sid = str(row[col_map["sid"]]).strip()
            if not sid or sid.lower() == "nan":
                continue
            if sid.endswith(".0") and sid[:-2].replace(".", "").isdigit():
                sid = sid[:-2]
            name = str(row[col_map["name"]]).strip() if "name" in col_map else sid
            if name.lower() == "nan":
                name = sid
            strategy = str(row[col_map["strategy"]]).strip()
            if not strategy or strategy.lower() == "nan":
                continue
            try:
                wr = float(row[col_map["winrate"]]) if "winrate" in col_map else 0.0
            except Exception:
                wr = 0.0
            try:
                samples = int(float(row[col_map["samples"]])) if "samples" in col_map else 0
            except Exception:
                samples = 0
            # 樣本為 0 時勝率視為無效，避免出現「100% 但 N=0 還可用」
            if samples <= 0:
                wr = 0.0
            updated = str(row[col_map["updated"]]).strip() if "updated" in col_map else ""
            if updated.lower() == "nan":
                updated = ""

            if sid not in mem:
                mem[sid] = {"name": name, "updated": updated, "strategies": {}}
            mem[sid]["strategies"][strategy] = {
                "winrate": wr,
                "wins": 0,
                "total": samples,
                "samples": samples,
            }
            if updated and (not mem[sid].get("updated") or updated > mem[sid]["updated"]):
                mem[sid]["updated"] = updated
                mem[sid]["name"] = name
        return mem
    except Exception:
        return None


def load_memory():
    """
    優先順序：
    1. 公開 Google 試算表（MEMORY_SHEET）← 主要持久化方式
    2. 本地 JSON（備援）
    3. 空 dict
    """
    gmem = load_memory_from_public_sheet()
    if gmem is not None and len(gmem) > 0:
        return gmem

    path = CONFIG["MEMORY_FILE"]
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data:
                    return data
        except Exception:
            pass
    return {}


def save_memory(mem):
    """
    本地 JSON 盡力寫入（Cloud 可能失敗）；真正持久化靠使用者下載 CSV 貼到試算表。
    回傳是否成功寫入本地。
    """
    path = CONFIG["MEMORY_FILE"]
    try:
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.warning(f"寫入本地記憶檔失敗（不影響本次 session，請用下方「下載記憶 CSV」保存）：{e}")
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
            # 必須：有記憶、樣本>0、勝率≥門檻
            if not stats or key not in stats:
                continue
            wr = float(stats[key].get("winrate", 0) or 0)
            samples = int(stats[key].get("samples", 0) or 0)
            if samples <= 0 or wr < CONFIG["WINRATE_THRESHOLD"]:
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
1. 點「**回測所有個股策略勝率（2年）**」  
2. 等待完成（約 1000+ 檔，可能需數分鐘～十幾分鐘）  
3. **立刻按「下載記憶 CSV」** → 開啟你的記憶試算表 → 全選刪除舊資料 → 貼上覆蓋並保存  
4. 接著按「掃描訊號」即可使用  

**記憶試算表（請設成「知道連結的任何人可檢視」）：**  
https://docs.google.com/spreadsheets/d/1Ba3vWS9vf2dP9fgPQIp6nJSwYYacNsNPFz7jIAOGhe8  

**之後 Cloud 重啟／換裝置：**  
程式會自動用公開 CSV 讀取上述試算表，不必重跑回測（只要你有貼過最新 CSV）。

**平常操作：**
1. 直接點「掃描訊號（全部股票）」  
2. 只顯示該檔勝率 ≥ {CONFIG['WINRATE_THRESHOLD']}% 的策略  
3. 表格會顯示「個股勝率（樣本N）」；N 較小時標【小樣本】

**回測規則（全策略統一，2026 新版）：**
- 資料區間：約2年日線｜進場基準：訊號日收盤價  
- **勝**：訊號出現後，隔日收盤上漲 ≥ 3%  
- **敗**：隔日收盤上漲 < 3%  
- 樣本數只要 1 次也算  
- 沒有隔日資料 → 不計入樣本  
- 掃描間隔 step=3  

**調整方法：**
- 想改門檻：修改 CONFIG["WINRATE_THRESHOLD"]  
- 想改勝率門檻：修改 CONFIG["WINRATE_THRESHOLD"]  
- 想改小樣本警示：修改 CONFIG["MIN_SAMPLES_WARN"]  
    """)

col1, col2, col3, col4 = st.columns(4)
with col1:
    do_scan = st.button("掃描訊號（全部股票）", use_container_width=True)
with col2:
    do_backtest = st.button("回測所有個股策略勝率（2年）", type="primary", use_container_width=True)
with col3:
    if st.button("從試算表重新載入記憶", use_container_width=True):
        st.cache_data.clear()  # 清掉 CSV 快取，強制重抓
        fresh = load_memory_from_public_sheet()
        if fresh is not None and len(fresh) > 0:
            st.session_state["strategy_memory"] = fresh
            st.success(f"已從試算表載入 {len(fresh)} 檔記憶")
        else:
            st.warning("試算表無資料或讀取失敗，請確認已貼上 CSV 且設為「知道連結可檢視」")
        st.rerun()
with col4:
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
            st.session_state["strategy_memory"] = mem
            memory = mem
            st.success(f"回測完成並已更新記憶，共 {len(mem)} 檔。")
            st.warning(
                "【重要】請立刻下載下方 CSV，開啟你的記憶試算表 → 全選清空 → 貼上覆蓋。"
                "這樣 Cloud 重啟後程式才能自動讀回記憶，不必重跑回測。"
            )
            df_dl = memory_to_dataframe(mem)
            st.download_button(
                label="⬇️ 下載記憶 CSV（請貼到 Google 試算表保存）",
                data=df_dl.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"strategy_memory_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.error("回測失敗或無資料")

# 每次都從 session_state 重新取得最新記憶
memory = st.session_state.get("strategy_memory", {})

if do_scan:
    if not memory:
        st.error("尚未建立任何回測記憶。請先按「回測所有個股策略勝率（2年）」，或確認記憶試算表已貼上資料。")
    else:
        with st.spinner("掃描中（僅採用 ≥70% 策略）..."):
            st.session_state["scan_results_doc"] = run_full_scan(memory)
        st.success("掃描完成")

# 顯示記憶狀態
if memory:
    st.caption(
        f"目前記憶共 {len(memory)} 檔個股｜"
        f"來源優先：公開試算表 → 本地 JSON → 本次 session"
    )
else:
    st.info(
        "目前沒有回測記憶。請先執行「回測所有個股策略勝率（2年）」，"
        "或把已下載的 CSV 貼到記憶試算表後重新整理頁面。"
    )

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
                samples = int(sdata.get("samples", 0) or 0)
                wr = float(wr or 0)
                if samples <= 0:
                    flag = "❌無樣本"
                elif wr >= CONFIG["WINRATE_THRESHOLD"]:
                    flag = "✅可用"
                    if samples < CONFIG["MIN_SAMPLES_WARN"]:
                        flag += "【小樣本】"
                else:
                    flag = "❌過濾"
                    if samples < CONFIG["MIN_SAMPLES_WARN"]:
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
