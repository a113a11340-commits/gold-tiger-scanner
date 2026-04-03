import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南選股掃描器")

# 你的 Google Sheet 網址
MY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1jpJTJdrFSVcZowBnkgRwf55sumE_LS4q_eQk8YOpA24/edit"

def run_scan():
    """讀取試算表並處理資料"""
    csv_url = MY_SHEET_URL.split('/edit')[0] + '/export?format=csv&gid=0'
    try:
        res = requests.get(csv_url)
        res.encoding = 'utf-8'
        if res.status_code != 200:
            st.error("無法讀取試算表，請檢查權限是否設為『知道連結的任何人皆可檢視』")
            return []
    except:
        return []

    # 讀取 CSV，並強制指定欄位名稱（對應你的 GAS 結構）
    # A:sid, B:name, C:s_ma, D:l_ma, E:price, F:sign, G:vol
    raw_df = pd.read_csv(io.StringIO(res.text))
    
    results = []
    for i, row in raw_df.iterrows():
        try:
            # 根據你的試算表順序提取資料
            sid_raw = str(row.iloc[0]).split('.')[0].strip() # A欄
            if not sid_raw or sid_raw == 'nan': continue
            
            sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
            name = row.iloc[1]   # B欄
            s_ma = int(row.iloc[2]) if pd.notna(row.iloc[2]) else 5   # C欄
            l_ma = int(row.iloc[3]) if pd.notna(row.iloc[3]) else 20  # D欄
            price_from_sheet = row.iloc[4] # E欄 (GAS 算出的現價)
            sign = row.iloc[5] if pd.notna(row.iloc[5]) else ""      # F欄 (訊號)
            vol = row.iloc[6] if pd.notna(row.iloc[6]) else ""       # G欄 (量能)

            # 抓取 K 線圖需要的歷史資料
            stock = yf.download(sid_full, period="250d", progress=False)
            
            if not stock.empty:
                if isinstance(stock.columns, pd.MultiIndex):
                    stock.columns = stock.columns.get_level_values(0)
                
                results.append({
                    "sid": sid_full,
                    "name": name,
                    "price": price_from_sheet,
                    "s_ma": s_ma,
                    "l_ma": l_ma,
                    "sign": sign,
                    "vol": vol,
                    "df": stock
                })
        except:
            continue
    return results

# --- 3. 顯示介面 ---
if "data" not in st.session_state:
    with st.spinner('🐯 金虎南正在掃描盤勢...'):
        st.session_state["data"] = run_scan()

if "data" in st.session_state:
    data_list = st.session_state["data"]
    
    if not data_list:
        st.warning("查無資料，請確認試算表內容是否正確。")
    else:
        st.title("🐯 金虎南法則：API 直連版")
        
        # 顯示表格
        df_table = pd.DataFrame(data_list).drop(columns=['df', 's_ma', 'l_ma'])
        # 重新命名欄位讓表格更好看
        df_table.columns = ['代號', '名稱', '現價', '分析訊號', '量能狀態']
        st.table(df_table)
        
        st.divider()

        # 顯示圖表
        for item in data_list:
            with st.expander(f"📊 檢視 K 線分析：{item['sid']} {item['name']}", expanded=False):
                fig = go.Figure()
                # K線
                fig.add_trace(go.Candlestick(
                    x=item['df'].index, open=item['df']['Open'], 
                    high=item['df']['High'], low=item['df']['Low'], 
                    close=item['df']['Close'], name="K線"
                ))
                # 均線 (依照試算表設定的天數計算)
                ma_s = item['df']['Close'].rolling(window=item['s_ma']).mean()
                ma_l = item['df']['Close'].rolling(window=item['l_ma']).mean()
                fig.add_trace(go.Scatter(x=item['df'].index, y=ma_s, name=f'短({item["s_ma"]}MA)', line=dict(color='SpringGreen', width=1.5)))
                fig.add_trace(go.Scatter(x=item['df'].index, y=ma_l, name=f'長({item["l_ma"]}MA)', line=dict(color='Magenta', width=1.5)))
                
                fig.update_layout(
                    height=400, template="plotly_dark",
                    xaxis_rangeslider_visible=False,
                    xaxis=dict(rangebreaks=[dict(bounds=["sat", "mon"])]),
                    margin=dict(l=10, r=10, t=30, b=10)
                )
                st.plotly_chart(fig, use_container_width=True)

    if st.button("🔄 刷新數據"):
        del st.session_state["data"]
        st.rerun()