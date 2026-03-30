import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 基礎設定 (維持不變) ---
st.set_page_config(layout="wide", page_title="均線監控系統")
st.markdown('<style>div.block-container{padding-top:1rem;}</style>', unsafe_allow_html=True)

# 試算表網址 (維持不變)
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit?gid=0#gid=0"

# --- 2. 核心掃描邏輯 (維持不變) ---
def run_precise_scan():
    try:
        csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv'
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df_sheet = pd.read_csv(io.StringIO(res.text))
        
        raw_rows = df_sheet.iloc[:, [0, 1, 2, 3, 5, 6]].values.tolist()
        
        valid_stocks = []
        for r in raw_rows:
            sid_val = str(r[0]).strip() if pd.notnull(r[0]) else ""
            signal_val = str(r[4]).strip() if pd.notnull(r[4]) else ""
            if sid_val != "" and signal_val != "":
                valid_stocks.append(r)
        
        final_results = []
        if not valid_stocks:
            st.session_state["results"] = []
            return

        p_bar = st.progress(0)
        for i, item in enumerate(valid_stocks):
            try:
                sid_raw = str(item[0]).split('.')[0].strip()
                name = str(item[1])
                s_p, l_p = int(float(item[2])), int(float(item[3]))
                sign, vol = str(item[4]), str(item[5]) if pd.notnull(item[5]) else ""
                
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                df = yf.download(sid_full, period="250d", progress=False)
                
                if not df.empty:
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                    final_results.append({
                        "sid": sid_full, "名稱": name, "現價": f"{df['Close'].iloc[-1]:.2f}", 
                        "訊號": sign, "量能": vol, "df": df, "sP": s_p, "lP": l_p
                    })
            except: continue
            p_bar.progress((i + 1) / len(valid_stocks))
            
        st.session_state["results"] = final_results
        st.session_state["first_run"] = True
    except Exception as e:
        st.error(f"讀取錯誤: {e}")

if "first_run" not in st.session_state:
    run_precise_scan()

# --- 3. 繪圖函數 (只改高度為 150，線條維持 0.5) ---
def draw_kline(df, sid, name, sP, lP):
    fig = go.Figure()
    
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        increasing_line_color='#FF3333', decreasing_line_color='#00AA00', line=dict(width=0.5)
    ))
    
    ma_s = df['Close'].rolling(window=int(sP)).mean()
    ma_l = df['Close'].rolling(window=int(lP)).mean()
    # 線條粗度改回原本的 0.5
    fig.add_trace(go.Scatter(x=df.index, y=ma_s, name='短', line=dict(color='SpringGreen', width=0.5)))
    fig.add_trace(go.Scatter(x=df.index, y=ma_l, name='長', line=dict(color='Magenta', width=0.5)))
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=150, # 僅修改此項
        margin=dict(t=5, b=5, l=0, r=0), 
        xaxis_rangeslider_visible=False, showlegend=False, 
        font=dict(size=8, color="white"), dragmode='pan',
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, fixedrange=True)
    )
    
    st.markdown('<style>div[data-testid="stPlotlyChart"] { background-color: transparent !important; }</style>', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

# --- 4. UI 呈現 (維持不變) ---
st.title("📈 均線監控系統")

if st.button("🔄 手動更新數據", use_container_width=True):
    run_precise_scan()

if "results" in st.session_state and st.session_state["results"]:
    res_df = pd.DataFrame(st.session_state["results"])
    res_df["訊號/量能"] = res_df["訊號"].astype(str) + " | " + res_df["量能"].astype(str)
    st.table(res_df[["sid", "名稱", "現價", "訊號/量能"]])
    
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📊 {res['sid']} {res['名稱']}", key=f"btn_{idx}", use_container_width=True):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])