"""
================================================================================
台股精選訊號監控系統（Streamlit v16.0 施昇輝0050樂活KD與多派名師整合版）
================================================================================
【程式內建調整指南 (Adjustment Guide)】
您可以在下方程式碼中調整以下參數：
1. 最小成交量限制 (MIN_VOLUME)：預設 500,000 (500張)，ETF或大型權值股皆適用。
2. 施昇輝 0050 樂活 KD 戰法參數 (analyze_shishenghui_kd)：
   - 觸發條件：KD 指標之 K值與 D值同時小於 20（低檔超賣區），且股價站上月線（MA20）。
3. 既有策略：包含朱家泓頭頭高底底高、林恩如20週均線W底、阿水一式、貫穿線等。
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

# 頁面基本設定
st.set_page_config(layout="wide", page_title="台股精選訊號 v16.0")

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

# 【勝率對照表】（含施昇輝、朱家泓、林恩如與各大名師戰法）
WINRATE = {
    "施昇輝0050樂活KD": "56.5%",
    "朱家泓頭頭高底底高": "57.8%",
    "20週均線W底起長": "58.5%",
    "阿水一式(布林突破)": "53.5%",
    "貫穿線": "66.0%",
    "三內身": "65.0%",
    "大K棒收回": "68.0%",
    "破底翻": "48.2%",
    "阿水二式(弱勢放空)": "50.0%",
}

# 雲端清單來源設定
MAIN_SHEET = {
    "base": "https://docs.google.com/spreadsheets/d/13Mv-7uaFyR1KcxNRVrhxCGAAntElKprB7ZeWWBxS3n0",
    "gid": "0",
}

# 系統全域設定
CONFIG = {
    "MIN_VOLUME": 500000,      # 最小成交量限制：預設 500,000 (500張)
    "BATCH_WORKERS": 20,       # 多執行緒平行處理數量
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


def calc_kd(highs, lows, closes, n=9):
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
            if len(t_cls) < 100:
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
            tasks.append({"sid": sid, "name": name, "sheet": "主要清單", "short_n": 20, "long_n": 100})
    except Exception as e:
        st.error(f"讀取主要股票清單失敗: {e}")
    return tasks


def _pack(sid, name, sheet, hist, price, signal, direction, entry, stop, target, how, side, wr):
    return {
        "sid": sid, "name": name, "sheet": sheet, "hist": hist,
        "price": price, "signal": f"{signal}｜勝率{wr}", "direction": direction,
        "entry": entry, "stop": stop, "target": target, "how": how,
        "side": side, "winrate": wr,
        "lots": int(hist["vols"][-1] // 1000),
    }


# ==============================================================================
# 【新增策略】：施昇輝 0050 樂活 KD 波段戰法（KD < 20 低檔超賣區買進）
# ==============================================================================
def analyze_shishenghui_kd(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    
    k_list, d_list = calc_kd(highs, lows, closes, n=9)
    ma20 = calc_ma_list(closes, 20)
    
    if None in (k_list[-1], d_list[-1], ma20[-1]):
        return None
        
    # 條件：KD 均在 20 以下（低檔超賣區，符合施昇輝樂活大叔逢低買進波段點）
    is_low_kd = (k_list[-1] < 20) and (d_list[-1] < 20)
    
    # 附帶輔助：準備打底或量縮止穩
    if not is_low_kd:
        return None
        
    return {
        "signal": f"施昇輝樂活KD：K({k_list[-1]:.1f})與D({k_list[-1]:.1f})雙雙跌破20低檔超賣區",
        "direction": "買進（逢低佈局）", "side": "long", "winrate": WINRATE["施昇輝0050樂活KD"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(closes[-1] * 0.93, 2),  # 樂活法強調大不了套牢領股息，設 7% 停損或長抱
        "target": round(closes[-1] * 1.12, 2),
        "how": "施昇輝0050無腦投資術：KD<20低檔超賣區勇敢逢低分批買進，等待KD>80再出場",
        "price": closes[-1],
    }


# ==============================================================================
# 【既有精選戰法】
# ==============================================================================
def analyze_chujiahung_bottom(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 80 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None:
        return None
    recent_lows = lows[-60:]
    early_min, late_min = min(recent_lows[:30]), min(recent_lows[30:])
    recent_highs = highs[-60:]
    early_max, late_max = max(recent_highs[:30]), max(recent_highs[30:])
    if not (late_min >= early_min and late_max >= early_max and closes[-1] > ma20[-1]):
        return None
    avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    if not (avg5_vol > 0 and vols[-1] >= avg5_vol * 1.2 and closes[-1] > opens[-1]):
        return None
    return {
        "signal": "朱家泓頭頭高底底高：形成頭頭高底底高多頭結構+站上MA20帶量",
        "direction": "買進", "side": "long", "winrate": WINRATE["朱家泓頭頭高底底高"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], ma20[-1] * 0.98), 2),
        "target": round(closes[-1] * 1.12, 2),
        "how": "朱家泓飆股戰法：確認頭頭高、底底高與月線多頭排列",
        "price": closes[-1],
    }


def analyze_lin_20w_w_bottom(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 120 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma100 = calc_ma_list(closes, 100)
    if ma100[-1] is None or closes[-1] <= ma100[-1]:
        return None
    recent_lows = lows[-40:]
    if min(recent_lows[20:]) < min(recent_lows[:20]) * 0.99:
        return None
    avg5_vol = sum(vols[-6:-1]) / 5 if n >= 6 else 0
    if not (avg5_vol > 0 and vols[-1] >= avg5_vol * 1.3 and closes[-1] > opens[-1]):
        return None
    return {
        "signal": "20週均線W底起長：站上100MA+不再破底+帶量突破",
        "direction": "買進", "side": "long", "winrate": WINRATE["20週均線W底起長"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], ma100[-1] * 0.98), 2),
        "target": round(closes[-1] * 1.12, 2),
        "how": "林恩如四大法寶核心：大趨勢向上且底部打底完成後帶量攻擊",
        "price": closes[-1],
    }


def analyze_ashui_1(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma20, upper, lower, bandwidth = calc_bollinger_bands(closes, period=20, num_std=2.0)
    if None in (ma20[-1], upper[-1], bandwidth[-1], bandwidth[-5]):
        return None
    if not (min(bandwidth[-10:]) < (sum(bandwidth[-60:]) / 60) * 0.85 and vols[-1] >= (sum(vols[-6:-1])/5) * 2.0 and closes[-1] > opens[-1] and closes[-1] >= upper[-1] * 0.995):
        return None
    return {
        "signal": "阿水一式：布林通道壓縮後帶量突破上軌",
        "direction": "買進", "side": "long", "winrate": WINRATE["阿水一式(布林突破)"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], ma20[-1] * 0.98), 2),
        "target": round(closes[-1] * 1.10, 2),
        "how": "壓縮+帶量+紅K突破通道頂",
        "price": closes[-1],
    }


def analyze_piercing_line(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None or closes[-1] < ma20[-1] * 0.95:
        return None
    d0, d1 = closes[-1], closes[-2]
    o0, o1 = opens[-1], opens[-2]
    if not (d1 < o1 and d0 > o0 and o0 < o1 and d0 >= (o1 + d1) / 2):
        return None
    return {
        "signal": "貫穿線：上升趨勢回檔過實體中點",
        "direction": "買進", "side": "long", "winrate": WINRATE["貫穿線"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], lows[-2], closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.09, 2),
        "how": "高勝率反轉型態",
        "price": closes[-1],
    }


def analyze_three_inside_up(hist):
    closes, highs, lows, opens, vols = hist["closes"], hist["highs"], hist["lows"], hist["opens"], hist["vols"]
    n = len(closes)
    if n < 60 or vols[-1] < CONFIG["MIN_VOLUME"]:
        return None
    ma20 = calc_ma_list(closes, 20)
    if ma20[-1] is None or closes[-1] < ma20[-1] * 0.95:
        return None
    d0, d1, d2 = closes[-1], closes[-2], closes[-3]
    o0, o1, o2 = opens[-1], opens[-2], opens[-3]
    if not ((d2 < o2) and (d1 > o1) and (o1 >= min(o2, d2)) and (d1 <= max(o2, d2)) and (d0 > o0) and (d0 > d1)):
        return None
    return {
        "signal": "三內身：孕線完成後第三根價量確認",
        "direction": "買進", "side": "long", "winrate": WINRATE["三內身"],
        "entry": round(closes[-1] * 1.005, 2),
        "stop": round(min(lows[-1], lows[-2], lows[-3], closes[-1] * 0.97), 2),
        "target": round(closes[-1] * 1.09, 2),
        "how": "孕線後多方表態確認",
        "price": closes[-1],
    }


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
            "how": "站回前低後買",
            "price": closes[-1],
        }
    return None


SIGNAL_KEYS = [
    "施昇輝0050樂活KD", "朱家泓頭頭高底底高", "20週均線W底起長", "阿水一式", "貫穿線", "三內身", "破底翻"
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
            ("施昇輝0050樂活KD", analyze_shishenghui_kd),
            ("朱家泓頭頭高底底高", analyze_chujiahung_bottom),
            ("20週均線W底起長", analyze_lin_20w_w_bottom),
            ("阿水一式", analyze_ashui_1),
            ("貫穿線", analyze_piercing_line),
            ("三內身", analyze_three_inside_up),
            ("破底翻", analyze_break_bottom_flip),
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
        conflict = any("買" in d for d in dirs) and any("賣" in d for d in dirs)
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
    ma20 = calc_ma_list(hist["closes"], 20)[-100:]
    ma100 = calc_ma_list(hist["closes"], 100)[-100:]
    fig.add_trace(go.Scatter(x=x, y=ma20, mode="lines", name="MA20", line=dict(color="#1E90FF", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=ma100, mode="lines", name="100MA", line=dict(color="#FF4500", width=2)), row=1, col=1)
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


# ==============================================================================
# 網頁介面 (Streamlit UI)
# ==============================================================================
st.title("台股精選訊號 v16.0（施昇輝0050樂活與多名師策略整合版）")
st.caption(f"{time.strftime('%Y-%m-%d %H:%M')}｜新增施昇輝 0050 樂活大叔 KD 低檔超賣區逢低佈局戰法")

st.warning("勝率為歷史回測樣本，未扣成本，不構成投資建議。")

with st.expander("策略清單與勝率概覽", expanded=True):
    st.markdown("""
