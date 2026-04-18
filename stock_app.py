# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-區間監控版")

MY_SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
GIDS = ["0", "1241939414", "534437042"]

def run_scan():
    all_raw_rows = []
    for gid in GIDS:
        csv_url = f"{MY_SHEET_BASE}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=15)
            res.encoding = 'utf-8'
            if res.status_code == 200:
                df_part = pd.read_csv(io.StringIO(res.text))
                all_raw_rows.append(df_part)
        except Exception: continue

    if not all_raw_rows: return []
    raw_df = pd.concat(all_raw_rows, ignore_index=True)

    temp_rows = []
    all_sids_set = set() # 用 set 來取得「不重複」的代號清單供下載
    
    for i, row in raw_df.iterrows():
        if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
        sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
        if sign == "": continue 
        
        sid_raw = str(row.iloc[0]).split('.')[0].strip()
        sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
        
        all_sids_set.add(sid_full) # 這裡只存不重複的代號用於 yfinance
        # 但在 temp_rows 中，我們保留每一行（即使代號重複也會存進去）
        temp_rows.append({'sid_full': sid_full, 'row': row, 'sign': sign})

    if not temp_rows: return []

    # --- 一次性下載所有需要的代號（不重複） ---
    download_list = list(all_sids_set)
    all_data = yf.download(download_list, period="120d", progress=False, group_by='ticker')
    
    results = []
    for item in temp_rows: # 這裡會跑遍每一行，包含重複的代號
        try:
            sid_full = item['sid_full']
            row = item['row']
            sign = item['sign']
            
            # 從下載的大數據包中提取對應代號的資料
            if len(download_list) > 1:
                stock = all_data[sid_full].copy()
            else:
                stock = all_data.copy()
            
            if isinstance(stock.columns, pd.MultiIndex):
                stock.columns = stock.columns.get_level_values(0)
            
            if stock.empty or 'Close' not in stock.columns: continue

            # --- 維持你原有的計算邏輯 ---
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma_p = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma_p = pd.to_numeric(row.iloc[3], errors='coerce')
            s_ma_val = int(s_ma_p) if pd.notna(s_ma_p) else 20
            l_ma_val = int(l_ma_p) if pd.notna(l_ma_p) else 60
            stock['MA_S'] = stock['Close'].rolling(window=s_ma_val).mean()
            stock['MA_L'] = stock['Close'].rolling(window=l_ma_val).mean()
            
            view_df = stock.tail(42)
            best_box = None
            idx = 0
            while idx < len(view_df) - 2:
                w = view_df.iloc[idx:idx+3]
                w_max, w_min = w['High'].max(), w['Low'].min()
                if (w_max - w_min) / w_min <= 0.03:
                    start_i = idx
                    while idx < len(view_df) - 1:
                        nr = view_df.iloc[idx+1]
                        if nr['Low'] >= w_min * 0.985 and nr['High'] <= w_max * 1.015:
                            idx += 1
                        else:
                            break
                    best_box = {'start': view_df.index[start_i], 'end': view_df.index[idx], 'top': w_max, 'bottom': w_min}
                idx += 1

            latest_p = float(stock['Close'].iloc[-1])
            results.append({
                "sid": sid_full, "name": name, "price": latest_p,
                "s_ma_p": s_ma_val, "l_ma_p": l_ma_val, "sign": sign, "df": stock,
                "box": best_box 
            })
        except Exception: continue
    return results