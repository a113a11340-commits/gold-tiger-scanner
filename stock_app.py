# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import io
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. 基礎設定 ---
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit?gid=0#gid=0" 

st.set_page_config(page_title="均線系統", layout="wide")
st.title("🐯 均線系統：全自動監控")

# --- 2. 繪圖函數：寬扁比例、下方圖例、含畫框與橡皮擦 ---
def draw_kline(df, sid, name, sP, lP):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, 
                        subplot_titles=(f'{sid} {name}', '成交量能'), 
                        row_width=[0.3, 0.7])

    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        name='K線', increasing_line_color='#FF3333', decreasing_line_color='#00AA00'
    ), row=1, col=1)
    
    df_ma = df.copy()
    df_ma['MA_S'] = df_ma['Close'].rolling(window=int(sP)).mean()
    df_ma['MA_L'] = df_ma['Close'].rolling(window=int(lP)).mean()
    
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_S'], name=f'短均({sP})', line=dict(color='SpringGreen', width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_L'], name=f'長均({lP})', visible='legendonly', line=dict(color='Magenta', width=2)), row=1, col=1)
    
    colors = ['#FF3333' if row['Close'] >= row['Open'] else '#00AA00' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="black", plot_bgcolor="black",
        font=dict(family="Microsoft JhengHei", size=14, color="white"),
        xaxis_rangeslider_visible=False, height=500, dragmode='pan',
        newshape=dict(line_color='White', line_width=2),
        margin=dict(t=50, b=80, l=10, r=10),
        legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5)
    )

    config = {
        'scrollZoom': True, 'displayModeBar': True, 'displaylogo': False,
        'modeBarButtonsToAdd': ['drawline', 'drawrect', 'eraseshape'],
        'modeBarButtonsToRemove': ['toImage', 'zoom2d', 'select2d', 'lasso2d', 'zoomIn2d', 'zoomOut2d', 'autoScale2d'],
        'locale': 'zh-TW'
    }
    st.plotly_chart(fig, use_container_width=True, config=config)

# --- 3. 掃描與讀取函數 (抓取 F 訊號 & G 量能) ---
def run_precise_scan():
    try:
        csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv'
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df_sheet = pd.read_csv(io.StringIO(res.text))
        
        # 讀取 A(0), B(1), C(2), D(3), F(5), G(6) 欄
        raw_rows = df_sheet.iloc[:, [0, 1, 2, 3, 5, 6]].values.tolist()
        valid_stocks = [r for r in raw_rows if pd.notnull(r[0])]
        
        final_list = [] 
        bar = st.progress(0)
        for i, item in enumerate(valid_stocks):
            try:
                sid_raw = str(item[0]).split('.')[0].strip()
                name = str(item[1])
                sP, lP = int(float(item[2])), int(float(item[3]))
                sheet_signal = str(item[4]) if pd.notnull(item[4]) else ""
                sheet_volume = str(item[5]) if pd.notnull(item[5]) else ""
                
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                df = yf.download(sid_full, period="250d", progress=False)
                if df.empty: continue
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                
                curP = df['Close'].iloc[-1]
                maS = df['Close'].rolling(window=sP).mean().iloc[-1]
                maS_y = df['Close'].rolling(window=sP).mean().iloc[-2]
                close_y = df['Close'].iloc[-2]
                
                if (close_y >= maS_y and curP < maS) or (close_y < maS_y and curP > maS):
                    final_list.append({
                        "代號": sid_full, "名稱": name, "現價": f"{curP:.2f}", 
                        "訊號": sheet_signal, "量能": sheet_volume, 
                        "df": df, "sP": sP, "lP": lP
                    })
            except: continue
            bar.progress((i + 1) / len(valid_stocks))
        st.session_state["results"] = final_list
    except Exception as e: 
        st.error(f"❌ 讀取錯誤: {e}")
        st.session_state["results"] = []

# --- 4. 執行與顯示介面 ---
if "results" not in st.session_state:
    run_precise_scan()

# 確保 results 存在且不為空
results = st.session_state.get("results", [])

if results:
    # 顯示表格 (排除繪圖用的 dataframe 欄位)
    show_df = pd.DataFrame(results)[["代號", "名稱", "現價", "訊號", "量能"]]
    st.table(show_df)
    
    st.write("---")
    # 產生按鈕
    for idx, res in enumerate(results):
        if st.button(f"📈 繪製: {res['代號']} {res['名稱']}", key=f"btn_{idx}"):
            draw_kline(res["df"], res["代號"], res["名稱"], res["sP"], res["lP"])
else:
    st.write("目前無觸發訊號。")

if st.sidebar.button("重新掃描"):
    st.session_state.pop("results", None)
    st.rerun()