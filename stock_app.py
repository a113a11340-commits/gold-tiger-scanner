"""
================================================================================
台股精選訊號監控系統（Streamlit v28.1 阿水一式帶寬 <= 0.2 正統修正版）
================================================================================
【版本更新說明 v28.1】
1. 修正阿水一式帶寬計算可能因 None 值而報錯的問題（改為安全過濾）
2. 強化 Google 試算表讀取失敗時的錯誤提示
3. 全面加入繁體中文註解與「如何修改」指引，方便後續維護
4. 保持原有 15 策略邏輯、勝率表、衝突彙整排序（衝突：否 在前）
5. 布林通道仍採用 2.1 倍標準差（阿水正統設定）

【如何執行】
1. 安裝必要套件：
   pip install streamlit pandas plotly numpy requests
2. 執行指令：
   streamlit run 台股精選訊號_v28.1_阿水一式修正版.py
3. 瀏覽器會自動開啟網頁介面

【重要可修改參數位置】
- CONFIG 字典：最小成交量、歷史天數、平行執行緒數、快取時間
- MAIN_SHEET：更換股票清單的 Google 試算表網址
- WINRATE：各策略歷史勝率顯示文字
- SIGNAL_KEYS 與 mapping：新增或移除策略
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
# 頁面基本設定
# ==============================================================================
st.set_page_config(layout="wide", page_title="台股精選訊號 v28.1")

# 樣式調整（字體加大、紅買綠賣）
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

# ==============================================================================
# 【可修改區】15 策略勝率對照表
# 說明：這裡只是顯示用文字，不影響實際計算。若要更新勝率數字，直接改字串即可。
# ==============================================================================
WINRATE = {
    "林恩如20週均線W底": "58.5%",
    "朱家泓頭頭高底底高": "57.8%",
    "施昇輝0050樂活KD": "56.5%",
    "資金輪動主流強勢股": "59.2%",
    "阿水一式": "53.5%",
    "貫穿線": "66.0%",
    "三內身": "65.0%",
    "大K棒收回": "68.0%",
    "三白兵": "48.8%",
    "爆量三白兵": "45.7%",
    "黏合晨星": "46.3%",
    "破底翻": "48.2%",
    "RSI鈍化": "45.6%",
    "多頭背離": "43.4%",
    "頂背離": "54.4%",
}

# ==============================================================================
# 【可修改區】雲端股票清單來源
# 說明：請把 Google 試算表設為「任何人擁有連結者皆可檢視」，
#       然後把完整網址貼到 base，gid 通常是 0（第一個工作表）。
# 修改方式：更換 base 與 gid 即可換成自己的清單。
# 清單格式要求：第一欄為股票代號（如 2330），第二欄為股票名稱。
# ==============================================================================
MAIN_SHEET = {
    "base": "https://docs.google.com/spreadsheets/d/13Mv-7uaFyR1KcxNRVrhxCGAAntElKprB7ZeWWBxS3n0",
    "gid": "0",
}

# ==============================================================================
# 【可修改區】系統全域設定
# 說明：這是最常用的調整位置。
# MIN_VOLUME   : 最小成交量（單位：股），預設 50 萬股 = 500 張
# MAX_HISTORY  : 抓取歷史資料天數，建議 250~300 天（支援 100MA）
# BATCH_WORKERS: 同時抓資料的執行緒數，網路慢可調低到 10
# CACHE_TTL    : 資料快取秒數，避免反覆打 Yahoo
# ==============================================================================
CONFIG = {
    "MIN_VOLUME": 500000,      # 最小成交量限制：預設 500,000（500張）
    "MAX_HISTORY": 300,        # 拉長歷史資料天數至 300 天，支援 100MA 與多月波段型態
    "BATCH_WORKERS": 20,       # 多執行緒平行處理數量
    "CACHE_TTL": 300,          # 資料快取時間（秒）
}

# HTTP 連線池設定（提高穩定性）
HTTP_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30)
HTTP_SESSION.mount("https://", adapter)
HTTP_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
SYMBOL_CACHE = {}   # 快取股票是 .TW 還是 .TWO


# ==============================================================================
# 技術指標計算函數（共用）
# ==============================================================================
def calc_ma_list(closes, period):
    """計算簡單移動平均線，回傳與 closes 等長的 list（前面為 None）"""
    ma = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        ma[i] = sum(closes[i - period + 1:i + 1]) / period
    return ma


def calc_rsi(closes, period=14):
    """計算 RSI（Wilder 平滑法）"""
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


def calc_kd(highs, lows, closes, n=9):
    """計算 KD 指標（RSV → K → D）"""
    length = len(closes)
    k_list = [None] * length
    d_list = [None] * length
    if length < n:
        return k_list, d_list
    k_val, d_val = 50.0, 50.0
    for i in range(length):
        if i < n - 1:
            continue
        window_high = max(highs[i - n + 1 : i + 1])
        window_low = min(lows[i - n + 1 : i + 1])
        rsv = 50.0 if window_high == window_low else (closes[i] - window_low) / (window_high - window_low) * 100.0
        k_val = (2 / 3) * k_val + (1 / 3) * rsv
        d_val = (2 / 3) * d_val + (1 / 3) * k_val
        k_list[i] = k_val
        d_list[i] = d_val
    return k_list, d_list


def calc_bollinger_bands(closes, period=20, num_std=2.0):
    """
    計算布林通道
    參數：
        period   : 中軌週期（預設 20）
        num_std  : 標準差倍數（阿水一式使用 2.1）
    回傳：ma, upper, lower, bandwidth
    bandwidth = (上軌 - 下軌) / 中軌
    """
    n = len(closes)
    ma = calc_ma_list(closes, period)
    upper = [None] * n
    lower = [None] * n
    bandwidth = [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        m = ma[i]
        std = np.std(window)          # 預設為母體標準差（ddof=0）
        u = m + num_std * std
        l = m - num_std * std
        upper[i] = u
        lower[i] = l
        bandwidth[i] = (u - l) / m if m > 0 else 0
    return ma, upper, lower, bandwidth


# ==============================================================================
# 資料抓取相關函數
# ==============================================================================
def get_yahoo_history(sid: str, max_n: int = CONFIG["MAX_HISTORY"]):
    """
    從 Yahoo Finance 抓取台股日線資料
    優先使用快取的後綴（.TW 或 .TWO），失敗則嘗試另一個。
    回傳 dict 包含 closes, highs, lows, opens, vols, dates
    """
    if sid in SYMBOL_CACHE:
        suffixes = [SYMBOL_CACHE[sid]]
    else:
        suffixes = [".TW", ".TWO"]
    for sfx in suffixes:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}{sfx}?range=2y&interval=1d"
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
            if len(t_cls) < 150:          # 資料太少就跳過
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
    """從 Google 試算表匯出 CSV（有快取）"""
    csv_url = f"{base_url}/export?format=csv&gid={gid}"
    res = HTTP_SESSION.get(csv_url, timeout=15)
    res.encoding = "utf-8"
    return res.text


def load_main_stocks():
    """
    載入主要股票清單
    修改方式：若想改成讀取本機 CSV，可在此改寫邏輯。
    """
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
            # 簡單過濾非數字代號
            if not sid.replace(".", "").replace("-", "").isdigit() or len(sid) < 4:
                continue
            sid = str(int(float(sid))) if "." in sid else sid
            name = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else sid
            tasks.append({"sid": sid, "name": name, "sheet": "主要清單", "short_n": 20, "long_n": 100})
    except Exception as e:
        st.error(f"讀取主要股票清單失敗: {e}")
        st.warning(
            "請確認 Google 試算表已設為「任何人擁有連結者皆可檢視」，"
            "或到程式碼 MAIN_SHEET 區更換正確的網址。"
        )
    return tasks


def _pack(sid, name, sheet, hist, price, signal, direction, entry, stop, target, how, side, wr):
    """把策略結果打包成統一格式"""
    return {
        "sid": sid, "name": name, "sheet": sheet, "hist": hist,
        "price": price, "signal": f"{signal}｜勝率{wr}", "direction": direction,
        "entry": entry, "stop": stop, "target": target, "how": how,
        "side": side, "winrate": wr,
        "lots": int(hist["vols"][-1] // 1000),
    }


# ==============================================================================
# 15 大策略函數定義
# 說明：每個函數接收 hist（歷史資料 dict），符合條件則回傳結果 dict，否則回傳 None。
# 修改方式：想調整條件就改對應的 if 判斷即可。
# ==============================================================================
def analyze_lin_20w_w_bottom(hist):
    """林恩如 20 週均線 W 底"""
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
        "how": "林恩如四大法寶：大趨勢100MA向上、W底打底不破前低、帶量站上月線表態",
        "price": closes[-1],
    }


def analyze_chujiahung_bottom(hist):
    """朱家泓 頭頭高底底高"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 100 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None or closes[-1] <= ma20[-1]:
        return None
    recent_lows = lows[-60:]
    early_min, late_min = min(recent_lows[:30]), min(recent_lows[30:])
    recent_highs = highs[-60:]
    early_max, late_max = max(recent_highs[:30]), max(recent_highs[30:])
    if not (late_min >= early_min and late_max >= early_max):
        return None
    avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    if not (avg5_vol > 0 and vols[-1] >= avg5_vol * 1.2 and closes[-1] > opens[-1]):
        return None
    return {
        "signal": "朱家泓頭頭高底底高：形成頭頭高底底高多頭結構+站上月線帶量",
        "direction": "買進", "side": "long", "winrate": WINRATE["朱家泓頭頭高底底高"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], ma20[-1] * 0.98), 2),
        "target": round(closes[-1] * 1.12, 2),
        "how": "確認頭頭高、底底高多頭排列，站上月線帶量攻擊",
        "price": closes[-1],
    }


