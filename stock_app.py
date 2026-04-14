import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁設定 ---
st.set_page_config(layout="wide", page_title="上班族快速監控版")

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
                f_signal = str(row.iloc[5]) if len(row) > 5 and pd.notna(row.iloc[5]) else ""

                stock = yf.download(sid_full, period="240d", progress=False)
                if stock.empty: continue
                if isinstance(stock.columns, pd.MultiIndex): stock.columns = stock.columns.get_level_values(0)
                stock['MA_S'] = stock['Close'].rolling(window=int(s_ma_val)).mean()
                
                # --- 箱型掃描與分類邏輯 ---
                view_df = stock.tail(42)
                boxes = []
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
                        boxes.append({'start': view_df.index[start_i], 'end': view_df.index[idx], 'top': w_max, 'bottom': w_min})
                    idx += 1
                
                # 判定分類
                cat = "盤整中"
                latest_close = stock.iloc[-1]['Close']
                if boxes:
                    if latest_close > boxes[-1]['top']: cat = "🚀 已突破"
                    elif latest_close < boxes[-1]['bottom']: cat = "⚠️ 跌破中"

                all_results.append({
                    "sid": sid_full, "name": name, "s_ma": s_ma_val, "df": stock, 
                    "f_signal": f_signal, "boxes": boxes, "cat": cat
                })
            except Exception: continue
    return all_results

if "data" not in st.session_state:
    with st.spinner('掃描訊號中...'):
        st.session_state["data"] = run_scan()

# --- 2. 戰情儀表板 ---
data = st.session_state["data"]
breakout_list = [d for d in data if d['cat'] == "🚀 已突破"]
breakdown_list = [d for d in data if d['cat'] == "⚠️ 跌破中"]
sideways_list = [d for d in data if d['cat'] == "盤整中"]

st.title("💼 上班快速看盤儀表板")
col1, col2, col3 = st.columns(3)
col1.metric("🚀 突破壓力", f"{len(breakout_list)} 檔")
col2.metric("⚠️ 跌破支撐", f"{len(breakdown_list)} 檔")
col3.metric("⌛ 區間整理", f"{len(sideways_list)} 檔")

# --- 3. 分頁呈現 ---
tab1, tab2, tab3 = st.tabs(["🚀 優先看突破", "⚠️ 風險監控(跌破)", "⌛ 全部標的"])

def draw_stock(item_list):
    for item in item_list:
        df = item['df']
        title = f"{item['sid']} {item['name']} ➔ {item['f_signal']}"
        with st.expander(title, expanded=(item['cat'] != "盤整中")):
            fig = go.Figure()
            # 畫箱型與最新紅線
            for b in item['boxes']:
                fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                              line=dict(width=0), fillcolor="gray", opacity=0.25)
            if item['boxes']:
                lb = item['boxes'][-1]
                fig.add_shape(type="line", x0=lb['start'], x1=df.index[-1], y0=lb['top'], y1=lb['top'],
                              line=dict(color="Red", width=2, dash="dash"))

            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                                         increasing_line_color='#d62728', decreasing_line_color='#2ca02c'))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#1f77b4', width=1.5)))
            fig.update_layout(xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
                              yaxis=dict(side='right'), height=300, margin=dict(l=5, r=5, t=5, b=5), template="plotly_white", showlegend=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            
            # 下方簡潔數據
            c1, c2 = st.columns(2)
            is_two = (df.iloc[-1]['High'] > df.iloc[-2]['High'])
            c1.write(f"天數: {len(df[item['boxes'][-1]['start']:]) if item['boxes'] else 'N/A'} | 二日: {'✅' if is_two else '❌'}")
            if item['boxes']:
                diff = round(df.iloc[-1]['Close'] - item['boxes'][-1]['top'], 2)
                c2.write(f"位移: {diff} | 均線: {item['s_ma']}MA")

with tab1: draw_stock(breakout_list)
with tab2: draw_stock(breakdown_list)
with tab3: draw_stock(data)