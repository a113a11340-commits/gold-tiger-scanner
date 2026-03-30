import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 頁面基本設定 ---
st.set_page_config(layout="wide", page_title="均線監控系統")
st.markdown('<style>div.block-container{padding-top:1rem;}</style>', unsafe_allow_html=True)

# 請在此處填寫您的試算表 URL
MY_SHEET_URL = "您的試算表網址"

# --- 核心邏輯：掃描試算表與抓取資料 ---
def run_precise_scan():
    try:
        # 1. 讀取 Google 試算表 (匯出 CSV 格式)
        csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv'
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        df_sheet = pd.read_csv(io.StringIO(res.text))
        
        # 讀取必要欄位: A(代號), B(名稱), C(短均), D(長均), F(訊號), G(量能)
        raw_rows = df_sheet.iloc[:, [0, 1, 2, 3, 5, 6]].values.tolist()
        valid_stocks = [r for r in raw_rows if pd.notnull(r[0])]
        
        final_results = []
        progress_bar = st.progress(0)
        
        for i, item in enumerate(valid_stocks):
            try:
                sid_raw = str(item[0]).split('.')[0].strip()
                name = str(item[1])
                sP, lP = int(float(item[2])), int(float(item[3]))
                sheet_signal = str(item[4]) if pd.notnull(item[4]) else ""
                sheet_volume = str(item[5]) if pd.notnull(item[5]) else ""
                
                # 抓取 Yahoo Finance 資料 (預設 250 天)
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                df = yf.download(sid_full, period="250d", progress=False)
                
                if not df.empty:
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                    final_results.append({
                        "sid": sid_full, 
                        "名稱": name, 
                        "現價": f"{df['Close'].iloc[-1]:.2f}", 
                        "訊號": sheet_signal,
                        "量能": sheet_volume,
                        "df": df, 
                        "sP": sP, 
                        "lP": lP
                    })
            except: continue
            progress_bar.progress((i + 1) / len(valid_stocks))
            
        st.session_state["results"] = final_results
        st.success(f"✅ 掃描完成！共 {len(final_results)} 檔符合。")
    except Exception as e:
        st.error(f"❌ 讀取發生錯誤: {e}")

# --- 核心繪圖函數 (雙線、透明、低高度) ---
def draw_kline(df, sid, name, sP, lP):
    fig = go.Figure()

    # 極細 K 線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
        increasing_line_color='#FF3333', decreasing_line_color='#00AA00',
        line=dict(width=0.5)
    ))
    
    # 同時計算與顯示雙均線
    df_ma = df.copy()
    ma_s = df_ma['Close'].rolling(window=int(sP)).mean()
    ma_l = df_ma['Close'].rolling(window=int(lP)).mean()
    
    fig.add_trace(go.Scatter(x=df_ma.index, y=ma_s, name='短', line=dict(color='SpringGreen', width=0.5)))
    fig.add_trace(go.Scatter(x=df_ma.index, y=ma_l, name='長', line=dict(color='Magenta', width=0.5)))
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", # 背景全透明
        plot_bgcolor="rgba(0,0,0,0)", 
        height=100,                   # 極致低高度
        margin=dict(t=5, b=5, l=0, r=0),
        xaxis_rangeslider_visible=False,
        showlegend=False, 
        font=dict(size=8, color="white"),
        dragmode='pan',
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, fixedrange=True)
    )

    config = {
        'displayModeBar': True,
        'displaylogo': False,
        'modeBarButtonsToAdd': ['zoomIn2d', 'zoomOut2d'],
        'modeBarButtonsToRemove': ['toImage', 'select2d', 'lasso2d', 'pan2d', 'zoom2d', 'autoScale2d', 'resetScale2d']
    }
    
    # 確保透明背景
    st.markdown('<style>div[data-testid="stPlotlyChart"] { background-color: transparent !important; }</style>', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config=config)

# --- 介面呈現 ---
st.title("📈 均線監控系統")

if st.button("🔄 重新執行掃描", use_container_width=True):
    run_precise_scan()

if "results" in st.session_state:
    res_df = pd.DataFrame(st.session_state["results"])
    # 合併欄位，確保手機不需滑動
    res_df["訊號/量能"] = res_df["訊號"].astype(str) + " | " + res_df["量能"].astype(str)
    
    st.table(res_df[["sid", "名稱", "現價", "訊號/量能"]])
    
    for idx, res in enumerate(st.session_state["results"]):
        if st.button(f"📊 {res['sid']} {res['名稱']}", key=f"btn_{idx}", use_container_width=True):
            draw_kline(res["df"], res["sid"], res["名稱"], res["sP"], res["lP"])