def analyze_shishenghui_kd(hist):
    """施昇輝 0050 樂活 KD"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    k_list, d_list = calc_kd(highs, lows, closes, n=9)
    ma20 = calc_ma_list(closes, 20)
    if None in (k_list[-1], d_list[-1], ma20[-1]):
        return None
    if not (k_list[-1] < 20 and d_list[-1] < 20 and closes[-1] > ma20[-1]):
        return None
    return {
        "signal": f"施昇輝樂活KD：K({k_list[-1]:.1f})與D({d_list[-1]:.1f})跌破20且站上月線",
        "direction": "買進（逢低佈局）", "side": "long", "winrate": WINRATE["施昇輝0050樂活KD"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(closes[-1] * 0.93, 2),
        "target": round(closes[-1] * 1.12, 2),
        "how": "樂活大叔逢低買進波段點，KD<20且站上月線分批佈局",
        "price": closes[-1],
    }


def analyze_lin_sector_rotation(hist):
    """資金輪動主流強勢股"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 100 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma20, ma100 = calc_ma_list(closes, 20), calc_ma_list(closes, 100)
    if None in (ma20[-1], ma100[-1]) or closes[-1] <= ma100[-1] or closes[-1] <= ma20[-1]:
        return None
    recent_high_60 = max(highs[-60:])
    is_near_high = closes[-1] >= recent_high_60 * 0.97
    avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    is_volume_surge = avg5_vol > 0 and vols[-1] >= avg5_vol * 1.5
    if not (is_near_high and is_volume_surge and closes[-1] > opens[-1]):
        return None
    return {
        "signal": "資金輪動主流強勢股：站上100MA與月線+爆量突破高點",
        "direction": "買進", "side": "long", "winrate": WINRATE["資金輪動主流強勢股"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], ma100[-1] * 0.98), 2),
        "target": round(closes[-1] * 1.15, 2),
        "how": "鎖定主流強勢族群，資金爆量流入突破高點，停損守100MA",
        "price": closes[-1],
    }


