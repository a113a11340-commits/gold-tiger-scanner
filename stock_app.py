import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-區間監控版")

MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    base_url = MY_SHEET_URL.split('/edit')[0]
    csv_url = f"{base_url}/export?format=csv&gid=0"
    try:
        res = requests.get(csv_url, timeout=15)
        res.encoding = 'utf-8'
        if res.status_code != 200: return []
        raw_df = pd.read_csv(io.StringIO(res.text))
    except Exception: return []

    results = []
    for i, row in raw_df.iterrows():
        try:
            if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
            
            # 核心過濾：只要 F 欄位有字，就代表你想監控這檔，不論是否在區間內都顯示
            sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
            if sign == "": continue 
            
            sid_raw = str(row.iloc[0]).split('.')[0].strip()
            sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma_p = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma_p = pd.to_numeric(row.iloc[3], errors='coerce')

            stock = yf.download(sid_full, period="120d", progress=False)
            if not stock.empty:
                if isinstance(stock.columns, pd.MultiIndex):
                    stock.columns = stock.columns.get_level_values(0)
                
                # 計算均線
                s_ma_val = int(s_ma_p) if pd.notna(s_ma_p) else 20
                l_ma_val = int(l_ma_p) if pd.notna(l_ma_p) else 60
                stock['MA_S'] = stock['Close'].rolling(window=s_ma_val).mean()
                stock['MA_L'] = stock['Close'].rolling(window=l_ma_val).mean()
                
                # --- 自動尋找最近的箱型區間 (目測輔助用) ---
                view_df = stock.tail(42)
                best_box = None
                idx = 0
                while idx < len(view_df) - 2:
                    w = view_df.iloc[idx:idx+3]
                    w_max, w_min = w['High'].max(), w['Low'].min()
                    # 波動在 3% 內視為基礎區間
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

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    with st.spinner('讀取訊號中...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-訊號監控")
with col_b:
    if st.button("🔄 刷新"):
        del st.session_state["data"]
        st.rerun()

if not data_list:
    st.info("試算表 F 欄位目前無訊號標註。")
else:
    for item in data_list:
        df = item['df']
        total_len = len(df)
        header = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}"
        
        with st.expander(header, expanded=True):
            fig = go.Figure()
            
            # 畫灰色小框 (只要有找到區間就畫，不管現在價格在哪)
            if item['box']:
                b = item['box']
                fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                              line=dict(width=0), fillcolor="gray", opacity=0.3)

            # K線 (2個月視野，K棒寬度設為 1.2 較好目測)
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F',
                line=dict(width=1.2)
            ))
            
            # 短/長均線
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#0055CC', width=2.5), name="短均"))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#888888', width=1, dash='dot'), name="長均"))

            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False,
                margin=dict(l=5, r=5, t=5, b=5),
                # 固定 2 個月 (42天) 視角
                xaxis=dict(type='category', range=[total_len - 42, total_len - 0.5], showticklabels=False, fixedrange=True),
                yaxis=dict(side='right', tickfont=dict(size=11), fixedrange=True),
                hovermode=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False})