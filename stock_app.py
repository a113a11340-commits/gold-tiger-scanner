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
st.markdown('<style>.modebar-container { top: 0 !important; }</style>', unsafe_allow_html=True) # 強制工具列置頂
st.title("🐯 均線系統：全自動監控")

# --- 2. 繪圖函數：工具列外移、下方圖例、含畫框與橡皮擦 ---
def draw_kline(df, sid, name, sP, lP):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.1, 
                        subplot_titles=(f'{sid} {name}', '成交量能'), 
                        row_width=[0.3, 0.7])

    # K線圖
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        name='K線', increasing_line_color='#FF3333', decreasing_line_color='#00AA00'
    ), row=1, col=1)
    
    # 均線計算
    df_ma = df.copy()
    df_ma['MA_S'] = df_ma['Close'].rolling(window=int(sP)).mean()
    df_ma['MA_L'] = df_ma['Close'].rolling(window=int(lP)).mean()
    
    # 短均與長均 (長均預設隱藏)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_S'], name=f'短均({sP})', line=dict(color='SpringGreen', width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_L'], name=f'長均({lP})', visible='legendonly', line=dict(color='Magenta', width=2)), row=1, col=1)
    
    # 成交量
    colors = ['#FF3333' if row['Close'] >= row['Open'] else '#00AA00' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)

    # 畫面外觀設定
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="black", plot_bgcolor="black",
        font=dict(family="Microsoft JhengHei", size=14, color="white"),
        xaxis_rangeslider_visible=False, height=550, dragmode='pan',
        newshape=dict(line_color='White', line_width=2),
        margin=dict(t=100, b=50, l=10, r=10), # 頂部留白給工具列
        
        # 修正：將圖例標籤移到圖表上方（y=1.1），不擋住K線
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5
        )
    )

    # 工具列設定：包含畫線、畫矩形(框框)、橡皮擦，並移除多餘按鈕
    config = {
        'scrollZoom': True, 
        'displayModeBar': True, 
        'displaylogo': False,
        'modeBarButtonsToAdd': [
            'drawline',    # 畫線
            'drawrect',    # 畫小框框 (矩形圖示)
            'eraseshape'   # 橡皮擦 (打叉方塊圖示)
        ],
        'modeBarButtonsToRemove': [
            'toImage', 'zoom2d', 'pan2d', 'select2d', 'lasso2d', 
            'zoomIn2d', 'zoomOut2d', 'autoScale2d', 'resetScale2d', 'hoverClosestCartesian', 'hoverCompareCartesian'
        ],
        'locale': 'zh-TW' # 中文化提示
    }
    
    st.plotly_chart(fig, use_container_width=True, config=config)

# --- 3. 掃描與讀取函數 (加入 G 欄量能讀取) ---
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
                name, sP, lP = str(item[1]), int(float(item[2])), int(float(item[3]))
                sheet_signal = str(item[4]) if pd.notnull(item[4]) else "" # F欄
                sheet_volume = str(item[5]) if pd.notnull(item[5]) else "" # G欄 ⬅️ 新增量能
                
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                df = yf.download(sid_full, period="250d", progress=False)
                if df.empty: continue
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                
                # 簡單判斷邏輯
                curP = df['Close'].iloc[-1]
                maS = df['Close'].rolling(window=sP).mean().iloc[-1]
                maS_y = df['Close'].rolling(window=sP).mean().iloc[-2]
                close_y = df['Close'].iloc[-2]
                
                if (close_y >= maS_y and curP < maS) or (close_y < maS_y and curP > maS):
                    final_list.append({
                        "sid": sid_full, "名稱": name, "現價": f"{curP:.2f}", 
                        "訊號": sheet_signal, "量能": sheet_volume, # ⬅️ 顯示量能
                        "df": df, "sP": sP, "lP": lP
                    })
            except: continue
            bar.progress((i + 1) / len(valid_stocks))
        st.session_state["results"] = final_list
    except Exception as e: st.error(f"❌ 錯誤: {e}")

# --- 4. 介面顯示 ---
if "results" not in st.session_state:
    run_precise_scan()

if st.session_state.get("results"):
    # 表格顯示代號、名稱、現價、訊號(F欄)、量能(G欄)
    st.table(pd.DataFrame(st.session_state["results"])[["sid", "名稱", "現價", "訊號", "量能"]])
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📈 {res['sid']} {res['名稱']}", key=f"btn_{idx}"):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])

if st.sidebar.button("重新掃描"):
    st.session_state.pop("results", None)
    st.rerun()