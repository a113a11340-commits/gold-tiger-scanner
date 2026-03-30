import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

# --- 1. 介面最上方的按鈕 ---
st.title("均線系統：全自動監控")

# 將重新掃描按鈕移到最上方
if st.button("🔄 重新執行掃描", use_container_width=True):
    run_precise_scan()

# --- 2. 修正後的繪圖函數 (移除成交量、工具欄，線條極細) ---
def draw_kline(df, sid, name, sP, lP):
    # 只建立一個圖表 (移除子圖，因為不需要成交量)
    fig = go.Figure()

    # K線圖 (線條寬度設為 1)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        name='K線', increasing_line_color='#FF3333', decreasing_line_color='#00AA00',
        line=dict(width=1)
    ))
    
    # 均線計算
    df_ma = df.copy()
    df_ma['MA_S'] = df_ma['Close'].rolling(window=int(sP)).mean()
    df_ma['MA_L'] = df_ma['Close'].rolling(window=int(lP)).mean()
    
    # 極細均線 (width=1)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_S'], name=f'短均({sP})', 
                             line=dict(color='SpringGreen', width=1)))
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_L'], name=f'長均({lP})', 
                             visible='legendonly', line=dict(color='Magenta', width=1)))
    
    # 介面佈局優化
    fig.update_layout(
        title=f'{sid} {name}',
        template="plotly_dark", paper_bgcolor="black", plot_bgcolor="black",
        font=dict(family="Microsoft JhengHei", size=12, color="white"),
        xaxis_rangeslider_visible=False, 
        height=400, # 縮小高度適合手機
        dragmode='pan',
        margin=dict(t=50, b=20, l=10, r=10), 
        # 標籤移到圖表內上方，節省空間
        legend=dict(
            orientation="h", 
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(0,0,0,0.5)"
        )
    )

    # 徹底移除工具欄
    config = {
        'scrollZoom': True, 
        'displayModeBar': False, # 關閉工具欄
        'showAxisDragHandles': False,
        'showAxisRangeEntryBoxes': False
    }
    
    st.plotly_chart(fig, use_container_width=True, config=config)

# --- 3. 掃描結果表格 ---
if st.session_state.get("results"):
    # 顯示包含量能資訊的表格
    df_res = pd.DataFrame(st.session_state["results"])
    st.table(df_res[["sid", "名稱", "現價", "訊號", "量能"]])
    
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📈 查看 {res['sid']} {res['名稱']}", key=f"btn_{idx}", use_container_width=True):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])