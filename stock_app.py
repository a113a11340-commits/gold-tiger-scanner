import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南手機版-精準型態版")

# Google Sheet 網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    """穩定讀取邏輯：下載 8 個月數據"""
    csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv&gid=0'
    try:
        res = requests.get(csv_url, timeout=10, stream=True)
        res.encoding = 'utf-8'
        if res.status_code != 200:
            return []
    except Exception:
        return []

    raw_df = pd.read_csv(io.StringIO(res.text))
    results = []

    for i, row in raw_df.iterrows():
        try:
            if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "":
                continue 
            
            sign = row.iloc[5] if pd.notna(row.iloc[5]) else ""
            if str(sign).strip() == "":
                continue 

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
                
                latest_price_raw = float(stock['Close'].dropna().iloc[-1])
                formatted_price = f"{latest_price_raw:.2f}"
                
                results.append({
                    "sid": sid_full, "name": name, "price": formatted_price,
                    "s_ma": s_ma, "l_ma": l_ma, "sign": sign, "vol": vol, "df": stock
                })
        except Exception:
            continue
    return results

# --- 2. 執行與快取 ---
if "data" not in st.session_state:
    with st.spinner('雲端計算中...'):
        st.session_state["data"] = run_scan()

# --- 3. 畫面顯示 ---
if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    col_t, col_b = st.columns([7, 3])
    with col_t:
        st.subheader("🐯 金虎南訊號")
    with col_b:
        if st.button("🔄 更新"):
            del st.session_state["data"]
            st.rerun()

    if not data_list:
        st.write("目前無偵測到訊號")
    else:
        for item in data_list:
            title_text = f"{item['sid']} {item['name']} ({item['price']}) ➔ {item['sign']}"
            
            with st.expander(title_text, expanded=True):
                # 嚴格鎖定顯示 2 個月 (約 42 個交易日)
                df = item['df']
                display_df = df.iloc[-42:] if len(df) > 42 else df
                start_dt = display_df.index[0]
                end_dt = display_df.index[-1]

                # --- 第一圖：均線 K 線 (紅漲綠跌 / 隱藏時間) ---
                fig1 = go.Figure()
                fig1.add_trace(go.Candlestick(
                    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                    increasing_line_color='red', increasing_fillcolor='red',
                    decreasing_line_color='green', decreasing_fillcolor='green'
                ))
                
                if pd.notna(item['s_ma']):
                    ma_s = df['Close'].rolling(window=int(item['s_ma'])).mean()
                    fig1.add_trace(go.Scatter(x=df.index, y=ma_s, line=dict(color='SpringGreen', width=1)))
                if pd.notna(item['l_ma']):
                    ma_l = df['Close'].rolling(window=int(item['l_ma'])).mean()
                    fig1.add_trace(go.Scatter(x=df.index, y=ma_l, line=dict(color='Magenta', width=1)))

                fig1.update_layout(
                    height=140, showlegend=False, template="plotly_dark",
                    xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=5),
                    xaxis=dict(range=[start_dt, end_dt], type='category', showticklabels=False, fixedrange=True),
                    yaxis=dict(side='right', tickfont=dict(size=8), fixedrange=True)
                )
                st.plotly_chart(fig1, use_container_width=True, config={'displayModeBar': False})

                # --- 第二圖：型態標註 (細線框、壓力、支撐) ---
                fig2 = go.Figure()
                fig2.add_trace(go.Candlestick(
                    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                    increasing_line_color='red', increasing_fillcolor='red',
                    decreasing_line_color='green', decreasing_fillcolor='green'
                ))

                # 計算關鍵位置 (壓力與支撐)
                high_p = float(display_df['High'].max())
                low_p = float(display_df['Low'].min())
                high_idx = display_df['High'].idxmax()
                
                # 畫出壓力頸線 (細紅虛線)
                fig2.add_shape(type="line", x0=start_dt, x1=end_dt, y0=high_p, y1=high_p,
                               line=dict(color="red", width=1, dash="dash"))
                # 畫出型態小框框 (黃色細框)
                fig2.add_shape(type="rect", x0=high_idx, x1=end_dt, y0=high_p*0.99, y1=high_p*1.01,
                               line=dict(color="yellow", width=1), fillcolor="yellow", opacity=0.1)

                fig2.update_layout(
                    height=100, showlegend=False, template="plotly_dark",
                    xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=5),
                    xaxis=dict(range=[start_dt, end_dt], type='category', showticklabels=False, fixedrange=True),
                    yaxis=dict(side='right', tickfont=dict(size=8), fixedrange=True, showgrid=False)
                )
                st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})

                # --- 實戰建議 ---
                # 根據價格位置動態建議
                curr_p = float(item['price'])
                pattern_type = "嘗試突破中" if curr_p >= high_p * 0.98 else "底部整理"
                
                st.info(f"""
                **分析：此圖目前處於「{pattern_type}」階段**
                * **關鍵位置**：上方紅色虛線壓力位約在 `{high_p:.2f}`。
                * **操作建議**：若 K 線帶量站穩黃框上緣，代表型態完成可進場；若在黃框處出現長上影線，則需預防「雙頂」反轉。
                * **支撐警示**：下方支撐關注 `{low_p:.2f}`，跌破則型態失效。
                """)