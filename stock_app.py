import streamlit as st
import plotly.graph_objects as go
import pandas as pd

# --- 1. 核心繪圖函數：高度100 + 雙均線 + 深色背景 ---
def draw_kline(df, sid, name, sP, lP):
    # 建立圖表
    fig = go.Figure()

    # K線圖 (寬度設為 1，確保手機看得見)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        name='K', increasing_line_color='#FF3333', decreasing_line_color='#00AA00',
        line=dict(width=1)
    ))
    
    # 計算均線
    df_ma = df.copy()
    ma_s = df_ma['Close'].rolling(window=int(sP)).mean()
    ma_l = df_ma['Close'].rolling(window=int(lP)).mean()
    
    # 同時顯示短均(綠)與長均(紫)
    fig.add_trace(go.Scatter(x=df_ma.index, y=ma_s, name='短', line=dict(color='SpringGreen', width=1)))
    fig.add_trace(go.Scatter(x=df_ma.index, y=ma_l, name='長', line=dict(color='Magenta', width=1)))
    
    fig.update_layout(
        paper_bgcolor="black", # 改回黑色背景，防止全白
        plot_bgcolor="black", 
        height=100,           # 極致縮小高度
        margin=dict(t=5, b=5, l=0, r=0),
        xaxis_rangeslider_visible=False,
        showlegend=False, 
        dragmode='pan',
        # 隱藏座標軸資訊，讓手機畫面不擁擠
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, fixedrange=True, showticklabels=False)
    )

    # 工具欄配置：保留放大縮小
    config = {
        'displayModeBar': True,
        'displaylogo': False,
        'modeBarButtonsToAdd': ['zoomIn2d', 'zoomOut2d'],
        'modeBarButtonsToRemove': [
            'toImage', 'select2d', 'lasso2d', 'pan2d', 'zoom2d',
            'autoScale2d', 'resetScale2d', 'hoverClosestCartesian'
        ],
    }
    
    st.plotly_chart(fig, use_container_width=True, config=config)

# --- 2. 主程式介面 ---
st.title("均線監控系統")

# 重新掃描按鈕放在最上方
if st.button("🔄 重新執行掃描", use_container_width=True):
    # 這裡執行您的掃描邏輯，並更新 st.session_state["results"]
    st.rerun()

# --- 3. 表格顯示：合併量能，解決手機滑動問題 ---
if "results" in st.session_state and st.session_state["results"]:
    res_df = pd.DataFrame(st.session_state["results"])
    
    # 將「訊號」與「量能」合併在同一欄
    res_df["訊號 | 量能"] = res_df["訊號"].astype(str) + " / " + res_df["量能"].astype(str)
    
    # 顯示精簡後的表格，字體會自動適應手機
    st.table(res_df[["sid", "名稱", "現價", "訊號 | 量能"]])
    
    # 顯示每支股票的按鈕與圖表
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📈 {res['sid']} {res['名稱']}", key=f"btn_{idx}", use_container_width=True):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])