# ==============================================================================
# 【阿水一式】嚴格採用：2.1倍標準差 + 帶寬 <= 0.2 + 成交量 >= 2倍均量
# 修改重點：
# 1. 帶寬改為安全過濾 None 後再取 min（避免計算錯誤）
# 2. 條件維持正統：近 10 日內出現過帶寬 <= 0.2
# 3. 成交量 >= 前 5 日均量的 2 倍
# 4. 紅 K 且接近或突破 2.1 倍上軌
# ==============================================================================
def analyze_ashui_1(hist):
    """阿水一式（帶寬壓縮突破）"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None

    # 阿水正統 2.1 倍標準差
    ma20, upper, lower, bandwidth = calc_bollinger_bands(closes, period=20, num_std=2.1)
    if None in (ma20[-1], upper[-1], bandwidth[-1]):
        return None

    # 【修正】安全過濾 None，避免 min() 出錯
    recent_bw = [b for b in bandwidth[-10:] if b is not None]
    if not recent_bw:
        return None
    is_compressed = min(recent_bw) <= 0.2

    # 當日成交量 >= 前 5 日均量的 2 倍
    avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    is_volume_surge = avg5_vol > 0 and vols[-1] >= avg5_vol * 2.0

    # 紅 K 且接近或突破上軌（允許 0.5% 誤差）
    is_break_upper = closes[-1] > opens[-1] and closes[-1] >= upper[-1] * 0.995

    if not (is_compressed and is_volume_surge and is_break_upper):
        return None

    return {
        "signal": f"阿水一式：帶寬壓縮({bandwidth[-1]:.2f}≤0.2)+2倍均量突破2.1倍上軌",
        "direction": "買進", "side": "long", "winrate": WINRATE["阿水一式"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], ma20[-1] * 0.98), 2),
        "target": round(closes[-1] * 1.10, 2),
        "how": "帶寬<=0.2壓縮+2倍均量+紅K突破上軌",
        "price": closes[-1],
    }


def analyze_piercing_line(hist):
    """貫穿線"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None or closes[-1] < ma20[-1]:
        return None
    d0, d1 = closes[-1], closes[-2]
    o0, o1 = opens[-1], opens[-2]
    if not (d1 < o1 and d0 > o0 and o0 < o1 and d0 >= (o1 + d1) / 2):
        return None
    return {
        "signal": "貫穿線：上升趨勢回檔過實體中點且站上月線",
        "direction": "買進", "side": "long", "winrate": WINRATE["貫穿線"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], lows[-2], closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.09, 2),
        "how": "高勝率反轉型態，停損守近期低點",
        "price": closes[-1],
    }


