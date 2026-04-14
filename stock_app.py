import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 設定與資料讀取 ---
st.set_page_config(layout="wide", page_title="核心訊號監控系統")

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
                short_ma_p = pd.to_numeric(row.iloc[2], errors='coerce') 
                long_ma_p = 60 
                
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"

                stock = yf.download(sid_full, period="240d", progress=False)
                if stock.empty: continue
                if isinstance(stock.columns, pd.MultiIndex): stock.columns = stock.columns.get_level_values(0)
                
                # 均線與量能計算
                stock['MA_S'] = stock['Close'].rolling(window=int(short_ma_p)).mean()
                stock['MA_L'] = stock['Close'].rolling(window=long_ma_p).mean()
                stock['V_MA5'] = stock['Volume'].rolling(window=5).mean()
                
                latest = stock.iloc[-1]
                prev = stock.iloc[-2]
                
                # --- 核心判定邏輯 ---
                # A. 均線訊號
                is_break_ma = (prev['Close'] <= prev['MA_S'] and latest['Close'] > latest['MA_S'])
                is_drop_ma = (prev['Close'] >= prev['MA_S'] and latest['Close'] < latest['MA_S'])
                
                # B. 箱型區間掃描
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
                
                # C. 箱型訊號
                is_break_box = False
                is_drop_box = False
                if boxes:
                    last_b = boxes[-1]
                    is_break_box = (latest['Close'] > last_b['top'])
                    is_drop_box = (latest['Close'] < last_b['bottom'])

                # --- 綜合訊號決定是否顯示 ---
                sig = None
                if is_break_ma or is_break_box: sig = "🚀 突破"
                elif is_drop_ma or is_drop_box: sig = "⚠️ 跌破"
                
                if sig:
                    ma_up = latest['MA_S'] > prev['MA_S']
                    vol_up = latest['Volume'] > latest['V_MA5']
                    box_days = len(view_df[boxes[-1]['start']:]) if boxes else 0
                    
                    all_results.append({
                        "sid": sid_full, "name": name, "df": stock, 
                        "price": latest['Close'], "ma_s_val": latest['MA_S'], "ma_up": ma_up,
                        "vol_up": vol_up, "sig": sig, "box_days": box_days, "boxes": boxes
                    })
            except Exception: continue
    return all_results

if "data" not in st.session_state:
    with st.spinner('訊號掃描中...'):
        st.session_state["data"] = run_scan()

st.title(f"⚡ 關鍵訊號監控 ({len(st.session_state['data'])} 檔發動)")

for item in st.session_state["data"]:
    ma_dir = "📈 均線上揚" if item['ma_up'] else "📉 均線走平"
    vol_dir = "🔥 量增" if item['vol_up'] else "☁️ 量縮"
    # 標題欄位：[訊號] 代號 名稱 | 價 | 均線 | 整理天數 | 狀態
    header = f"{item['sig']} {item['sid']} {item['name']} | 價:{item['price']:.2f} | {item['box_days']}天箱 | {ma_dir} | {vol_dir}"
    
    with st.expander(header, expanded=True):
        df = item['df']
        fig = go.Figure()
        
        # 畫灰色箱型
        if item['boxes']:
            lb = item['boxes'][-1]
            fig.add_shape(type="rect", x0=lb['start'], x1=lb['end'], y0=lb['bottom'], y1=lb['top'],
                          line=dict(width=0), fillcolor="gray", opacity=0.25)

        # 畫 K 線
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                                     increasing_line_color='#d62728', decreasing_line_color='#2ca02c'))
        
        # 畫長短均線 (藍色為你設定的短均，橘色為60MA)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#1f77b4', width=2.5), name='短均'))
        fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#ff7f0e', width=1.5), name='長均'))

        fig.update_layout(xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
                          yaxis=dict(side='right'), height=320, margin=dict(l=5, r=5, t=5, b=5), 
                          template="plotly_white", showlegend=False)

        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})