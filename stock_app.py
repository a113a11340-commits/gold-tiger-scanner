# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import io
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. 基礎設定 ---
# 請確保你的試算表已開啟「知道連結的人即可檢視」
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit?gid=0#gid=0" 

st.set_page_config(page_title="均線系統", layout="wide")
st.title("🐯 均線系統：手機優化版")

# --- 2. 繪圖函數：極細線、1/3成交量、標籤外移 ---
def draw_kline(df, sid, name, sP, lP):
    # 設定子圖比例：K線 0.7, 成交量 0.3 (約 1/3)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.08, 
                        subplot_titles=(f'{sid} {name}', '成交量能'), 
                        row_width=[0.3, 0.7]) 

    # K線圖 (線條寬度 1)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        name='K線', increasing_line_color='#FF3333', decreasing_line_color='#00AA00',
        line=dict(width=1) 
    ), row=1, col=1)
    
    # 均線計算
    df_ma = df.copy()
    df_ma['MA_S'] = df_ma['Close'].rolling(window=int(sP)).mean()
    df_ma['MA_L'] = df_ma['Close'].rolling(window=int(lP)).mean()
    
    # 極細均線 (width=1)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_S'], name=f'短均({sP})', 
                             line=dict(color='SpringGreen', width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_L'], name=f'長均({lP})', 
                             visible='legendonly', line=dict(color='Magenta', width=1)), row=1, col=1)
    
    # 成交量
    colors = ['#FF3333' if row['Close'] >= row['Open'] else '#00AA00' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)

    # 介面佈局優化
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="black", plot_bgcolor="black",
        font=dict(family="Microsoft JhengHei", size=12, color="white"),
        xaxis_rangeslider_visible=False, height=500, dragmode='pan',
        
        # 手動畫線設定為極細 (width=1)
        newshape=dict(line_color='White', line_width=1),
        
        # 增加頂部邊距，給工具欄和標籤留空間
        margin=dict(t=120, b=50, l=10, r=10), 
        
        # 標籤移到最上方外側
        legend=dict(
            orientation="h", 
            yanchor="bottom",
            y=1.15,            
            xanchor="center",
            x=0.5
        )
    )

    config = {
        'scrollZoom': True, 
        'displayModeBar': True,
        'displaylogo': False,
        'modeBarButtonsToAdd': [
            'drawline',    # 畫線
            'drawrect',    # 小框框
            'eraseshape'   # 橡皮擦
        ],
        'modeBarButtonsToRemove': [
            'toImage', 'zoom2d', 'pan2d', 'select2d', 'lasso2d', 
            'zoomIn2d', 'zoomOut2d', 'autoScale2d', 'resetScale2d', 
            'hoverClosestCartesian', 'hoverCompareCartesian'
        ],
        'locale': 'zh-TW'
    }
    
    # CSS 固定工具列位置
    st.markdown('<style>.modebar-container { top: -30px !important; }</style>', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config=config)

# --- 3. 掃描與讀取函數 (含 F 欄訊號、G 欄量能) ---
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
                sheet_signal = str(item[4]) if pd.notnull(item[4]) else "" # F欄
                sheet_volume = str(item[5]) if pd.notnull(item[5]) else "" # G欄
                
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                df = yf.download(sid_full, period="250d", progress=False)
                if df.empty: continue
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                
                # 判斷邏輯 (觸發才顯示)
                curP = df['Close'].iloc[-1]
                maS = df['Close'].rolling(window=sP).mean().iloc[-1]
                maS_y = df['Close'].rolling(window=sP).mean().iloc[-2]
                close_y = df['Close'].iloc[-2]
                
                if (close_y >= maS_y and curP < maS) or (close_y < maS_y and curP > maS):
                    final_list.append({
                        "sid": sid_full, "名稱": name, "現價": f"{curP:.2f}", 
                        "訊號": sheet_signal, "量能": sheet_volume,
                        "df": df, "sP": sP, "lP": lP
                    })
            except: continue
            bar.progress((i + 1) / len(valid_stocks))
        st.session_state["results"] = final_list
    except Exception as e: st.error(f"❌ 讀取錯誤: {e}")

# --- 4. 介面顯示 ---
if "results" not in st.session_state:
    run_precise_scan()

if st.session_state.get("results"):
    # 顯示表格含訊號與量能
    st.table(pd.DataFrame(st.session_state["results"])[["sid", "名稱", "現價", "訊號", "量能"]])
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📈 繪製圖形: {res['sid']} {res['名稱']}", key=f"btn_{idx}"):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])

if st.sidebar.button("重新掃描"):
    st.session_state.pop("results", None)
    st.rerun()