def analyze_three_inside_up(hist):
    """三內身"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None or closes[-1] < ma20[-1]:
        return None
    d0, d1, d2 = closes[-1], closes[-2], closes[-3]
    o0, o1, o2 = opens[-1], opens[-2], opens[-3]
    if not ((d2 < o2) and (d1 > o1) and (o1 >= min(o2, d2)) and (d1 <= max(o2, d2)) and (d0 > o0) and (d0 > d1)):
        return None
    return {
        "signal": "三內身：孕線完成後第三根確認且站上月線",
        "direction": "買進", "side": "long", "winrate": WINRATE["三內身"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], lows[-2], lows[-3], closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.09, 2),
        "how": "孕線後多方表態確認，站上月線",
        "price": closes[-1],
    }


def analyze_power_candle_recovery(hist):
    """大K棒強力收回"""
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
            "direction": "買進", "side": "long", "winrate": WINRATE["大K棒收回"],
            "entry": round(closes[-1] * 1.005, 2),
            "stop": round(min(lows[-1], lows[big_bearish_idx] * 0.98), 2),
            "target": round(closes[-1] * 1.10, 2),
            "how": "恐慌賣壓大陰線被完全收回，停損守大陰線底下",
            "price": closes[-1],
        }
    return None


def analyze_bull_sanbaibing(hist, require_volume_surge=False):
    """三白兵 / 爆量三白兵"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma5, ma10, ma20 = calc_ma_list(closes, 5), calc_ma_list(closes, 10), calc_ma_list(closes, 20)
    if None in (ma5[-1], ma10[-1], ma20[-1]):
        return None
    if not (ma5[-1] > ma10[-1] > ma20[-1] and closes[-1] > ma20[-1]):
        return None
    d0, d1, d2 = closes[-1], closes[-2], closes[-3]
    o0, o1, o2 = opens[-1], opens[-2], opens[-3]
    if not (d0 > o0 and d1 > o1 and d2 > o2 and d0 > d1 > d2):
        return None
    avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    volume_surge = avg5_vol > 0 and vols[-1] >= avg5_vol * 1.5
    if require_volume_surge and not volume_surge:
        return None
    if not require_volume_surge and volume_surge:
        return None
    sig = "均線多頭排列 + 爆量 + 三白兵 + 站上月線" if require_volume_surge else "均線多頭排列 + 三白兵 + 站上月線"
    wr = WINRATE["爆量三白兵"] if require_volume_surge else WINRATE["三白兵"]
    return {
        "signal": sig, "direction": "買進", "side": "long", "winrate": wr,
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], closes[-1] * 0.97, ma10[-1] * 0.99), 2),
        "target": round(closes[-1] * 1.08, 2),
        "how": "回檔不破MA10再買；停損MA10下",
        "price": closes[-1],
    }


