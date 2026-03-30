import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

st.set_page_config(layout="wide")

# 你的網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1XpGq9Zl6O5eX-pD8O0A-f0oT9U_T0X7uO_Vp9I6Z_E/edit"

def run_scan():
    csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv'
    res = requests.get(csv_url)
    res.encoding = 'utf-8'
    df = pd.read_csv(io.StringIO(res.text))
    
    results = []
    for i, row in df.iterrows():
        try:
            sid = str(row[0]).split('.')[0].strip()
            sid_full = f"{sid}.TW" if len(sid) == 4 else sid
            stock = yf.download(sid_full, period="250d", progress=False)
            if not stock.empty:
                stock.columns = [c[0] if isinstance(c, tuple) else c for c in stock.columns]
                results.append({
                    "sid": sid_full, "name": row[1], "price": stock['Close'].iloc[-1],
                    "s_ma": int(row[2]), "l_ma": int(row[3]), 
                    "sign": row[5], "vol": row[6], "df": stock
                })
        except: continue
    st.session_state["data"] = results

# 一進去就執行
if "data" not in st.session_state:
    run_scan()

if "data" in st.session_state:
    # 原始表格顯示
    display_df = pd.DataFrame(st.session_state["data"])
    st.table(display_df[["sid", "name", "price", "sign", "vol"]])
    
    for item in st.session_state["data"]:
        if st.button(f"📊 {item['sid']} {item['name']}", key=item['sid']):
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=item['df'].index, open=item['df']['Open'], high=item['df']['High'], low=item['df']['Low'], close=item['df']['Close']))
            
            # 均線
            ma_s = item['df']['Close'].rolling(window=item['s_ma']).mean()
            ma_l = item['df']['Close'].rolling(window=item['l_ma']).mean()
            fig.add_trace(go.Scatter(x=item['df'].index, y=ma_s, name='短', line=dict(color='SpringGreen', width=1)))
            fig.add_trace(go.Scatter(x=item['df'].index, y=ma_l, name='長', line=dict(color='Magenta', width=1)))
            
            fig.update_layout(
                height=150, # 高度 150
                xaxis_rangeslider_visible=False,
                # 排除假日
                xaxis=dict(rangebreaks=[dict(bounds=["sat", "mon"])]),
                yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.3)', side='right'),
                template="plotly_dark",
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig, use_container_width=True)