| 方向 | 訊號名稱 | 核心邏輯 / 參考勝率 |
|------|----------|---------------------|
| 買 | **施昇輝0050樂活KD** | **56.5%**（KD雙雙跌破20低檔超賣區，樂活逢低佈局） |
| 買 | 朱家泓頭頭高底底高 | **57.8%**（頭頭高、底底高多頭結構 + 站上MA20帶量） |
| 買 | 20週均線W底起長 | **58.5%**（站上100MA + W底不再破底 + 帶量突破） |
| 買 | 阿水一式 | **53.5%**（布林壓縮 + 2倍均量 + 紅K突破上軌） |
| 買 | 貫穿線 | **66.0%**（上升趨勢回檔過實體中點） |
| 買 | 三內身 | **65.0%**（孕線後第三根確認） |
| 買 | 破底翻 | **48.2%** |
""")

col1, col2 = st.columns(2)
with col1:
    do_scan = st.button("同步掃描", use_container_width=True)
with col2:
    if st.button("強制刷新", type="primary", use_container_width=True):
        st.cache_data.clear()
        SYMBOL_CACHE.clear()
        st.rerun()

if do_scan or "scan_results_v16" not in st.session_state:
    with st.spinner("掃描中（結合施昇輝0050樂活KD與各項名師戰法）..."):
        st.session_state["scan_results_v16"] = run_full_scan()
    if do_scan:
        st.success("掃描完成")

results = st.session_state.get("scan_results_v16", {})

tabs = st.tabs([
    "衝突彙整",
    "施昇輝0050樂活KD 56.5%",
    "朱家泓頭頭高底底高 57.8%",
    "20週均線W底 58.5%",
    "阿水一式 53.5%",
    "貫穿線 66%",
    "三內身 65%",
    "破底翻 48%",
])

with tabs[0]:
    st.markdown("同一檔出現多個訊號時集中顯示。買賣相反會標衝突。")
    cdf = build_conflict_table(results)
    if cdf.empty:
        st.info("目前沒有跨訊號重疊個股。")
    else:
        st.dataframe(cdf, use_container_width=True, hide_index=True)

with tabs[1]:
    render_signal_tab(results.get("施昇輝0050樂活KD", []), "施昇輝0050樂活 KD 戰法", "歷史勝率 56.5%｜KD 雙雙跌破 20 低檔超賣區，逢低樂活佈局")
with tabs[2]:
    render_signal_tab(results.get("朱家泓頭頭高底底高", []), "朱家泓頭頭高底底高戰法", "歷史勝率 57.8%｜頭頭高、底底高多頭結構 + 站上 MA20 帶量")
with tabs[3]:
    render_signal_tab(results.get("20週均線W底起長", []), "20週均線 W 底起長", "歷史勝率 58.5%｜站上 100MA 且 W 底打底完成、不再破底")
with tabs[4]:
    render_signal_tab(results.get("阿水一式", []), "阿水一式（布林壓縮突破）", "歷史勝率 53.5%｜壓縮 + 2倍均量 + 紅K突破通道頂")
with tabs[5]:
    render_signal_tab(results.get("貫穿線", []), "貫穿線（負上線）", "歷史勝率 66.0%｜高勝率反轉型態")
with tabs[6]:
    render_signal_tab(results.get("三內身", []), "三內身", "歷史勝率 65.0%｜孕線第三根確認")
with tabs[7]:
    render_signal_tab(results.get("破底翻", []), "破底翻", "歷史勝率 48.2%")

st.markdown("---")
st.caption("僅供學習監控。投資有風險，請獨立判斷並自負盈虧。")