def analyze_bull_sticky_morning(hist):
    """黏合晨星"""
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma5, ma10, ma20 = calc_ma_list(closes, 5), calc_ma_list(closes, 10), calc_ma_list(closes, 20)
    if None in (ma5[-1], ma10[-1], ma20[-1], ma5[-3], ma10[-3], ma20[-3]):
        return None
    if not (ma5[-1] > ma10[-1] > ma20[-1] and closes[-1] > ma20[-1]):
        return None
    prev_spread = max(ma5[-3], ma10[-3], ma20[-3]) - min(ma5[-3], ma10[-3], ma20[-3])
    curr_spread = max(ma5[-1], ma10[-1], ma20[-1]) - min(ma5[-1], ma10[-1], ma20[-1])
    if not (prev_spread / ma20[-3] < 0.025 and curr_spread > prev_spread * 1.5 and ma5[-1] > ma10[-1]):
        return None
    return {
        "signal": "均線多頭排列 + 黏合打開 + 晨星 + 站上月線",
        "direction": "買進", "side": "long", "winrate": WINRATE["黏合晨星"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], closes[-1] * 0.97, ma10[-1] * 0.99), 2),
        "target": round(closes[-1] * 1.08, 2),
        "how": "晨星＋黏合打開，回檔不破MA10",
        "price": closes[-1],
    }


def analyze_break_bottom_flip(hist):
    """破底翻"""
    closes, highs, lows, vols = hist["closes"], hist["highs"], hist["lows"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < 800000:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None or closes[-1] < ma20[-1]:
        return None
    prev_low = min(lows[-23:-3])
    if any(l < prev_low * 0.995 for l in lows[-3:]) and closes[-1] > prev_low:
        return {
            "signal": f"破底翻：跌破前低後站回且站上月線",
            "direction": "買進", "side": "long", "winrate": WINRATE["破底翻"],
            "entry": round(closes[-1] * 1.005, 2),
            "stop": round(prev_low * 0.985, 2),
            "target": round(closes[-1] * 1.07, 2),
            "how": "站回前低後買，停損前低下約1.5%",
            "price": closes[-1],
        }
    return None


def analyze_rsi_passivation(hist):
    """RSI 鈍化"""
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
        "direction": "買進（順勢）", "side": "long", "winrate": WINRATE["RSI鈍化"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(ma5[-1] * 0.99, closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.06, 2),
        "how": "跌破五日線或RSI<70出場",
        "price": closes[-1],
    }


def _swing_indices(values, order=3, find_min=True):
    """找出局部高低點索引"""
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
    """尋找背離配對"""
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
    """找出最佳背離（一次或二度）"""
    n = len(closes)
    look = min(80, n - 1)
    near = n - 8
    found_double, found_single = [], []
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
    rsi_txt = "、".join(f"RSI{p}={rv:.1f}" for p, _, rv in chosen)
    last_idx = max(last for _, last, _ in chosen)[1]
    return {"is_double": bool(found_double), "rsi_txt": rsi_txt, "last_idx": last_idx}


def analyze_bull_divergence(hist):
    """多頭背離"""
    closes, lows, highs, vols = hist["closes"], hist["lows"], hist["highs"], hist["vols"]
    if len(closes) < 80 or vols[-1] < CONFIG["MIN_VOLUME"]:
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
        "how": "停損背離低點下。RSI用5與10檢查。",
        "price": closes[-1],
    }


