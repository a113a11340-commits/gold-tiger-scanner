# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import io
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. 設定與 Google Sheet 連結 (不改動) ---
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit?gid=0#gid=0" 

st.set_page_config(page_title="均線系統", layout="wide")
st.title("🐯 均線系統：82 檔全自動監控")

# --- 2. 繪圖函數：強化黑底與中文顯示 ---
def draw_kline(df, sid, name, sP, lP):
    # 建立子圖
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, 
                        subplot_titles=(f'{sid} {name} 均線走勢', '成交量能'), 
                        row_width=[0.3, 0.7])

    # A. K線圖 - 強化顏色對比
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        name='K線',
        increasing_line_color='#FF3333', decreasing_line_color='#00AA00'
    ), row=1, col=1)
    
    # 計算均線 (邏輯不變)
    df_ma = df.copy()
    df_ma['MA_S'] = df_ma['Close'].rolling(window=int(sP)).mean()
    df_ma['MA_L'] = df_ma['Close'].rolling(window=int(lP)).mean()
    
    # 短均線：螢光綠，加粗
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_S'], name=f'短均({sP}MA)', 
                             line=dict(color='SpringGreen', width=3)), row=1, col=1)
    # 長均線：粉紅紫，加粗
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_L'], name=f'長均({lP}MA)', 
                             line=dict(color='Magenta', width=3)), row=1, col=1)
    
    # B. 成交量圖
    colors = ['#FF3333' if row['Close'] >= row['Open'] else '#00AA00' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)

    # --- 關鍵修正：黑底 + 中文字型 + 移除下方滑桿 ---
    fig.update_layout(
        template="plotly_dark", # 專業黑底
        font=dict(
            family="Microsoft JhengHei, Apple LiGothic, sans-serif", # 修正中文顯示
            size=14
        ),
        xaxis_rangeslider_visible=False, # 隱藏滑桿，手機更好用
        height=800,
        dragmode='pan', # 預設改為移動模式，方便手機查看歷史
        margin=dict(t=80, b=50, l=10, r=10)
    )

    # --- 關鍵修正：移除多餘工具籃，僅保留畫線與縮放功能 ---
    config = {
        'displayModeBar': True,
        'modeBarButtonsToRemove': ['zoomIn2d', 'zoomOut2d', 'autoScale2d', 'resetScale2d', 'hoverClosestCartesian', 'hoverCompareCartesian', 'toggleSpikelines'],
        'modeBarButtonsToAdd': ['drawline', 'drawrect', 'eraseshape'],
        'scrollZoom': True,
        'displaylogo': False
    }
    
    st.plotly_chart(fig, use_container_width=True, config=config)

# --- 3. 核心執行函數 (判斷邏輯完全不動) ---
def run_precise_scan():
    try:
        csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv'
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df_sheet = pd.read_csv(io.StringIO(res.text))
        
        raw_rows = df_sheet.iloc[:, [0, 1, 2, 3]].values.tolist()
        valid_stocks = [r for r in raw_rows if pd.notnull(r[0]) and str(r[0]).strip() != ""]
        
        st.info(f"🔄 正在掃描雲端清單（共 {len(valid_stocks)} 檔）...")
        
        final_list = [] 
        bar = st.progress(0)
        status_text = st.empty()
        
        for i, item in enumerate(valid_stocks):
            try:
                sid_raw = str(item[0]).split('.')[0].strip()
                name = str(item[1])
                sP = int(float(item[2])) if pd.notnull(item[2]) else 21
                lP = int(float(item[3])) if pd.notnull(item[3]) else 152
                
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                status_text.text(f"🔍 掃描中 ({i+1}/{len(valid_stocks)}): {sid_full}")
                
                df = yf.download(sid_full, period="250d", interval="1d", progress=False)
                if df.empty or len(df) < lP: continue
                df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
                
                # 修復 float 報錯問題 (TypeError)
                curPrice = float(df['Close'].iloc[-1])
                closes = df['Close'].tolist()[::-1]
                vols = df['Volume'].tolist()[::-1]
                pList = [curPrice] + closes[1:]

                def getMA(arr, per, off):
                    p = int(per)
                    return sum(arr[off : p + off]) / p if len(arr) >= p + off else 0

                maST, maSY = getMA(pList, sP, 0), getMA(pList, sP, 1)
                maLT, maLY, maLB = getMA(pList, lP, 0), getMA(pList, lP, 1), getMA(pList, lP, 2)

                sigs, is_alert = [], False
                configs = [{"t":"短","d":sP,"ct":maST,"cy":maSY}, {"t":"長","d":lP,"ct":maLT,"cy":maLY,"cb":maLB}]
                for m in configs:
                    if m["ct"] == 0: continue
                    trend = "⬆️" if m["ct"] > m["cy"] else "↘️"
                    lbl = f"{m['t']}({m['d']}MA){trend}"
                    
                    if pList[1] >= m["cy"] and pList[0] < m["ct"]: 
                        sigs.append(f"跌破{lbl}[停損]"); is_alert = True
                    elif m["t"] == "長" and pList[2] < m.get("cb",0) and pList[1] > m["cy"] and float(df['Low'].iloc[-1]) > m["ct"]:
                        sigs.append(f"2日法則{lbl}[加碼1/2]"); is_alert = True
                    elif pList[1] < m["cy"] and pList[0] > m["ct"]: 
                        sigs.append(f"突破{lbl}[進場1/2]"); is_alert = True

                if is_alert:
                    vol_tag = "🔴量增" if (len(vols) >= 2 and vols[0] > vols[1] * 1.2) else ""
                    final_list.append({
                        "sid": sid_full, "名稱": name, "現價": f"{curPrice:.2f}", 
                        "訊號": " + ".join(sigs), "量能": vol_tag, "df": df, "sP": sP, "lP": lP
                    })
            except Exception: continue
            bar.progress((i + 1) / len(valid_stocks))

        status_text.empty()
        st.session_state["results"] = final_list
    except Exception as e: st.error(f"❌ 讀取錯誤: {e}")

# --- 4. 顯示與看圖邏輯 (邏輯完全不動) ---
if "results" not in st.session_state:
    run_precise_scan()

if st.session_state.get("results"):
    st.success(f"🚨 掃描完成！共有 {len(st.session_state['results'])} 檔觸發關鍵訊號。")
    # 將結果表格化，並正確命名欄位
    res_data = pd.DataFrame(st.session_state["results"])[["sid", "名稱", "現價", "訊號", "量能"]]
    st.table(res_data.rename(columns={"sid": "代號"}))
    
    st.write("---")
    # 建立按鈕生成圖形
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📈 查看圖表: {res['sid']} {res['名稱']}", key=f"btn_{idx}"):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])
else:
    st.warning("✅ 目前無觸發訊號。")

if st.sidebar.button("🔄 重新重新掃描清單"):
    st.session_state.pop("results", None)
    st.rerun()