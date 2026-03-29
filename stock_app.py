def draw_kline(df, sid, name, sP, lP):
    # 建立子圖：調整 row_width 比例，讓 K 線佔 80%
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.02, 
                        subplot_titles=(f'<b>{sid} {name} 均線走勢</b>', '<b>成交量能</b>'), 
                        row_width=[0.2, 0.8])

    # A. K線圖 (維持你原始的顏色)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        name='K線',
        increasing_line_color='#FF3333', decreasing_line_color='#00AA00'
    ), row=1, col=1)
    
    # 均線計算 (邏輯完全不動)
    df_ma = df.copy()
    df_ma['MA_S'] = df_ma['Close'].rolling(window=int(sP)).mean()
    df_ma['MA_L'] = df_ma['Close'].rolling(window=int(lP)).mean()
    
    # 均線繪製：加粗線條，顏色維持螢光綠與粉紅紫
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_S'], name=f'短均({sP}MA)', 
                             line=dict(color='SpringGreen', width=3)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_L'], name=f'長均({lP}MA)', 
                             line=dict(color='Magenta', width=3)), row=1, col=1)
    
    # B. 成交量圖
    colors = ['#FF3333' if row['Close'] >= row['Open'] else '#00AA00' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)

    # --- 修正重點：黑底、中文、大圖、移除工具 ---
    fig.update_layout(
        template="plotly_dark", # 確保黑底
        font=dict(
            family="Microsoft JhengHei, Apple LiGothic, sans-serif", # 確保繁體中文
            size=16
        ),
        xaxis_rangeslider_visible=False, 
        height=1000, # 增加到 1000，解決圖太小的問題
        dragmode=False, # 徹底停用畫線拖拽模式
        margin=dict(t=50, b=20, l=10, r=10) # 縮減邊距撐滿畫面
    )

    # 移除所有按鈕 (包括畫線工具、相機、縮放按鈕)
    config = {
        'displayModeBar': True,
        'modeBarButtonsToRemove': [
            'drawline', 'drawrect', 'eraseshape', 'drawcircle', 'drawopenpath', 
            'drawclosedpath', 'select2d', 'lasso2d', 'zoom2d', 'pan2d',
            'zoomIn2d', 'zoomOut2d', 'autoScale2d', 'resetScale2d', 'toImage', 'hoverClosestCartesian', 'hoverCompareCartesian'
        ], 
        'displaylogo': False
    }
    
    st.plotly_chart(fig, use_container_width=True, config=config)