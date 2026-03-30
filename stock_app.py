# --- 修正後的 3. 掃描與執行邏輯 ---
def run_precise_scan():
    try:
        csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv'
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df_sheet = pd.read_csv(io.StringIO(res.text))
        
        # 抓取前 6 欄 (0=代號, 1=名稱, 2=短均, 3=長均, 5=自訂訊號)
        # 注意：iloc[:, [0, 1, 2, 3, 5]] 代表 A, B, C, D, F 欄
        raw_rows = df_sheet.iloc[:, [0, 1, 2, 3, 5]].values.tolist()
        valid_stocks = [r for r in raw_rows if pd.notnull(r[0]) and str(r[0]).strip() != ""]
        
        final_list = [] 
        bar = st.progress(0)
        for i, item in enumerate(valid_stocks):
            try:
                sid_raw = str(item[0]).split('.')[0].strip()
                name = str(item[1])
                sP = (int(float(item[2])) if pd.notnull(item[2]) else 21)
                lP = (int(float(item[3])) if pd.notnull(item[3]) else 152)
                # --- 關鍵修正：讀取 F 欄內容 ---
                sheet_signal = str(item[4]) if pd.notnull(item[4]) else ""
                
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                df = yf.download(sid_full, period="250d", interval="1d", progress=False)
                
                if df.empty or len(df) < lP: continue
                df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
                curPrice = float(df['Close'].iloc[-1])
                
                # 保留原有掃描邏輯，但顯示內容改用 F 欄
                pList = [curPrice] + df['Close'].tolist()[::-1][1:]
                def getMA(arr, per, off):
                    p = int(per)
                    return sum(arr[off : p + off]) / p if len(arr) >= p + off else 0
                    
                maST, maSY = getMA(pList, sP, 0), getMA(pList, sP, 1)
                maLT, maLY, maLB = getMA(pList, lP, 0), getMA(pList, lP, 1), getMA(pList, lP, 2)
                
                # 判斷是否需要加入清單 (觸發條件不變)
                is_alert = False
                if (pList[1] >= maSY and pList[0] < maST) or \
                   (pList[2] < maLB and pList[1] > maSY and df['Low'].iloc[-1] > maLT) or \
                   (pList[1] < maSY and pList[0] > maST):
                    is_alert = True
                
                if is_alert:
                    final_list.append({
                        "sid": sid_full, 
                        "名稱": name, 
                        "現價": f"{curPrice:.2f}", 
                        "訊號": sheet_signal, # ⬅️ 這裡改為顯示 F 欄內容
                        "df": df, 
                        "sP": sP, 
                        "lP": lP
                    })
            except Exception: continue
            bar.progress((i + 1) / len(valid_stocks))
        st.session_state["results"] = final_list
    except Exception as e: st.error(f"❌ 讀取錯誤: {e}")

# --- 繪圖函數維持上一次調整好的 (黑底、寬比例、下方圖例、中文化) ---
def draw_kline(df, sid, name, sP, lP):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, 
                        subplot_titles=(f'{sid} {name} 均線走勢', '成交量能'), 
                        row_width=[0.3, 0.7])
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線', increasing_line_color='#FF3333', decreasing_line_color='#00AA00'), row=1, col=1)
    df_ma = df.copy()
    df_ma['MA_S'] = df_ma['Close'].rolling(window=int(sP)).mean()
    df_ma['MA_L'] = df_ma['Close'].rolling(window=int(lP)).mean()
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_S'], name=f'短均({sP}MA)', line=dict(color='SpringGreen', width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_L'], name=f'長均({lP}MA)', visible='legendonly', line=dict(color='Magenta', width=2)), row=1, col=1)
    colors = ['#FF3333' if row['Close'] >= row['Open'] else '#00AA00' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)
    fig.update_layout(template="plotly_dark", paper_bgcolor="black", plot_bgcolor="black", font=dict(family="Microsoft JhengHei", size=14, color="white"), xaxis_rangeslider_visible=False, height=500, dragmode='pan', newshape=dict(line_color='White', line_width=2), margin=dict(t=50, b=50, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5))
    config = {'scrollZoom': True, 'displayModeBar': True, 'displaylogo': False, 'modeBarButtonsToAdd': ['drawline', 'eraseshape'], 'modeBarButtonsToRemove': ['lasso2d', 'select2d', 'zoom2d'], 'locale': 'zh-TW'}
    st.plotly_chart(fig, use_container_width=True, config=config)