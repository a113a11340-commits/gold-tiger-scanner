import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import requests
import io

# --- 1. 頁面設定與重新掃描按鈕 ---
st.set_page_config(layout="wide")
st.markdown('<style>div.block-container{padding-top:1rem;}</style>', unsafe_allow_html=True)

if st.button("🔄 重新掃描試算表", use_container_width=True):
    # 這裡放你原本的 run_precise_scan() 邏輯
    pass

# --- 2. 核心繪圖函數 (極細、雙線、透明、低高度) ---
def draw_kline(df, sid, name, sP, lP):
    fig = go.Figure()

    # 極細 K 線 (0.5 寬度)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        name='K', increasing_line_color='#FF3333', decreasing_line_color='#00AA00',
        line=dict(width=0.5)
    ))
    
    # 計算並顯示雙均線
    df_ma = df.copy()
    ma_s = df_ma['Close'].rolling(window=int(sP)).mean()
    ma_l = df_ma['Close'].rolling(window=int(lP)).mean()
    
    # 短均(綠)與長均(紫)
    fig.add_trace(go.Scatter(x=df_ma.index, y=ma_s, name='短', line=dict(color='SpringGreen', width=0.5)))
    fig.add_trace(go.Scatter(x=df_ma.index, y=ma_l, name='長', line=dict(color='Magenta', width=0.5)))
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", # 背景透明
        plot_bgcolor="rgba(0,0,0,0)", 
        height=100,                   # 高度減半再減半
        margin=dict(t=5, b=5, l=0, r=0),
        xaxis_rangeslider_visible=False,
        showlegend=False, 
        font=dict(size=8, color="white"),
        dragmode='pan',
        # 隱藏座標軸與格線，讓手機看圖不跑位
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, fixedrange=True)
    )

    config = {
        'displayModeBar': True,
        'displaylogo': False,
        'modeBarButtonsToAdd': ['zoomIn2d', 'zoomOut2d'], # 加入放大縮小
        'modeBarButtonsToRemove': [
            'toImage', 'select2d', 'lasso2d', 'pan2d', 'zoom2d',
            'autoScale2d', 'resetScale2d', 'hoverClosestCartesian'
        ],
    }
    
    st.markdown('<style>div[data-testid="stPlotlyChart"] { background-color: transparent !important; }</style>', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config=config)

# --- 3. 表格顯示 (合併量能與訊號，免移動) ---
if "results" in st.session_state and st.session_state["results"]:
    res_df = pd.DataFrame(st.session_state["results"])
    # 把 G 欄量能直接併入，手機不用橫移
    res_df["訊號/量能"] = res_df["訊號"].astype(str) + " | " + res_df["量能"].astype(str)
    
    st.table(res_df[["sid", "名稱", "現價", "訊號/量能"]])
    
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📈 {res['sid']} {res['名稱']}", key=f"btn_{idx}", use_container_width=True):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])