def analyze_top_divergence(hist):
    """頂背離（唯一賣出訊號）"""
    closes, lows, highs, vols = hist["closes"], hist["lows"], hist["highs"], hist["vols"]
    if len(closes) < 80 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    info = _best_div(closes, lows, highs, bull=False)
    if not info:
        return None
    tag = "二度空頭背離" if info["is_double"] else "一次空頭背離（頂背離）"
    return {
        "signal": f"{tag}：價新高RSI未新低（{info['rsi_txt']}）",
        "direction": "賣出／減碼", "side": "short", "winrate": WINRATE["頂背離"],
        "entry": "-", "stop": "-", "target": round(closes[-1] * 0.95, 2),
        "how": "持有者減碼；空手不追高。",
        "price": closes[-1],
    }


# ==============================================================================
# 策略鍵值對映清單（新增策略時記得同步修改這裡）
# ==============================================================================
SIGNAL_KEYS = [
    "林恩如20週均線W底", "朱家泓頭頭高底底高", "施昇輝0050樂活KD", "資金輪動主流強勢股",
    "阿水一式", "貫穿線", "三內身", "大K棒收回", "三白兵", "爆量三白兵",
    "黏合晨星", "破底翻", "RSI鈍化", "多頭背離", "頂背離"
]


def run_full_scan():
    """執行全部 15 策略掃描"""
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
    if not main_stocks:
        st.warning("目前沒有任何股票可掃描，請檢查 Google 試算表設定。")
        return results

    def process_main(item):
        hist = get_yahoo_history(item["sid"])
        if hist is None:
            return []
        item = {**item, "hist": hist}
        found = []
        mapping = [
            ("林恩如20週均線W底", analyze_lin_20w_w_bottom),
            ("朱家泓頭頭高底底高", analyze_chujiahung_bottom),
            ("施昇輝0050樂活KD", analyze_shishenghui_kd),
            ("資金輪動主流強勢股", analyze_lin_sector_rotation),
            ("阿水一式", analyze_ashui_1),
            ("貫穿線", analyze_piercing_line),
            ("三內身", analyze_three_inside_up),
            ("大K棒收回", analyze_power_candle_recovery),
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
    """建立衝突彙整表（衝突：否 排在前面）"""
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
    # 衝突「否」在前面，「是」在後面
    return pd.DataFrame(rows).sort_values(["衝突", "策略數"], ascending=[True, False])


# ==============================================================================
# 圖表繪製函數（阿水一式採用 2.1 倍布林軌道）
# ==============================================================================
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
        # 阿水一式專用：使用 2.1 倍標準差繪製布林通道
        _, upper_all, lower_all, _ = calc_bollinger_bands(hist["closes"], period=20, num_std=2.1)
        ma20_all = calc_ma_list(hist["closes"], 20)
        upper = upper_all[-100:]
        lower = lower_all[-100:]
        ma20 = ma20_all[-100:]

        fig.add_trace(go.Scatter(x=x, y=upper, mode="lines", name="布林上軌(2.1σ)", line=dict(color="#FF8C00", width=1.5, dash="dash")), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=ma20, mode="lines", name="布林中軌(MA20)", line=dict(color="#1E90FF", width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=lower, mode="lines", name="布林下軌(2.1σ)", line=dict(color="#FF8C00", width=1.5, dash="dash")), row=1, col=1)
    else:
        # 其他策略：顯示月線與 100MA
        ma20 = calc_ma_list(hist["closes"], 20)[-100:]
        ma100 = calc_ma_list(hist["closes"], 100)[-100:]
        fig.add_trace(go.Scatter(x=x, y=ma20, mode="lines", name="月線(MA20)", line=dict(color="#1E90FF", width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=ma100, mode="lines", name="100MA(20週)", line=dict(color="#FF4500", width=2)), row=1, col=1)

    colors = ["#FF3333" if closes[i] >= opens[i] else "#00A600" for i in range(len(closes))]
    fig.add_trace(go.Bar(x=x, y=vols, marker_color=colors, name="量"), row=2, col=1)
    fig.update_layout(title=title, xaxis_rangeslider_visible=False,
                      margin=dict(l=8, r=8, t=36, b=8), height=380, showlegend=True,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                      font=dict(size=14))
    fig.update_xaxes(showticklabels=False, showgrid=False)
    return fig


def direction_html(direction: str) -> str:
    """方向文字加上顏色"""
    d = direction or ""
    if "賣" in d or "減碼" in d:
        return f'<span class="sell-text">{d}</span>'
    if "買" in d:
        return f'<span class="buy-text">{d}</span>'
    return d


def render_signal_tab(data_list, title, note="", is_bollinger=False):
    """渲染單一策略分頁"""
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
            fig = make_chart(item["hist"], f"{item['sid']} {item['name']}", is_bollinger=is_bollinger)
            st.plotly_chart(fig, use_container_width=True, key=f"c_{title}_{idx}_{item['sid']}")


# ==============================================================================
# 網頁介面 (Streamlit UI)
# ==============================================================================
st.title("台股精選訊號 v28.1（阿水一式帶寬<=0.2 正統修正版）")
st.caption(f"{time.strftime('%Y-%m-%d %H:%M')}｜阿水一式帶寬已嚴格設定為 <= 0.2（已修正 None 過濾）")

st.warning("勝率為歷史回測樣本，未扣成本，不構成投資建議。")

with st.expander("策略總覽與勝率清單", expanded=True):
    st.markdown("""
| 方向 | 訊號名稱 | 核心邏輯 / 參考勝率 |
|------|----------|---------------------|
| 買 | **林恩如20週均線W底** | **58.5%**（站上100MA與月線 + W底不再破底 + 帶量） |
| 買 | **朱家泓頭頭高底底高** | **57.8%**（頭頭高、底底高多頭結構 + 站上月線帶量） |
| 買 | 施昇輝0050樂活KD | **56.5%**（KD<20超賣區 + 站上月線逢低佈局） |
| 買 | 資金輪動主流強勢股 | **59.2%**（100MA與月線之上 + 接近新高 + 爆量） |
| 買 | **阿水一式** | **53.5%**（2.1倍布林帶寬<=0.2壓縮 + 2倍均量 + 紅K突破上軌） **[正統帶寬<=0.2邏輯]** |
| 買 | 貫穿線 / 三內身 | **66.0% / 65.0%**（高勝率反轉 + 站上月線） |
| 買 | 大K棒強力收回 | **68.0%**（突破恐慌陰線 + 站上月線） |
| 買 | 三白兵 / 爆量三白兵 / 黏合晨星 | **48.8% / 45.7% / 46.3%** |
| 買 | 破底翻 / RSI鈍化 | **48.2% / 45.6%** |
| 買 | 多頭背離 | **43.4%**（RSI5、RSI10 價新低RSI未新低） |
| 賣 | 頂背離 | **54.4%**（RSI5、RSI10 價新高RSI未新低） |
""")

col1, col2 = st.columns(2)
with col1:
    do_scan = st.button("同步掃描全部 15 種策略", use_container_width=True)
with col2:
    if st.button("強制刷新", type="primary", use_container_width=True):
        st.cache_data.clear()
        SYMBOL_CACHE.clear()
        st.rerun()

if do_scan or "scan_results_v28" not in st.session_state:
    with st.spinner("掃描中（載入 300 天歷史資料並執行 15 種名師戰法）..."):
        st.session_state["scan_results_v28"] = run_full_scan()
    if do_scan:
        st.success("掃描完成")

results = st.session_state.get("scan_results_v28", {})

tabs = st.tabs([
    "衝突彙整",
    "林恩如20週W底 58.5%",
    "朱家泓頭頭高 57.8%",
    "施昇輝樂活KD 56.5%",
    "資金輪動主流 59%",
    "阿水一式 53%",
    "貫穿線 66%",
    "三內身 65%",
    "大K棒收回 68%",
    "三白兵 48%",
    "爆量三白兵 45%",
    "黏合晨星 46%",
    "破底翻 48%",
    "RSI鈍化 45%",
    "多頭背離 43%",
    "頂背離 54%",
])

with tabs[0]:
    st.markdown("同一檔出現多個訊號時集中顯示。買賣相反會標衝突（衝突「否」排序在前面）。")
    cdf = build_conflict_table(results)
    if cdf.empty:
        st.info("目前沒有跨訊號重疊個股。")
    else:
        st.dataframe(cdf, use_container_width=True, hide_index=True)

with tabs[1]:
    render_signal_tab(results.get("林恩如20週均線W底", []), "林恩如 20 週均線 W 底戰法", "歷史勝率 58.5%｜站上 100MA 與月線 + W 底不再破底 + 帶量")
with tabs[2]:
    render_signal_tab(results.get("朱家泓頭頭高底底高", []), "朱家泓頭頭高底底高戰法", "歷史勝率 57.8%｜頭頭高、底底高多頭結構 + 站上月線帶量")
with tabs[3]:
    render_signal_tab(results.get("施昇輝0050樂活KD", []), "施昇輝 0050 樂活 KD 戰法", "歷史勝率 56.5%｜KD 雙雙跌破 20 低檔超賣區 + 站上月線")
with tabs[4]:
    render_signal_tab(results.get("資金輪動主流強勢股", []), "資金輪動主流強勢股", "歷史勝率 59.2%｜100MA與月線之上 + 接近新高 + 爆量")
with tabs[5]:
    render_signal_tab(results.get("阿水一式", []), "阿水一式（帶寬<=0.2壓縮突破）", "歷史勝率 53.5%｜2.1倍帶寬<=0.2 + 2倍均量 + 紅K突破上軌", is_bollinger=True)
with tabs[6]:
    render_signal_tab(results.get("貫穿線", []), "貫穿線（負上線）", "歷史勝率 66.0%｜高勝率反轉 + 站上月線")
with tabs[7]:
    render_signal_tab(results.get("三內身", []), "三內身", "歷史勝率 65.0%｜孕線確認 + 站上月線")
with tabs[8]:
    render_signal_tab(results.get("大K棒收回", []), "大K棒強力收回", "歷史勝率 68.0%｜突破恐慌陰線 + 站上月線")
with tabs[9]:
    render_signal_tab(results.get("三白兵", []), "多頭排列 + 三白兵", "歷史勝率 48.8%")
with tabs[10]:
    render_signal_tab(results.get("爆量三白兵", []), "多頭排列 + 爆量 + 三白兵", "歷史勝率 45.7%")
with tabs[11]:
    render_signal_tab(results.get("黏合晨星", []), "多頭排列 + 黏合打開 + 晨星", "歷史勝率 46.3%")
with tabs[12]:
    render_signal_tab(results.get("破底翻", []), "破底翻", "歷史勝率 48.2%")
with tabs[13]:
    render_signal_tab(results.get("RSI鈍化", []), "RSI 鈍化", "歷史勝率 45.6%")
with tabs[14]:
    render_signal_tab(results.get("多頭背離", []), "一次／二度多頭背離", "RSI(5) 與 RSI(10) 檢查｜歷史底背離約 43.4%")
with tabs[15]:
    render_signal_tab(results.get("頂背離", []), "RSI 頂背離（唯一賣出）", "RSI(5) 與 RSI(10) 檢查｜歷史勝率 54.4%")

st.markdown("---")
st.caption("僅供學習監控。投資有風險，請獨立判斷並自負盈虧。")
""")
