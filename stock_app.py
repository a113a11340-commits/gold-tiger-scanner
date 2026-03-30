# -*- coding: utf-8 -*-
import streamlit as st
import yfinance as yf
import pandas as pd
import io
import requests
import plotly.graph_objects as go

# --- 1. 基礎設定 ---
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit?gid=0#gid=0" 

st.set_page_config(page_title="均線系統", layout="wide")

# --- 2. 定義功能函數 (必須放在最前面) ---

def draw_kline(df, sid, name, sP, lP):
    """繪製極簡 K 線圖：無成交量、無工具列、細線"""
    fig = go.Figure()

    # K線圖 (線條寬度 1)
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        name='K線', increasing_line_color='#FF3333', decreasing_line_color='#00AA00',
        line=dict(width=1)
    ))
    
    # 均線計算
    df_ma = df.copy()
    df_ma['MA_S'] = df_ma['Close'].rolling(window=int(sP)).mean()
    df_ma['MA_L'] = df_ma['Close'].rolling(window=int(lP)).mean()
    
    # 極細均線 (width=1)
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_S'], name=f'短均({sP})', 
                             line=dict(color='SpringGreen', width=1)))
    fig.add_trace(go.Scatter(x=df_ma.index, y=df_ma['MA_L'], name=f'長均({lP})', 
                             visible='legendonly', line=dict(color='Magenta', width=1)))
    
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="black", plot_bgcolor="black",
        font=dict(family="Microsoft JhengHei", size=12, color="white"),
        xaxis_rangeslider_visible=False, 
        height=400, 
        dragmode='pan',
        margin=dict(t=30, b=20, l=10, r=10),
        legend=dict(orientation="h", yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(0,0,0,0.5)")
    )

    # 徹底移除工具欄與互動按鈕
    config = {'displayModeBar': False, 'scrollZoom': True}
    st.plotly_chart(fig, use_container_width=True, config=config)

def run_precise_scan():
    """執行掃描邏輯"""
    try:
        csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv'
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df_sheet = pd.read_csv(io.StringIO(res.text))
        
        # 讀取 A, B, C, D, F, G 欄
        raw_rows = df_sheet.iloc[:, [0, 1, 2, 3, 5, 6]].values.tolist()
        valid_stocks = [r for r in raw_rows if pd.notnull(r[0])]
        
        final_list = [] 
        bar = st.progress(0)
        for i, item in enumerate(valid_stocks):
            try:
                sid_raw = str(item[0]).split('.')[0].strip()
                name, sP, lP = str(item[1]), int(float(item[2])), int(float(item[3]))
                sheet_signal, sheet_vol = str(item[4]), str(item[5])
                
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                df = yf.download(sid_full, period="250d", progress=False)
                if df.empty: continue
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                
                curP = df['Close'].iloc[-1]
                maS = df['Close'].rolling(window=sP).mean().iloc[-1]
                maS_y = df['Close'].rolling(window=sP).mean().iloc[-2]
                close_y = df['Close'].iloc[-2]
                
                if (close_y >= maS_y and curP < maS) or (close_y < maS_y and curP > maS):
                    final_list.append({
                        "sid": sid_full, "名稱": name, "現價": f"{curP:.2f}", 
                        "訊號": sheet_signal, "量能": sheet_vol, "df": df, "sP": sP, "lP": lP
                    })
            except: continue
            bar.progress((i + 1) / len(valid_stocks))
        st.session_state["results"] = final_list
    except Exception as e: st.error(f"❌ 讀取錯誤: {e}")

# --- 3. 介面執行 (按鈕在最上方) ---

st.title("🐯 均線系統")

# 重新掃描按鈕
if st.button("🔄 重新掃描試算表", use_container_width=True):
    run_precise_scan()

# 首次進入自動掃描
if "results" not in st.session_state:
    run_precise_scan()

# 顯示結果
if st.session_state.get("results"):
    res_df = pd.DataFrame(st.session_state["results"])
    st.table(res_df[["sid", "名稱", "現價", "訊號", "量能"]])
    
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📈 {res['sid']} {res['名稱']}", key=f"btn_{idx}", use_container_width=True):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])