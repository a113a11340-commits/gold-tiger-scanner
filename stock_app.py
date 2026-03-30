# --- 修正後的 3. 掃描與讀取函數 (加入 G 欄讀取) ---
def run_precise_scan():
    try:
        csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv'
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df_sheet = pd.read_csv(io.StringIO(res.text))
        
        # 讀取 A(0), B(1), C(2), D(3), F(5), G(6) 欄
        # iloc[:, [0, 1, 2, 3, 5, 6]] 分別代表 代號, 名稱, 短均, 長均, 訊號, 量能
        raw_rows = df_sheet.iloc[:, [0, 1, 2, 3, 5, 6]].values.tolist()
        valid_stocks = [r for r in raw_rows if pd.notnull(r[0])]
        
        final_list = [] 
        bar = st.progress(0)
        for i, item in enumerate(valid_stocks):
            try:
                sid_raw = str(item[0]).split('.')[0].strip()
                name = str(item[1])
                sP, lP = int(float(item[2])), int(float(item[3]))
                sheet_signal = str(item[4]) if pd.notnull(item[4]) else "" # F欄: 訊號
                sheet_volume = str(item[5]) if pd.notnull(item[5]) else "" # G欄: 量能 ⬅️ 新增
                
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                df = yf.download(sid_full, period="250d", progress=False)
                if df.empty: continue
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                
                # 判斷邏輯
                curP = df['Close'].iloc[-1]
                maS = df['Close'].rolling(window=sP).mean().iloc[-1]
                maS_y = df['Close'].rolling(window=sP).mean().iloc[-2]
                close_y = df['Close'].iloc[-2]
                
                if (close_y >= maS_y and curP < maS) or (close_y < maS_y and curP > maS):
                    final_list.append({
                        "sid": sid_full, 
                        "名稱": name, 
                        "現價": f"{curP:.2f}", 
                        "訊號": sheet_signal, 
                        "量能": sheet_volume, # ⬅️ 顯示在表格中
                        "df": df, 
                        "sP": sP, 
                        "lP": lP
                    })
            except: continue
            bar.progress((i + 1) / len(valid_stocks))
        st.session_state["results"] = final_list
    except Exception as e: st.error(f"❌ 讀取錯誤: {e}")

# --- 介面顯示部分 (同步更新表格欄位) ---
if st.session_state.get("results"):
    # 表格中新增 "量能" 欄位顯示
    st.table(pd.DataFrame(st.session_state["results"])[["sid", "名稱", "現價", "訊號", "量能"]])
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📈 {res['sid']} {res['名稱']}", key=f"btn_{idx}"):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])