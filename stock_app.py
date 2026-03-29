def draw_kline(df, sid, name, sP, lP):
    # 建立子圖
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
    
    # 短均線：顯示
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_S'], name=f'短均({sP}MA)', 
                             line=dict(color='SpringGreen', width=2)), row=1, col=1)
    
    # 長均線：預設隱藏 (點圖例才出來)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_L'], name=f'長均({lP}MA)', 
                             visible='legendonly', 
                             line=dict(color='Magenta', width=2)), row=1, col=1)
    
    # B. 成交量圖
    colors = ['#FF3333' if row['Close'] >= row['Open'] else '#00AA00' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)

    # --- 關鍵修正：dragmode 設為 pan (平移)，解決滑動變成指定區域的問題 ---
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="black",
        plot_bgcolor="black",
        font=dict(family="Microsoft JhengHei", size=14, color="white"),
        xaxis_rangeslider_visible=False,
        height=800,
        dragmode='pan',            # ⬅️ 這裡改好了！滑動時只會左右平移，不會變成框選放大
        newshape=dict(line_color='White', line_width=2), 
        margin=dict(t=80, b=50, l=10, r=10)
    )

    # --- 關鍵修正：工具列強制顯示橡皮擦 ---
    config = {
        'modeBarButtonsToAdd': [
            'eraseshape',   # ⬅️ 橡皮擦 (圖示通常是一個橡皮擦或打叉的方塊)
            'drawline',     # 畫線
            'drawrect'      # 畫框
        ],
        'scrollZoom': True,
        'displaylogo': False,
        'displayModeBar': True, # 強制顯示工具列
        'modeBarButtonsToRemove': ['lasso2d', 'select2d', 'zoom2d'] # 移除 zoom2d 徹底解決框選問題
    }
    
    st.plotly_chart(fig, use_container_width=True, config=config)