import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io
import datetime # 用於計算日期範圍

# --- 1. 網頁基本設定 (維持原樣，確保穩定性) ---
st.set_page_config(layout="wide", page_title="金虎南訊號精選")

# 你的 Google Sheet 網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    """讀取試算表，嚴格執行沒訊號不顯示，並加入防死機保護 (結構維持原樣，不做優化)"""
    csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv&gid=0'
    try:
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        if res.status_code != 200:
            st.error("連線 Google Sheet 失敗，請檢查共用權限。")
            return []
    except Exception as e:
        st.error(f"網路連線異常: {e}")
        return []

    raw_df = pd.read_csv(io.StringIO(res.text))
    results = []

    for i, row in raw_df.iterrows():
        try:
            # --- 【保險機制】：檢查代號是否為空 ---
            if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "":
                continue 
            
            # --- 【過濾邏輯】：檢查 F 欄訊號 ---
            sign = row.iloc[5] if pd.notna(row.iloc[5]) else ""
            if str(sign).strip() == "":
                continue 

            # 處理股票代號格式
            sid_raw = str(row.iloc[0]).split('.')[0].strip()
            sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
            
            # 讀取其他欄位資訊
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            
            # 均線處理：空白則為 NaN (結構維持原樣)
            s_ma = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma = pd.to_numeric(row.iloc[3], errors='coerce')
            
            # 【關鍵修改】：抓取 G 欄量能狀態，準備加入 expander 標題
            # Key Change: Read G-column (vol)
            vol = row.iloc[6] if pd.notna(row.iloc[6]) else ""

            # 只有通過『訊號過濾』的股票，才去下載 Yahoo Finance 資料 (維持原樣)
            stock = yf.download(sid_full, period="250d", progress=False)
            
            if not stock.empty:
                # 處理 yfinance 多層索引
                if isinstance(stock.columns, pd.MultiIndex):
                    stock.columns = stock.columns.get_level_values(0)
                
                # 【關鍵修改】：確保現價是兩位小數的文字
                # Key Change: Ensure price is formatted to two decimal places
                latest_price_raw = float(stock['Close'].dropna().iloc[-1])
                formatted_price = f"{latest_price_raw:.2f}"
                
                results.append({
                    "sid": sid_full,
                    "name": name,
                    "price": formatted_price, # 使用格式化後的文字現價
                    "s_ma": s_ma,
                    "l_ma": l_ma,
                    "sign": sign,
                    "vol": vol, # 量能
                    "df": stock
                })
        except Exception:
            continue
            
    return results

# --- 2. 資料快取機制 (維持原樣) ---
if "data" not in st.session_state:
    with st.spinner('🔍 正在掃描盤勢...'):
        st.session_state["data"] = run_scan()

# --- 3. 顯示介面邏輯 (進行功能性修改) ---
if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    # 功能按鈕
    col_title, col_btn = st.columns([8, 1])
    with col_title:
        st.title("🐯 金虎南：訊號精選模式")
    with col_btn:
        if st.button("🔄 重新整理"):
            del st.session_state["data"]
            st.rerun()

    # 如果清單為空
    if not data_list:
        st.info("💡 目前清單中沒有偵測到任何訊號。")
    else:
        # 顯示統計表格 (現價已格式化)
        st.subheader(f"✅ 今日偵測到 {len(data_list)} 檔強勢訊號")
        df_display = pd.DataFrame(data_list).drop(columns=['df', 's_ma', 'l_ma'])
        df_display.columns = ['代號', '名稱', '現價', '分析訊號', '量能狀態']
        st.table(df_display)
        
        st.divider()

        # 逐一顯示詳細 K 線圖 (進行圖表修改)
        for item in data_list:
            # 【關鍵修改】：修改 Expander 標題，加入量能欄位 G 欄內容
            # Key Change: Add G-column vol to expander title
            expander_title = f"📈 {item['sid']} {item['name']} ➔ 訊號：{item['sign']} 量能：{item['vol']}"
            with st.expander(expander_title, expanded=False):
                fig = go.Figure()
                
                # 繪製 K 線
                fig.add_trace(go.Candlestick(
                    x=item['df'].index, 
                    open=item['df']['Open'], high=item['df']['High'], 
                    low=item['df']['Low'], close=item['df']['Close'], 
                    name="K線"
                ))
                
                # 只有試算表有填寫數字，才畫出對應均線 (維持原樣)
                close_prices = item['df']['Close']
                if pd.notna(item['s_ma']):
                    ma_s = close_prices.rolling(window=int(item['s_ma'])).mean()
                    fig.add_trace(go.Scatter(x=item['df'].index, y=ma_s, name=f'短({int(item["s_ma"])}MA)', line=dict(color='SpringGreen', width=1.5)))
                
                if pd.notna(item['l_ma']):
                    ma_l = close_prices.rolling(window=int(item['l_ma'])).mean()
                    fig.add_trace(go.Scatter(x=item['df'].index, y=ma_l, name=f'長({int(item["l_ma"])}MA)', line=dict(color='Magenta', width=1.5)))
                
                # --- 【關鍵修改】：修改圖表佈局設定 ---
                # 1. 計算一個月的日期範圍 (以最後一個有效日期回溯一個月)
                latest_date = item['df'].index[-1]
                one_month_ago = latest_date - pd.DateOffset(months=1)

                fig.update_layout(
                    height=150, # 高度降為 150
                    template="plotly_dark",
                    xaxis_rangeslider_visible=False,
                    xaxis=dict(
                        range=[one_month_ago, latest_date], # 【關鍵修改】：只顯示一個月 K 線
                        rangebreaks=[dict(bounds=["sat", "mon"])],
                        tickfont=dict(size=8), # 【關鍵修改】：x 軸字體小一點
                    ),
                    yaxis=dict(
                        showgrid=True, gridcolor='rgba(128,128,128,0.2)', side='right',
                        tickfont=dict(size=8), # 【關鍵修改】：y 軸字體小一點
                    ),
                    font=dict(size=10), # 【關鍵修改】：全域字體小一點 (圖例、軸字體)
                    # 緊湊邊距，適合小高度圖表
                    margin=dict(l=10, r=10, t=10, b=10),
                    # 圖例字體也縮小
                    legend=dict(font=dict(size=8))
                )
                
                # --- 【關鍵修改】：移除工具箱 (模式列) ---
                # Key Change: Hide modebar (config={'displayModeBar': False})
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})