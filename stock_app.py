import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io
from collections import Counter # 加入共振計算用

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南手機版-精準型態版")

# Google Sheet 網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    """穩定讀取邏輯：下載 8 個月數據"""
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
            vol = row.iloc[6] if pd.notna(row.iloc[6]) else ""

            # 下載 8 個月 (240d)
            stock = yf.download(sid_full, period="240d", progress=False)
            
            if not stock.empty:
                if isinstance(stock.columns, pd.MultiIndex):
                    stock.columns = stock.columns.get_level_values(0)
                
                # --- 小箱型偵測與定錨邏輯 ---
                ma_val = int(s_ma) if pd.notna(s_ma) else 20
                stock['MA_Detect'] = stock['Close'].rolling(window=ma_val).mean()
                
                box_info = None
                recent_3 = stock.tail(3)
                if len(recent_3) == 3 and not recent_3['MA_Detect'].isna().any():
                    is_3_day_valid = ((recent_3['High'] >= recent_3['MA_Detect']) & (recent_3['Low'] <= recent_3['MA_Detect'])).all()
                    
                    if is_3_day_valid:
                        temp_idx = len(stock) - 3
                        while temp_idx > 0:
                            prev_row = stock.iloc[temp_idx - 1]
                            if prev_row['High'] >= prev_row['MA_Detect'] and prev_row['Low'] <= prev_row['MA_Detect']:
                                temp_idx -= 1
                            else:
                                break
                        
                        box_df = stock.iloc[temp_idx:]
                        all_pts = pd.concat([box_df['Close'], box_df['High']]).round(2).tolist()
                        counts = Counter(all_pts)
                        max_f = max(counts.values())
                        res_line = max([p for p, f in counts.items() if f == max_f])
                        
                        box_info = {
                            "start_date": box_df.index[0],
                            "top": max(res_line, box_df['Close'].max()),
                            "days": len(box_df)
                        }

                latest_p = float(stock['Close'].dropna().iloc[-1])
                results.append({
                    "sid": sid_full, "name": name, "price": f"{latest_p:.2f}",
                    "s_ma": s_ma, "l_ma": l_ma, "sign": sign, "vol": vol, "df": stock,
                    "box": box_info 
                })
        except Exception: continue
    return results

# --- 2. 執行與快取 ---
if "data" not in st.session_state:
    with st.spinner('雲端型態計算中...'):
        st.session_state["data"] = run_scan()

# --- 3. 畫面顯示 ---
if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    col_t, col_b = st.columns([7, 3])
    with col_t: st.subheader("🐯 金虎南型態訊號")
    with col_b:
        if st.button("🔄 更新"):
            del st.session_state["data"]
            st.rerun()

    if not data_list:
        st.write("目前無訊號")
    else:
        for item in data_list:
            df = item['df']
            display_df = df.iloc[-42:] 
            start_idx = display_df.index[0]
            end_idx = display_df.index[-1]
            
            p_high = float(display_df['High'].max())
            p_low = float(display_df['Low'].min())
            p_high_at = display_df['High'].idxmax()

            title_text = f"{item['sid']} {item['name']} ({item['price']}) ➔ {item['sign']}"
            
            with st.expander(title_text, expanded=True):
                # --- 圖表 1：原有的 K 線與均線 ---
                fig1 = go.Figure()
                fig1.add_trace(go.Candlestick(
                    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                    increasing_line_color='red', increasing_fillcolor='red',
                    decreasing_line_color='green', decreasing_fillcolor='green'
                ))
                if pd.notna(item['s_ma']):
                    fig1.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(window=int(item['s_ma'])).mean(), line=dict(color='SpringGreen', width=1)))
                if pd.notna(item['l_ma']):
                    fig1.add_trace(go.Scatter(x=df.index, y=df['Close'].rolling(window=int(item['l_ma'])).mean(), line=dict(color='Magenta', width=1)))

                fig1.update_layout(
                    height=160, showlegend=False, template="plotly_dark",
                    xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=5),
                    xaxis=dict(range=[start_idx, end_idx], type='category', showticklabels=False, fixedrange=True),
                    yaxis=dict(side='right', tickfont=dict(size=8), fixedrange=True)
                )
                st.plotly_chart(fig1, use_container_width=True, config={'displayModeBar': False})

                # --- 圖表 2：型態標註圖 ---
                fig2 = go.Figure()
                fig2.add_trace(go.Candlestick(
                    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                    increasing_line_color='red', increasing_fillcolor='red',
                    decreasing_line_color='green', decreasing_fillcolor='green'
                ))
                
                # 畫小箱型共振線 (紅細實線)
                if item['box']:
                    box = item['box']
                    line_start = max(start_idx, box['start_date'])
                    fig2.add_shape(type="line", x0=line_start, x1=end_idx, y0=box['top'], y1=box['top'],
                                  line=dict(color="red", width=1)) # 改為細線

                # 移除壓力線與支撐線的 add_hline
                
                # 原有的標記框保留
                fig2.add_shape(type="rect", x0=p_high_at, x1=end_idx, y0=p_high*0.995, y1=p_high*1.005,
                               line=dict(color="yellow", width=1), fillcolor="yellow", opacity=0.3)

                fig2.update_layout(
                    height=120, showlegend=False, template="plotly_dark",
                    xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=10),
                    xaxis=dict(range=[start_idx, end_idx], type='category', showticklabels=False, fixedrange=True),
                    yaxis=dict(side='right', tickfont=dict(size=8), fixedrange=True, showgrid=False)
                )
                st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})

                # --- 實戰建議 ---
                st.write(f"**實戰建議：**")
                if item['box']:
                    st.info(f"🐯 **金虎南箱型成立**：此箱型已蓄勢 {item['box']['days']} 天，共振壓力位 `{item['box']['top']:.2f}`。")
                
                if float(item['price']) >= p_high * 0.97:
                    st.warning(f"⚠️ 型態：**高檔壓力測試**。價格接近波段高點 `{p_high:.2f}`。")
                elif float(item['price']) <= p_low * 1.03:
                    st.success(f"✅ 型態：**低檔支撐尋找**。價格靠近波段低點 `{p_low:.2f}`。")
                else:
                    st.info(f"盤整：目前在波段區間內震盪。")