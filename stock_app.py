import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-靜態黑白專業版")

# 更新為你提供的試算表連結
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
            # 檢查代號是否存在
            if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
            # 讀取 F 欄位訊號
            sign = row.iloc[5] if pd.notna(row.iloc[5]) else ""
            if str(sign).strip() == "": continue 

            sid_raw = str(row.iloc[0]).split('.')[0].strip()
            sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma_param = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma_param = pd.to_numeric(row.iloc[3], errors='coerce')

            # 下載數據 (下載240天以計算長均線，但顯示120天)
            stock = yf.download(sid_full, period="240d", progress=False)
            
            if not stock.empty:
                if isinstance(stock.columns, pd.MultiIndex):
                    stock.columns = stock.columns.get_level_values(0)
                
                # 計算短均與長均
                s_ma_val = int(s_ma_param) if pd.notna(s_ma_param) else 20
                l_ma_val = int(l_ma_param) if pd.notna(l_ma_param) else 60
                stock['MA_S'] = stock['Close'].rolling(window=s_ma_val).mean()
                stock['MA_L'] = stock['Close'].rolling(window=l_ma_val).mean()
                
                # 箱型邏輯判定 (維持你提供的邏輯)
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
                    "s_ma_p": s_ma_val, "l_ma_p": l_ma_val, "sign": sign, "df": stock,
                    "box": box_data 
                })
        except Exception: continue
    return results

if "data" not in st.session_state:
    with st.spinner('掃描數據中...'):
        st.session_state["data"] = run_scan()

if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    col_t, col_b = st.columns([7, 3])
    with col_t: st.subheader("🐯 金虎南型態監控")
    with col_b:
        if st.button("🔄 刷新數據"):
            del st.session_state["data"]
            st.rerun()

    if not data_list:
        st.write("目前試算表中無符合訊號之股票")
    else:
        for item in data_list:
            df = item['df']
            total_len = len(df)
            end_dt = df.index[-1]
            
            title_text = f"{item['sid']} {item['name']} ({item['price']}) ➔ {item['sign']}"
            
            with st.expander(title_text, expanded=True):
                fig = go.Figure()
                
                # 1. K線圖 (細線專業版)
                fig.add_trace(go.Candlestick(
                    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                    increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                    decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F',
                    line=dict(width=0.8)
                ))
                
                # 2. 短均線 (深藍細線)
                fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], 
                                         line=dict(color='#0055CC', width=1.2), 
                                         name=f"{item['s_ma_p']}MA", hoverinfo='skip'))

                # 3. 長均線 (灰色虛線)
                fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], 
                                         line=dict(color='#888888', width=1, dash='dot'), 
                                         name=f"{item['l_ma_p']}MA", hoverinfo='skip'))

                # 4. 箱型顯示 (深黑色填充)
                if item['box']:
                    box = item['box']
                    fig.add_shape(type="rect",
                                  x0=box['start_date'], x1=end_dt,
                                  y0=box['low'], y1=box['high'],
                                  line=dict(color="#000000", width=0.8),
                                  fillcolor="#000000", opacity=0.2)

                fig.update_layout(
                    height=350, showlegend=False, 
                    template="plotly_white", 
                    xaxis_rangeslider_visible=False, 
                    margin=dict(l=10, r=10, t=10, b=10),
                    # --- 設定為 120 天視野 ---
                    xaxis=dict(
                        type='category',
                        range=[total_len - 60, total_len - 0.5], 
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
                
                # 徹底轉為靜態圖片模式，適合手機
                st.plotly_chart(fig, use_container_width=True, config={
                    'staticPlot': True, 
                    'displayModeBar': False
                })