# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import io
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. 設定你的專屬網址 ---
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit?gid=0#gid=0" 

st.set_page_config(page_title="均線系統", layout="wide")
st.title("🐯 均線系統：全自動監控")

# --- 2. 繪圖函數：修正預設隱藏長均、預設不畫線 ---
def draw_kline(df, sid, name, sP, lP):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, 
                        subplot_titles=(f'{sid} {name} 均線走勢', '成交量能'), 
                        row_width=[0.3, 0.7])

    # A. K線圖
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        name='K線',
        increasing_line_color='#FF3333', decreasing_line_color='#00AA00'
    ), row=1, col=1)
    
    # 均線邏輯
    df_ma = df.copy()
    df_ma['MA_S'] = df_ma['Close'].rolling(window=int(sP)).mean()
    df_ma['MA_L'] = df_ma['Close'].rolling(window=int(lP)).mean()
    
    # 短均線：正常顯示
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_S'], name=f'短均({sP}MA)', 
                             line=dict(color='SpringGreen', width=2)), row=1, col=1)
    
    # 長均線：關鍵修正 -> visible='legendonly' (預設隱藏，點圖例才顯示)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_L'], name=f'長均({lP}MA)', 
                             visible='legendonly', 
                             line=dict(color='Magenta', width=2)), row=1, col=1)
    
    # B. 成交量圖
    colors = ['#FF3333' if row['Close'] >= row['Open'] else '#00AA00' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)

    # --- 畫面設定：背景黑、不預設畫線 ---
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="black",
        plot_bgcolor="black",
        font=dict(family="Microsoft JhengHei", size=14, color="white"),
        xaxis_rangeslider_visible=False,
        height=800,
        dragmode='zoom',           # ⬅️ 修正：改回 zoom，一開啟不會亂畫線
        newshape=dict(line_color='White', line_width=2), 
        margin=dict(t=80, b=50, l=10, r=10)
    )

    # --- 工具列設定：保留橡皮擦 ---
    config = {
        'modeBarButtonsToAdd': [
            'eraseshape',   # 橡皮擦
            'drawline',     # 畫線
            'drawrect'      # 畫框
        ],
        'scrollZoom': True,
        'displaylogo': False,
        'displayModeBar': True,
        'modeBarButtonsToRemove': ['lasso2d', 'select2d'] 
    }
    
    st.plotly_chart(fig, use_container_width=True, config=config)

# --- 3. 核心執行函數 (數據邏輯完全不動) ---
def run_precise_scan():
    try:
        csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv'
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df_sheet = pd.read_csv(io.StringIO(res.text))
        raw_rows = df_sheet.iloc[:, [0, 1, 2, 3]].values.tolist()
        valid_stocks = [r for r in raw_rows if pd.notnull(r[0]) and str(r[0]).strip() != ""]
        final_list = [] 
        bar = st.progress(0)
        for i, item in enumerate(valid_stocks):
            try:
                sid_raw = str(item[0]).split('.')[0].strip()
                name = str(item[1])
                sP, lP = (int(float(item[2])) if pd.notnull(item[2]) else 21), (int(float(item[3])) if pd.notnull(item[3]) else 152)
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                df = yf.download(sid_full, period="250d", interval="1d", progress=False)
                if df.empty or len(df) < lP: continue
                df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
                curPrice = float(df['Close'].iloc[-1])
                pList = [curPrice] + df['Close'].tolist()[::-1][1:]
                def getMA(arr, per, off):
                    p = int(per)
                    return sum(arr[off : p + off]) / p if len(arr) >= p + off else 0
                maST, maSY = getMA(pList, sP, 0), getMA(pList, sP, 1)
                maLT, maLY, maLB = getMA(pList, lP, 0), getMA(pList, lP, 1), getMA(pList, lP, 2)
                sigs, is_alert = [], False
                if pList[1] >= maSY and pList[0] < maST: sigs.append(f"跌破短均[停損]"); is_alert = True
                elif pList[2] < maLB and pList[1] > maSY and df['Low'].iloc[-1] > maLT: sigs.append(f"2日法則[加碼]"); is_alert = True
                elif pList[1] < maSY and pList[0] > maST: sigs.append(f"突破短均[進場]"); is_alert = True
                if is_alert:
                    final_list.append({"sid": sid_full, "名稱": name, "現價": f"{curPrice:.2f}", "訊號": " + ".join(sigs), "df": df, "sP": sP, "lP": lP})
            except Exception: continue
            bar.progress((i + 1) / len(valid_stocks))
        st.session_state["results"] = final_list
    except Exception as e: st.error(f"❌ 讀取錯誤: {e}")

# --- 4. 顯示與看圖邏輯 ---
if "results" not in st.session_state: run_precise_scan()
if st.session_state.get("results"):
    df_show = pd.DataFrame(st.session_state["results"])[["sid", "名稱", "現價", "訊號"]]
    st.table(df_show)
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📈 繪製圖形: {res['sid']} {res['名稱']}", key=f"btn_{idx}"):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])
if st.sidebar.button("重新掃描"):
    st.session_state.pop("results", None)
    st.rerun()