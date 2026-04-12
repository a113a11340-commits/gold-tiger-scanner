import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-靜態專業配色版")

MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv&gid=0'
    try:
        res = requests.get(csv_url, timeout=15, stream=True)
        res.encoding = 'utf-8'
        if res.status_code != 200: return []
    except Exception: return []

    raw_df = pd.read_csv(io.StringIO(res.text))
    results = []

    for i, row in raw_df.iterrows():
        try:
            if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
            sign = row.iloc[5] if pd.notna(row.iloc[5]) else ""
            if str(sign).strip() == "": continue 

            sid_raw = str(row.iloc[0]).split('.')[0].strip()
            sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma = pd.to_numeric(row.iloc[3], errors='coerce')

            stock = yf.download(sid_full, period="240d", progress=False)
            
            if not stock.empty:
                if isinstance(stock.columns, pd.MultiIndex):
                    stock.columns = stock.columns.get_level_values(0)
                
                ma_val = int(s_ma) if pd.notna(s_ma) else 20
                stock['MA_S'] = stock['Close'].rolling(window=ma_val).mean()
                
                box_data = None
                recent_3 = stock.tail(3)
                if len(recent_3) == 3 and not recent_3['MA_S'].isna().any():
                    is_3_day_valid = ((recent_3['High'] >= recent_3['MA_S']) & (recent_3['Low'] <= recent_3['MA_S'])).all()
                    
                    if is_3_day_valid:
                        temp_idx = len(stock) - 3
                        while temp_idx > 0:
                            prev_row = stock.iloc[temp_idx - 1]
                            if prev_row['High'] >= prev_row['MA_S'] and prev_row['Low'] <= prev_row['MA_S']:
                                temp_idx -= 1
                            else:
                                break
                        
                        box_df = stock.iloc[temp_idx:]
                        box_data = {
                            "start_date": box_df.index[0],
                            "high": float(box_df['Close'].max()),
                            "low": float(box_df['Close'].min()),
                            "days": len(box_df)
                        }

                latest_p = float(stock['Close'].dropna().iloc[-1])
                results.append({
                    "sid": sid_full, "name": name, "price": f"{latest_p:.2f}",
                    "s_ma": s_ma, "l_ma": l_ma, "sign": sign, "df": stock,
                    "box": box_data 
                })
        except Exception: continue
    return results

if "data" not in st.session_state:
    with st.spinner('圖表生成中...'):
        st.session_state["data"] = run_scan()

if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    col_t, col_b = st.columns([7, 3])
    with col_t: st.subheader("🐯 金虎南訊號")
    with col_b:
        if st.button("🔄 刷新"):
            del st.session_state["data"]
            st.rerun()

    if not data_list:
        st.write("目前無訊號")
    else:
        for item in data_list:
            df = item['df']
            total_len = len(df)
            end_dt = df.index[-1]
            
            title_text = f"{item['sid']} {item['name']} ({item['price']}) ➔ {item['sign']}"
            
            with st.expander(title_text, expanded=True):
                fig = go.Figure()
                
                # 1. K線圖 (細線)
                fig.add_trace(go.Candlestick(
                    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                    increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                    decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F',
                    line=dict(width=0.8)
                ))
                
                # 2. 短均線 (深藍細線)
                if pd.notna(item['s_ma']):
                    ma_s = df['Close'].rolling(window=int(item['s_ma'])).mean()
                    fig.add_trace(go.Scatter(x=df.index, y=ma_s, line=dict(color='#0055CC', width=1)))

                # 3. 長均線 (灰細虛線)
                if pd.notna(item['l_ma']):
                    ma_l = df['Close'].rolling(window=int(item['l_ma'])).mean()
                    fig.add_trace(go.Scatter(x=df.index, y=ma_l, line=dict(color='#888888', width=0.8, dash='dot')))

                # 4. 箱型顏色修正：淡灰色填充 + 深灰色細邊框
                if item['box']:
                    box = item['box']
                    fig.add_shape(type="rect",
                                  x0=box['start_date'], x1=end_dt,
                                  y0=box['low'], y1=box['high'],
                                  line=dict(color="#555555", width=0.8), # 深灰邊框
                                  fillcolor="#CCCCCC", opacity=0.25) # 淡灰填充

                fig.update_layout(
                    height=300, showlegend=False, 
                    template="plotly_white",
                    xaxis_rangeslider_visible=False, 
                    margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(
                        type='category',
                        range=[total_len - 42, total_len - 0.5], 
                        showticklabels=False,
                        fixedrange=True,
                        gridcolor='#F2F2F2'
                    ),
                    yaxis=dict(
                        side='right', 
                        tickfont=dict(size=10), 
                        gridcolor='#F2F2F2',
                        fixedrange=True
                    ),
                    hovermode=False
                )
                
                st.plotly_chart(fig, use_container_width=True, config={
                    'staticPlot': True, 
                    'displayModeBar': False
                })