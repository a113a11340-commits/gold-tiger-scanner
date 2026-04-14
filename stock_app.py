import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io
from collections import Counter

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

                # 抓取 240 天數據 (約 8 個月) 用於精確壓力線與 MA 計算
                stock = yf.download(sid_full, period="240d", progress=False)
                if stock.empty: continue
                if isinstance(stock.columns, pd.MultiIndex): stock.columns = stock.columns.get_level_values(0)
                
                stock['MA_S'] = stock['Close'].rolling(window=int(s_ma_val)).mean()
                latest = stock.iloc[-1]
                prev = stock.iloc[-2]
                
                box_info = {"has_box": False, "days": 0, "res_line": 0, "low_line": 0, "type": ""}
                status_tags = []

                # --- 判定：二日法則 ---
                is_two_day = (prev['Close'] > prev['MA_S'] * 1.01 and latest['High'] > prev['High'])

                # --- 判定：箱型區間 (3天內邏輯) ---
                # 抓取最近 3 天的資料
                recent_3 = stock.tail(3)
                # 判定條件：最近 3 天的高低點波幅在 3% 內，或皆與均線產生重合
                is_box_range = (recent_3['High'].max() - recent_3['Low'].min()) / recent_3['Low'].min() <= 0.03
                is_touching_ma = ((recent_3['High'] >= recent_3['MA_S']) & (recent_3['Low'] <= recent_3['MA_S'])).all()

                if is_box_range or is_touching_ma:
                    # 往前回溯找出連續整理的天數
                    temp_idx = len(stock) - 3
                    while temp_idx > 0:
                        p_row = stock.iloc[temp_idx - 1]
                        # 持續整理判定
                        p_box = (max(stock.iloc[temp_idx-1:len(stock)]['High']) - min(stock.iloc[temp_idx-1:len(stock)]['Low'])) / min(stock.iloc[temp_idx-1:len(stock)]['Low']) <= 0.05
                        if p_box: temp_idx -= 1
                        else: break
                    
                    box_start_date = stock.index[temp_idx]
                    box_range_df = stock.iloc[temp_idx:]
                    
                    # 計算壓力共振線 (實體頂與影線頂共 21:08 畫法)
                    pts = []
                    for _, b_row in box_range_df.iterrows():
                        pts.append(round(max(b_row['Open'], b_row['Close']), 1))
                        pts.append(round(b_row['High'], 1))
                    res_p = Counter(pts).most_common(1)[0][0]

                    box_info.update({
                        "has_box": True,
                        "start_date": box_start_date,
                        "days": len(box_range_df),
                        "res_line": res_p,
                        "low_line": box_range_df['Low'].min(),
                        "type": "浮空箱型" if not is_touching_ma else "觸線箱型"
                    })
                    
                    if latest['Close'] > res_p: status_tags.append("突破")
                    else: status_tags.append("盤整")

                all_results.append({
                    "sid": sid_full, "name": name, "price": f"{latest['Close']:.2f}",
                    "s_ma": s_ma_val, "tags": " | ".join(status_tags) if status_tags else "觀察中",
                    "df": stock, "box": box_info, "is_two_day": is_two_day
                })
            except Exception: continue
    return all_results

# --- 3. UI 呈現 ---
st.title("📈 市場型態掃描系統")
if "data" not in st.session_state:
    with st.spinner('正在分析市場數據...'):
        st.session_state["data"] = run_scan()

for item in st.session_state["data"]:
    df = item['df']
    with st.expander(f"{item['sid']} {item['name']} | 現價: {item['price']} | 狀態: {item['tags']}", expanded=True):
        
        # 圖表區 (視覺固定 2 個月)
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                                     increasing_line_color='#d62728', decreasing_line_color='#2ca02c', line=dict(width=1.2)))
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#1f77b4', width=1.5), hoverinfo='skip'))

        if item['box']['has_box']:
            b = item['box']
            # 紅色虛線壓力線
            fig.add_shape(type="line", x0=b['start_date'], x1=df.index[-1], y0=b['res_line'], y1=b['res_line'],
                          line=dict(color="Red", width=2, dash="dash"))
            # 灰色小框箱型區間
            fig.add_shape(type="rect", x0=b['start_date'], x1=df.index[-1], y0=b['low_line'], y1=b['res_line'],
                          line=dict(width=0), fillcolor="gray", opacity=0.15)

        fig.update_layout(height=350, template="plotly_white", showlegend=False,
                          xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
                          yaxis=dict(side='right', fixedrange=True), margin=dict(l=5, r=5, t=5, b=5))
        st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False})

        # --- 文字數據說明區 (專業條列版) ---
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**【箱型區間數據】**")
            if item['box']['has_box']:
                st.write(f"• 當前型態：{item['box']['type']}")
                st.write(f"• 連續整理天數：{item['box']['days']} 天")
                st.write(f"• 共振壓力價格：{item['box']['res_line']}")
                st.write(f"• 區間支撐價格：{item['box']['low_line']}")
            else:
                st.write("• 狀態：目前未形成明顯 3 日箱型區間")
        
        with c2:
            st.markdown("**【技術指標判定】**")
            st.write(f"• 二日法則：{'符合 (創昨日高點)' if item['is_two_day'] else '未符合 (未過昨日高點)'}")
            if item['box']['has_box']:
                diff = round((float(item['price']) - item['box']['res_line']), 2)
                st.write(f"• 價格位移：{'突破中 (+' if diff > 0 else '壓力下 ('}{diff})")
            st.write(f"• 設定均線：{item['s_ma']} MA")
        st.divider()