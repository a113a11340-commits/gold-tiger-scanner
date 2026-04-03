import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
# 設定為寬螢幕模式，讓圖表有更多空間顯示
st.set_page_config(layout="wide", page_title="金虎南選股掃描器")

# Google Sheet 來源網址 (需確認權限為「知道連結的人均可檢視」)
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1XpGq9Zl6O5eX-pD8O0A-f0oT9U_T0X7uO_Vp9I6Z_E/edit"

# --- 2. 定義核心掃描函式 ---
def run_scan():
    """從 Google Sheet 抓取清單，並從 yfinance 下載對應的股價資料"""
    # 將編輯網址轉換為 CSV 導出格式的連結
    csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv'
    try:
        res = requests.get(csv_url)
        res.encoding = 'utf-8'
        if res.status_code != 200:
            st.error("無法連線至 Google Sheet，請確認連結是否正確或權限是否開啟。")
            return []
    except Exception as e:
        st.error(f"網路連線發生錯誤: {e}")
        return []

    # 讀取 CSV 內容
    df = pd.read_csv(io.StringIO(res.text))
    results = []
    
    # 逐行遍歷試算表內容
    for i, row in df.iterrows():
        try:
            row_vals = row.values
            # 若第一欄 (股票代號) 為空則跳過
            if pd.isna(row_vals[0]):
                continue
                
            # 格式化股票代號：去除小數點、空格，4位數代號自動補上 .TW
            sid = str(row_vals[0]).split('.')[0].strip()
            sid_full = f"{sid}.TW" if len(sid) == 4 else sid
            
            # 讀取試算表欄位，並設定預設值以防欄位缺失
            name = row_vals[1] if len(row_vals) > 1 else "未命名"
            s_ma_val = int(row_vals[2]) if len(row_vals) > 2 and pd.notna(row_vals[2]) else 5
            l_ma_val = int(row_vals[3]) if len(row_vals) > 3 and pd.notna(row_vals[3]) else 20
            sign_text = row_vals[5] if len(row_vals) > 5 else ""
            vol_text = row_vals[6] if len(row_vals) > 6 else ""

            # 使用 yfinance 下載過去 250 天的股價資料
            stock = yf.download(sid_full, period="250d", progress=False)
            
            if not stock.empty:
                # 關鍵修正：處理 yfinance 新版回傳的 MultiIndex 欄位結構
                if isinstance(stock.columns, pd.MultiIndex):
                    stock.columns = stock.columns.get_level_values(0)
                
                # 確保成功取得收盤價欄位
                if 'Close' in stock.columns:
                    latest_price = float(stock['Close'].dropna().iloc[-1])
                    
                    # 將抓取到的資料存入結果清單
                    results.append({
                        "sid": sid_full, 
                        "name": name, 
                        "price": round(latest_price, 2),
                        "s_ma": s_ma_val, 
                        "l_ma": l_ma_val, 
                        "sign": sign_text, 
                        "vol": vol_text, 
                        "df": stock # 儲存完整的 DataFrame 供後續畫圖
                    })
        except Exception:
            # 若單一股票下載失敗，跳過並繼續下一支
            continue
            
    return results

# --- 3. 資料存取與快取邏輯 ---
# 檢查 Session State 是否已有資料，避免網頁重整時重複下載 API
if "data" not in st.session_state:
    with st.spinner('🚀 正在同步 Google Sheet 並從 Yahoo Finance 下載最新報價...'):
        st.session_state["data"] = run_scan()

# --- 4. 網頁前端顯示介面 ---
if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    # 若清單為空，顯示提示訊息
    if not data_list:
        st.warning("⚠️ 目前清單中沒有有效資料。請檢查 Google Sheet 內容或網路連線。")
        if st.button("手動重新整理"):
            del st.session_state["data"]
            st.rerun()
    else:
        st.title("🐯 金虎南股票掃描器")
        
        # 顯示總覽表格 (排除掉圖表用的原始資料 df 欄位)
        st.subheader("📋 股票監控清單")
        display_df = pd.DataFrame(data_list).drop(columns=['df', 's_ma', 'l_ma'])
        st.table(display_df)
        
        st.divider() # 網頁分割線
        
        # 顯示詳細 K 線圖區塊
        st.subheader("📈 技術分析圖表")
        for item in data_list:
            # 使用 expander (摺疊面板) 節省空間，使用者點擊才顯示圖表
            with st.expander(f"🔍 點擊查看：{item['sid']} {item['name']}", expanded=False):
                fig = go.Figure()
                
                # 繪製 K 線圖 (Candlestick)
                fig.add_trace(go.Candlestick(
                    x=item['df'].index, 
                    open=item['df']['Open'], 
                    high=item['df']['High'], 
                    low=item['df']['Low'], 
                    close=item['df']['Close'],
                    name="K線"
                ))
                
                # 計算與繪製移動平均線 (MA)
                ma_short = item['df']['Close'].rolling(window=item['s_ma']).mean()
                ma_long = item['df']['Close'].rolling(window=item['l_ma']).mean()
                
                fig.add_trace(go.Scatter(x=item['df'].index, y=ma_short, 
                                         name=f'短({item["s_ma"]}MA)', 
                                         line=dict(color='SpringGreen', width=1.5)))
                
                fig.add_trace(go.Scatter(x=item['df'].index, y=ma_long, 
                                         name=f'長({item["l_ma"]}MA)', 
                                         line=dict(color='Magenta', width=1.5)))
                
                # 設定圖表樣式、深色主題、隱藏滑桿、排除假日
                fig.update_layout(
                    height=450,
                    xaxis_rangeslider_visible=False,
                    xaxis=dict(rangebreaks=[dict(bounds=["sat", "mon"])]), # 排除週六日
                    yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)', side='right'),
                    template="plotly_dark",
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    margin=dict(l=10, r=10, t=30, b=10)
                )
                
                # 渲染圖表到 Streamlit
                st.plotly_chart(fig, use_container_width=True)

        # 頁尾：手動強制刷新按鈕
        if st.button("🔄 立即刷新所有資料"):
            del st.session_state["data"]
            st.rerun()