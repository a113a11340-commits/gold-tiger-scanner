import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-區間監控版")

# 你的試算表網址與三個分頁 GID
MY_SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
SHEET_GIDS = ["0", "534437042", "1241939414"] 

def run_scan():
    all_sids_info = []
    sids_to_download = set()

    # 修正網址邏輯：強制切除 /edit 之後的參數，確保使用乾淨的 /export
    clean_base = MY_SHEET_BASE.split('/edit')[0]

    for gid in SHEET_GIDS:
        csv_url = f"{clean_base}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=15)
            res.encoding = 'utf-8'
            
            # 檢查是否抓到正確 CSV (若顯示 <html 或 <!DOCTYPE 代表未發佈或權限不足)
            if res.status_code != 200 or res.text.strip().startswith("<!DOCTYPE") or res.text.strip().startswith("<html"):
                continue
            
            raw_df = pd.read_csv(io.StringIO(res.text))
            
            for i, row in raw_df.iterrows():
                # A 欄位 (代號) 檢查
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
                
                # F 欄位 (訊號) 檢查
                sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                if sign == "": continue 
                
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                
                sids_to_download.add(sid_full)
                all_sids_info.append({
                    "sid_full": sid_full,
                    "row": row,
                    "sign": sign
                })
        except Exception:
            continue

    if not sids_to_download: return []

    # --- 效能優化：一次性下載 ---
    download_list = list(sids_to_download)
    all_data = yf.download(download_list, period="120d", progress=False, group_by='ticker')

    results = []
    for item in all_sids_info:
        try:
            sid_full = item['sid_full']
            
            # 處理單檔與多檔下載的資料結構差異 (處理 MultiIndex)
            if len(download_list) > 1:
                stock = all_data[sid_full].copy()
            else:
                stock = all_data.copy()

            if isinstance(stock.columns, pd.MultiIndex):
                stock.columns = stock.columns.get_level_values(0)
            
            if stock.empty or 'Close' not in stock.columns: continue

            # 原有邏輯：計算均線
            row = item['row']
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma_p = pd.to_numeric(row.iloc[2], errors='coerce') 
            l_ma_p = pd.to_numeric(row.iloc[3], errors='coerce')
            s_ma_val = int(s_ma_p) if pd.notna(s_ma_p) else 20
            l_ma_val = int(l_ma_p) if pd.notna(l_ma_p) else 60
            
            stock['MA_S'] = stock['Close'].rolling(window=s_ma_val).mean()
            stock['MA_L'] = stock['Close'].rolling(window=l_ma_val).mean()
            
            # 原有邏輯：尋找箱型 (維持原狀，不延展)
            view_df = stock.tail(42)
            best_box = None
            idx = 0
            while idx < len(view_df) - 2:
                w = view_df.iloc[idx:idx+3]
                w_max, w_min = w['High'].max(), w['Low'].min()
                if (w_max - w_min) / w_min <= 0.03:
                    start_i = idx
                    while idx < len(view_df) - 1:
                        nr = view_df.iloc[idx+1]
                        if nr['Low'] >= w_min * 0.985 and nr['High'] <= w_max * 1.015:
                            idx += 1
                        else:
                            break
                    best_box = {'start': view_df.index[start_i], 'end': view_df.index[idx], 'top': w_max, 'bottom': w_min}
                idx += 1

            latest_p = float(stock['Close'].iloc[-1])
            results.append({
                "sid": sid_full, "name": name, "price": latest_p,
                "s_ma_p": s_ma_val, "l_ma_p": l_ma_val, "sign": item['sign'], "df": stock,
                "box": best_box 
            })
        except Exception:
            continue
    return results

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    with st.spinner('同步掃描多個分頁中...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-多分頁監控")
with col_b:
    if st.button("🔄 刷新"):
        del st.session_state["data"]
        st.rerun()

if not data_list:
    st.info("目前的分頁中，F 欄位無任何訊號標註。請檢查是否已執行『發佈到網路』。")
else:
    for item in data_list:
        df = item['df']
        total_len = len(df)
        header = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}"
        
        with st.expander(header, expanded=True):
            fig = go.Figure()
            
            # 畫灰色小框 (維持原有邏輯)
            if item['box']:
                b = item['box']
                fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                              line=dict(width=0), fillcolor="gray", opacity=0.3)

            # K線
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F',
                line=dict(width=1.2)
            ))
            
            # 短/長均線
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#0055CC', width=2.5), name="短均"))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#888888', width=1, dash='dot'), name="長均"))

            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False,
                margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[total_len - 42, total_len - 0.5], showticklabels=False, fixedrange=True),
                yaxis=dict(side='right', tickfont=dict(size=11), fixedrange=True),
                hovermode=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False})