import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 基礎設定 (維持不動) ---
st.set_page_config(layout="wide", page_title="均線監控系統")
st.markdown('<style>div.block-container{padding-top:1rem;}</style>', unsafe_allow_html=True)

MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit?gid=0#gid=0"

# --- 2. 核心掃描邏輯 (維持不動) ---
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
                # 修改點 1：抓取天數維持 250 天以利計算長均線，但繪圖時只秀半年
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

# --- 3. 繪圖函數 (修改高度、網格、時間範圍) ---
def draw_kline(df, sid, name, sP, lP):
    # 修改點 1：只取最後 60 筆資料 (約3個月) 進行繪圖
    plot_df = df.tail(60) 
    
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], low=plot_df['Low'], close=plot_df['Close'], 
        increasing_line_color='#FF3333', decreasing_line_color='#00AA00', line=dict(width=0.5)
    ))
    
    # 均線計算需用原始 df (確保 250 天數據充足)，但只畫出最後 60 天
    ma_s = df['Close'].rolling(window=int(sP)).mean().tail(60)
    ma_l = df['Close'].rolling(window=int(lP)).mean().tail(60)
    
    fig.add_trace(go.Scatter(x=plot_df.index, y=ma_s, name='短', line=dict(color='SpringGreen', width=0.5)))
    fig.add_trace(go.Scatter(x=plot_df.index, y=ma_l, name='長', line=dict(color='Magenta', width=0.5)))
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", 
        plot_bgcolor="rgba(0,0,0,0)",
        height=150, # 修改點 3：圖高改為 150
        margin=dict(t=5, b=5, l=0, r=0), 
        xaxis_rangeslider_visible=False, showlegend=False, 
        font=dict(size=8, color="white"), dragmode='pan',
        # 修改點 2：加入淺灰色網格
        xaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.3)', zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.3)', zeroline=False, fixedrange=True)
    )
    
    st.markdown('<style>div[data-testid="stPlotlyChart"] { background-color: transparent !important; }</style>', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

# --- 4. UI 呈現 (維持不動) ---
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