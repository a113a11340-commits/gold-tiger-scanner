import streamlit as st
import pandas as pd
import requests

# 1. 設定試算表
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4/export?format=csv&gid=1426872214"

st.title("🐯 金虎南：轉折監控系統 (主表模式)")

# 2. 按鈕動作：強制執行讀取與顯示
if st.button("🔄 同步主表資料 / 🚀 強制刷新即時報價"):
    try:
        # 直接讀取試算表，不做任何篩選
        df = pd.read_csv(SHEET_CSV_URL)
        
        # 簡單處理：將代號轉為字串
        df.iloc[:, 0] = df.iloc[:, 0].astype(str)
        
        # 直接顯示試算表內容，確認資料來源沒問題
        st.write("目前成功抓取到的試算表資料：")
        st.dataframe(df, use_container_width=True)
        
    except Exception as e:
        st.error(f"讀取失敗，請檢查網路或連結：{e}")

# 備註：這個版本只做「讀取與顯示」。
# 如果這能顯示表格，我們再下一步把「計算訊號」的部分加回去。