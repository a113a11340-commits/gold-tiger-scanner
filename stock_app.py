import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁與資料讀取設定 ---
st.set_page_config(layout="wide", page_title="技術分析監控系統")

# 請根據實際情況填入你的 Google Sheet 資訊
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24"
SHEET_GIDS = ["0", "1"] 

def run_scan():
    all_results = []
    for gid in SHEET_GIDS:
        csv_url = f"{MY_SHEET_URL}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=15)
            res.encoding = 'utf-8'
            if res.status_code != 200: continue
            raw_df = pd.read_csv(io.StringIO(res.text))
        except Exception: continue

        for i, row in raw_df.iterrows():
            try:
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
                s_ma_val = pd.to_numeric(row.iloc[2], errors='coerce')
                if pd.isna(s_ma_val): continue 

                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
                
                # 讀取 F 欄位訊號 (索引 5)
                f_signal = str(row.iloc[5]) if len(row) > 5 and pd.notna(row.iloc[5]) else ""

                # 抓取 240 天數據供計算
                stock = yf.download(sid_full, period="240d", progress=False)
                if stock.empty: continue
                if isinstance(stock.columns, pd.MultiIndex): stock.columns = stock.columns.get_level_values(0)
                
                stock['MA_S'] = stock['Close'].rolling(window=int(s_ma_val)).mean()
                
                all_results.append({
                    "sid": sid_full, "name": name, "s_ma": s_ma_val, "df": stock, "f_signal": f_signal
                })
            except Exception: continue
    return all_results

# --- 2. 執行掃描 (快取機制) ---
if "data" not in st.session_state:
    with st.spinner('正在分析數據中...'):
        st.session_state["data"] = run_scan()

# --- 3. UI 呈現 ---
for item in st.session_state["data"]:
    df = item['df']
    # 標題加入 F 欄位訊號
    title_text = f"{item['sid']} {item['name']} ➔ {item['f_signal']}" if item['f_signal'] else f"{item['sid']} {item['name']}"
    
    with st.expander(title_text, expanded=True):
        
        # A. 掃描 2 個月 (42天) 內的所有箱型
        view_df = df.tail(42)
        boxes = []
        idx = 0
        while idx < len(view_df) - 2:
            w = view_df.iloc[idx:idx+3]
            w_max, w_min = w['High'].max(), w['Low'].min()
            # 箱型判定：高低點波幅 3% 內
            if (w_max - w_min) / w_min <= 0.03:
                start_i = idx
                while idx < len(view_df) - 1:
                    nr = view_df.iloc[idx+1]
                    if nr['Low'] >= w_min * 0.985 and nr['High'] <= w_max * 1.015:
                        idx += 1
                    else:
                        break
                boxes.append({'start': view_df.index[start_i], 'end': view_df.index[idx], 'top': w_max, 'bottom': w_min})
            idx += 1

        # B. 繪圖區
        fig = go.Figure()
        
        # 畫所有偵測到的灰色箱型 (僅小框)
        for b in boxes:
            fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                          line=dict(width=0), fillcolor="gray", opacity=0.25)

        # 僅針對「最新一個」箱型畫延伸紅色壓力線，避免畫面混亂
        if boxes:
            latest_b = boxes[-1]
            fig.add_shape(type="line", x0=latest_b['start'], x1=df.index[-1], y0=latest_b['top'], y1=latest_b['top'],
                          line=dict(color="Red", width=2, dash="dash"))

        # 畫 K 線
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                                     increasing_line_color='#d62728', decreasing_line_color='#2ca02c'))
        
        # 畫 均線
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#1f77b4', width=1.5)))

        # 設定顯示範圍與手機版優化
        fig.update_layout(xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
                          yaxis=dict(side='right'), height=350, margin=dict(l=5, r=5, t=5, b=5), 
                          template="plotly_white", showlegend=False)

        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

        # C. 下方數據說明區
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**【箱型區間數據】**")
            if boxes:
                curr = boxes[-1]
                # 計算整理天數
                days_in_box = len(view_df[curr['start']:])
                st.write(f"• 當前箱型整理：第 {days_in_box} 天")
                st.write(f"• 區間壓力價格：{curr['top']:.2f}")
                st.write(f"• 區間支撐價格：{curr['bottom']:.2f}")
            else:
                st.write("• 狀態：目前未觀測到 3 日箱型")
        
        with c2:
            st.markdown("**【技術訊號提醒】**")
            # 二日法則：今日最高 > 昨日最高
            is_two_day = (df.iloc[-1]['High'] > df.iloc[-2]['High'])
            st.write(f"• 二日法則：{'✅ 符合 (過昨高)' if is_two_day else '❌ 未符合'}")
            
            # 壓力攻防計算
            if boxes:
                diff = round(df.iloc[-1]['Close'] - boxes[-1]['top'], 2)
                st.write(f"• 攻防位移：{'🚀 已突破' if diff > 0 else '⌛ 壓力下'}({diff})")
            
            st.write(f"• 設定均線：{item['s_ma']} MA")
        st.divider()