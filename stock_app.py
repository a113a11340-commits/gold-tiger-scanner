import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南手機版-半年精準版")

# Google Sheet 網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    """穩定讀取邏輯：下載 8 個月數據以確保長均線計算精準"""
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

            # 下載天數改為 8 個月 (240d)
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
    with st.spinner('數據同步中...'):
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
            title_text = f"{item['sid']} {item['name']} ({item['price']}) ➔ {item['sign']} [{item['vol']}]"
            
            with st.expander(title_text, expanded=True):
                # 設定顯示範圍為最近 2 個月
                end_dt = item['df'].index[-1]
                start_dt_show = end_dt - pd.DateOffset(months=2)

                # --- 第一張圖：原有的 K 線與均線圖 ---
                fig1 = go.Figure()
                fig1.add_trace(go.Candlestick(
                    x=item['df'].index, 
                    open=item['df']['Open'], high=item['df']['High'], 
                    low=item['df']['Low'], close=item['df']['Close'],
                    increasing_line_color='red', increasing_fillcolor='red',
                    decreasing_line_color='green', decreasing_fillcolor='green',
                    hoverinfo='none'
                ))
                
                close_prices = item['df']['Close']
                if pd.notna(item['s_ma']):
                    ma_s = close_prices.rolling(window=int(item['s_ma'])).mean()
                    fig1.add_trace(go.Scatter(x=item['df'].index, y=ma_s, line=dict(color='SpringGreen', width=1), hoverinfo='none'))
                
                if pd.notna(item['l_ma']):
                    ma_l = close_prices.rolling(window=int(item['l_ma'])).mean()
                    fig1.add_trace(go.Scatter(x=item['df'].index, y=ma_l, line=dict(color='Magenta', width=1), hoverinfo='none'))

                fig1.update_layout(
                    height=150, showlegend=False, template="plotly_dark",
                    hovermode=False, dragmode=False, xaxis_rangeslider_visible=False,
                    xaxis=dict(
                        range=[start_dt_show, end_dt], type='category', 
                        showticklabels=False, fixedrange=True
                    ),
                    yaxis=dict(side='right', tickfont=dict(size=8), fixedrange=True),
                    margin=dict(l=5, r=5, t=5, b=5),
                )
                st.plotly_chart(fig1, use_container_width=True, config={'displayModeBar': False})

                # --- 第二張圖：新增的型態偵測圖 ---
                fig2 = go.Figure()
                fig2.add_trace(go.Candlestick(
                    x=item['df'].index, 
                    open=item['df']['Open'], high=item['df']['High'], 
                    low=item['df']['Low'], close=item['df']['Close'],
                    increasing_line_color='red', increasing_fillcolor='red',
                    decreasing_line_color='green', decreasing_fillcolor='green',
                    hoverinfo='none'
                ))

                # --- 修正出錯的地方：改用切片抓取最近 60 天數據 ---
                cutoff_date = end_dt - pd.Timedelta(days=60)
                recent_data = item['df'].loc[item['df'].index >= cutoff_date]
                
                if not recent_data.empty:
                    high_val = recent_data['High'].max()
                    high_idx = recent_data['High'].idxmax()
                    
                    fig2.add_shape(
                        type="rect", x0=high_idx, x1=end_dt, y0=high_val*0.98, y1=high_val*1.02,
                        line=dict(color="Yellow", width=1), fillcolor="Yellow", opacity=0.2
                    )

                fig2.update_layout(
                    height=120, showlegend=False, template="plotly_dark",
                    hovermode=False, dragmode=False, xaxis_rangeslider_visible=False,
                    xaxis=dict(
                        range=[start_dt_show, end_dt], type='category', 
                        showticklabels=False, fixedrange=True
                    ),
                    yaxis=dict(side='right', tickfont=dict(size=8), fixedrange=True, showgrid=False),
                    margin=dict(l=5, r=5, t=5, b=20),
                )
                st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})

                # --- 實戰操作建議 ---
                st.markdown("""
                **🐯 金虎南型態實戰操作建議**
                *   **型態確認**：觀察下方偵測圖。若黃框出現在高檔且 K 線無法突破框頂，可能形成「雙頂」或「頭肩頂」，多單應警戒。
                *   **進場策略**：若出現「上升三角形」或「旗形整理」，應等價格明確站上框框上緣壓力位後再行介入。
                *   **止損關鍵**：所有交易應以框框下緣作為參考，一旦收盤跌破框位，代表型態失敗，應果斷執行停損。
                """)