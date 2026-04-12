import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南手機版-2個月精準框")

# Google Sheet 網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    """穩定讀取邏輯"""
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
                
                # --- 小框框偵測邏輯 (僅限短均線 s_ma) ---
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

# --- 2. 執行與快取 ---
if "data" not in st.session_state:
    with st.spinner('計算型態中...'):
        st.session_state["data"] = run_scan()

# --- 3. 畫面顯示 ---
if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    col_t, col_b = st.columns([7, 3])
    with col_t: st.subheader("🐯 金虎南訊號")
    with col_b:
        if st.button("🔄 更新"):
            del st.session_state["data"]
            st.rerun()

    if not data_list:
        st.write("目前無訊號")
    else:
        for item in data_list:
            df = item['df']
            # --- 關鍵修正：顯示 42 根 K 線 (2 個月) ---
            display_df = df.iloc[-42:] 
            start_idx = display_df.index[0]
            end_idx = display_df.index[-1]
            
            title_text = f"{item['sid']} {item['name']} ({item['price']}) ➔ {item['sign']}"
            
            with st.expander(title_text, expanded=True):
                fig = go.Figure()
                
                # 1. K線圖
                fig.add_trace(go.Candlestick(
                    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                    increasing_line_color='red', increasing_fillcolor='red',
                    decreasing_line_color='green', decreasing_fillcolor='green'
                ))
                
                # 2. 短均線 (黃)
                if pd.notna(item['s_ma']):
                    ma_s = df['Close'].rolling(window=int(item['s_ma'])).mean()
                    fig.add_trace(go.Scatter(x=df.index, y=ma_s, line=dict(color='yellow', width=1.5)))

                # 3. 長均線 (紫虛線)
                if pd.notna(item['l_ma']):
                    ma_l = df['Close'].rolling(window=int(item['l_ma'])).mean()
                    fig.add_trace(go.Scatter(x=df.index, y=ma_l, line=dict(color='Magenta', width=1, dash='dot')))

                # 4. 畫小框框 (亮眼青藍色 Cyan)
                if item['box']:
                    box = item['box']
                    box_start = max(start_idx, box['start_date'])
                    fig.add_shape(type="rect",
                                  x0=box_start, x1=end_idx,
                                  y0=box['low'], y1=box['high'],
                                  line=dict(color="Cyan", width=2),
                                  fillcolor="Cyan", opacity=0.3)

                fig.update_layout(
                    height=220, showlegend=False, template="plotly_dark",
                    xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=10, b=5),
                    # --- X 軸設定：隱藏日期標籤 ---
                    xaxis=dict(range=[start_idx, end_idx], type='category', showticklabels=False),
                    yaxis=dict(side='right', tickfont=dict(size=9))
                )
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

                if item['box']:
                    st.caption(f"💎 小箱型：區間持續 {item['box']['days']} 天")