import streamlit as st
import pandas as pd
import requests

# 這是您的設定
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4/export?format=csv&gid=1426872214"

st.title("🐯 金虎南：轉折監控系統 (主表模式)")

# 監控系統的顯示區塊
if st.button("🔄 同步主表資料 / 🚀 強制刷新即時報價"):
    try:
        # 使用 requests 取得資料，以便查看是否連線成功
        response = requests.get(SHEET_CSV_URL, timeout=10)
        
        if response.status_code == 200:
            df = pd.read_csv(pd.io.common.StringIO(response.text))
            st.write("連線成功，資料如下：")
            st.dataframe(df)
            st.session_state["raw_data"] = df
        else:
            st.error(f"無法讀取試算表，錯誤代碼: {response.status_code}")
            
    except Exception as e:
        st.error(f"程式執行錯誤: {str(e)}")

# 檢查是否已成功讀取資料
if "raw_data" in st.session_state:
    st.success("資料已載入，您可以進行下一步運算。")