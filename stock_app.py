import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南訊號精選")

# 你的 Google Sheet 網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    """讀取試算表，嚴格執行『沒訊號不顯示』的邏輯"""
    csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv&gid=0'
    try:
        # 設定 10 秒逾時，防止網路塞車導致網頁死機
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'utf-8'
        if res.status_code != 200:
            st.error("連線 Google Sheet 失敗，請檢查共用權限。")
            return []
    except Exception as e:
        st.error(f"網路連線異常: {e}")
        return []

    # 讀取試算表內容
    raw_df = pd.read_csv(io.StringIO(res.text))
    results = []

    for i, row in raw_df.iterrows():
        try:
            # --- 【保險機制 1】：檢查代號是否為空 ---
            if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "":
                continue 
            
            # --- 【關鍵過濾邏輯】：檢查 F 欄（分析訊號） ---
            # 如果 F 欄是空的，直接執行 continue 跳過，不執行後續動作
            sign = row.iloc[5] if pd.notna(row.iloc[5]) else ""
            if str(sign).strip() == "":
                continue # 💡 這裡就是『沒有訊號就不顯示』的核心

            # 處理股票代號格式
            sid_raw = str(row.iloc[0]).split('.')[0].strip()
            sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
            
            # 讀取其他欄位
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            
            # 均線處理：若試算表空白則為 NaN，後續不繪圖
            s_ma = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma = pd.to_numeric(row.iloc[3], errors='coerce')
            
            price_sheet = row.iloc[4] if pd.notna(row.iloc[4]) else "-"
            vol = row.iloc[6] if pd.notna(row.iloc[6]) else ""

            # 只有通過『訊號過濾』的股票，才去下載 Yahoo Finance 歷史資料
            stock = yf.download(sid_full, period="250d", progress=False)
            
            if not stock.empty:
                # 處理 yfinance 多層索引
                if isinstance(stock.columns, pd.MultiIndex):
                    stock.columns = stock.columns.get_level_values(0)
                
                results.append({
                    "sid": sid_full,
                    "name": name,
                    "price": price_sheet,
                    "s_ma": s_ma,
                    "l_ma": l_ma,
                    "sign": sign,
                    "vol": vol,
                    "df": stock
                })
        except Exception:
            # 萬一某一行資料格式錯誤，跳過不影響整體程式
            continue
            
    return results

# --- 2. 執行與顯示介面 ---

# 使用 session_state 快取資料，避免每次點選圖表都要重新下載
if "data" not in st.session_state:
    with st.spinner('🔍 正在掃描並過濾『有訊號』的股票...'):
        st.session_state["data"] = run_scan()

if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    # 頂部標題與功能按鈕
    col_title, col_btn = st.columns([8, 1])
    with col_title:
        st.title("🐯 金虎南：訊號精選模式")
    with col_btn:
        if st.button("🔄 重新整理"):
            del st.session_state["data"]
            st.rerun()

    # 如果過濾後清單為空
    if not data_list:
        st.info("💡 目前清單中沒有偵測到任何訊號（F 欄為空白）。")
    else:
        # 1. 顯示總覽表格
        st.subheader(f"✅ 今日偵測到 {len(data_list)} 檔訊號")
        df_display = pd.DataFrame(data_list).drop(columns=['df', 's_ma', 'l_ma'])
        df_display.columns = ['代號', '名稱', '現價', '分析訊號', '量能狀態']
        st.table(df_display)
        
        st.divider()

        # 2. 顯示詳細圖表
        for item in data_list:
            # 標題直接顯示該股票的訊號文字
            with st.expander(f"📈 {item['sid']} {item['name']} ➔ 訊號：{item['sign']}", expanded=False):
                fig = go.Figure()
                
                # 繪製 K 線圖
                fig.add_trace(go.Candlestick(
                    x=item['df'].index, 
                    open=item['df']['Open'], high=item['df']['High'], 
                    low=item['df']['Low'], close=item['df']['Close'], 
                    name="K線"
                ))
                
                # 根據試算表填寫的數字畫均線，沒填就不畫
                close_prices = item['df']['Close']
                if pd.notna(item['s_ma']):
                    ma_s = close_prices.rolling(window=int(item['s_ma'])).mean()
                    fig.add_trace(go.Scatter(x=item['df'].index, y=ma_s, name=f'短({int(item["s_ma"])}MA)', line=dict(color='SpringGreen', width=1.5)))
                
                if pd.notna(item['l_ma']):
                    ma_l = close_prices.rolling(window=int(item['l_ma'])).mean()
                    fig.add_trace(go.Scatter(x=item['df'].index, y=ma_l, name=f'長({int(item["l_ma"])}MA)', line=dict(color='Magenta', width=1.5)))
                
                fig.update_layout(
                    height=500, template="plotly_dark",
                    xaxis_rangeslider_visible=False,
                    xaxis=dict(rangebreaks=[dict(bounds=["sat", "mon"])]),
                    margin=dict(l=10, r=10, t=30, b=10)
                )
                st.plotly_chart(fig, use_container_width=True)