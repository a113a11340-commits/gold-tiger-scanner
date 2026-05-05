def run_scan():
    all_targets = []
    # --- 步驟 1: 讀取標的 ---
    for gid in GIDS:
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code != 200: continue
            raw_df = pd.read_csv(io.StringIO(res.text))
            for _, row in raw_df.iterrows():
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                all_targets.append({
                    "sid": f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw,
                    "name": row.iloc[1] if pd.notna(row.iloc[1]) else "未命名",
                    "s_ma_p": pd.to_numeric(row.iloc[2], errors='coerce'),
                    "l_ma_p": pd.to_numeric(row.iloc[3], errors='coerce')
                })
        except: continue

    if not all_targets: return []

    results = []
    for item in all_targets:
        try:
            sid = item['sid']
            # 改用 Ticker 物件獲取即時與歷史數據
            tk = yf.Ticker(sid)
            
            # --- 抓取即時成交價 (與 GAS 的 regularMarketPrice 同步) ---
            # yfinance 的 fast_info 提供了最接近實時的快照
            curr_p = tk.fast_info.get('last_price') 
            if curr_p is None: continue

            # 抓取歷史數據來計算均線 (抓 100 天夠算均線即可)
            stock = tk.history(period="100d")
            stock.dropna(subset=['Close'], inplace=True)
            if len(stock) < 2: continue

            # --- 均線計算 ---
            s_val = item.get('s_ma_p')
            if pd.isna(s_val): continue
            s_day = int(s_val)
            
            # 建立包含「今日最新價」的數列，模仿 GAS 的 pList = [curPrice].concat(closes.slice(1))
            # 我們保留歷史最後一筆作為「昨日」，今日則強制代入 curr_p
            hist_closes = stock['Close'].tolist()
            p_list = [curr_p] + hist_closes[::-1][1:] # [今日即時, 昨日收盤, 前日收盤...]

            # 計算均線 (手動計算以確保與 GAS 邏輯一致)
            def get_ma(arr, period, offset):
                sub = arr[offset : offset + period]
                return sum(sub) / period if len(sub) == period else 0

            curr_ma = get_ma(p_list, s_day, 0)
            prev_ma = get_ma(p_list, s_day, 1)
            prev_p = p_list[1] # 歷史序列的倒數第二筆

            # --- 訊號判定 (昨下今上) ---
            is_break_above = (prev_p <= prev_ma) and (curr_p > curr_ma)
            is_break_below = (prev_p >= prev_ma) and (curr_p < curr_ma)

            if is_break_above or is_break_below:
                bias = ((curr_p - curr_ma) / curr_ma) * 100
                trend = "⤴️上揚" if curr_ma > prev_ma else "⤵️下彎"
                icon = "🚀 剛突破" if is_break_above else "🚨 剛跌破"
                
                # 為了繪圖，我們把最新的即時價格更新進 dataframe
                stock.iloc[-1, stock.columns.get_loc('Close')] = curr_p
                stock['MA_S'] = stock['Close'].rolling(window=s_day).mean()

                item.update({
                    "df": stock,
                    "sign": f"{icon} {s_day}MA ({trend}) | 即時價: {curr_p:.2f} | MA: {curr_ma:.2f} | 乖離: {bias:.2f}%",
                })
                results.append(item)
        except: continue
    return results