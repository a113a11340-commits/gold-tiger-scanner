import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-動態容錯箱型版")

BASE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
GIDS = ["0", "1241939414", "534437042"]

def run_scan():
    all_temp_rows = []
    all_sids = []

    for gid in GIDS:
        csv_url = f"{BASE_SHEET_URL}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=15)
            res.encoding = 'utf-8'
            if res.status_code != 200: continue
            raw_df = pd.read_csv(io.StringIO(res.text))
            
            for i, row in raw_df.iterrows():
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
                sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                if sign == "": continue 
                
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                
                all_temp_rows.append({'sid_full': sid_full, 'row': row, 'sign': sign, 'gid': gid})
                if sid_full not in all_sids:
                    all_sids.append(sid_full)
        except Exception: continue

    if not all_sids: return []

    all_data = yf.download(all_sids, period="120d", progress=False, group_by='ticker', threads=True)
    
    results = []
    for item in all_temp_rows:
        try:
            sid_full = item['sid_full']
            row, sign, gid = item['row'], item['sign'], item['gid']
            
            stock = all_data[sid_full].copy() if len(all_sids) > 1 else all_data.copy()
            if isinstance(stock.columns, pd.MultiIndex):
                stock.columns = stock.columns.get_level_values(0)
            if stock.empty or 'Close' not in stock.columns: continue

            # 指標計算
            name = row.iloc[1] if pd.notna(row.iloc[1]) else "未命名"
            s_ma_val = int(pd.to_numeric(row.iloc[2], errors='coerce') or 20)
            l_ma_val = int(pd.to_numeric(row.iloc[3], errors='coerce') or 60)
            stock['MA_S'] = stock['Close'].rolling(window=s_ma_val).mean()
            stock['MA_L'] = stock['Close'].rolling(window=l_ma_val).mean()
            
            # --- 動態容錯箱型邏輯 ---
            view_df = stock.tail(42).copy()
            view_df['Touch'] = (view_df['Low'] <= view_df['MA_S']) & (view_df['High'] >= view_df['MA_S'])
            
            best_box = None
            idx = 0
            while idx < len(view_df) - 2:
                # 啟動：連續 3 天觸碰
                if view_df['Touch'].iloc[idx] and view_df['Touch'].iloc[idx+1] and view_df['Touch'].iloc[idx+2]:
                    start_idx = idx
                    box_high = view_df['High'].iloc[idx:idx+3].max()
                    box_low = view_df['Low'].iloc[idx:idx+3].min()
                    
                    miss_count = 0  # 紀錄沒碰到均線的天數
                    scan_i = idx + 2
                    
                    while scan_i < len(view_df) - 1:
                        next_day = view_df.iloc[scan_i + 1]
                        is_touch = next_day['Touch']
                        # 檢查是否仍在箱型範圍內 (容許 1% 誤差)
                        in_range = (next_day['Low'] >= box_low * 0.99) and (next_day['High'] <= box_high * 1.01)
                        
                        if is_touch or in_range:
                            scan_i += 1
                            # 更新箱型長大的範圍
                            box_high = max(box_high, next_day['High'])
                            box_low = min(box_low, next_day['Low'])
                            
                            # 重置沒碰到的計數
                            if is_touch:
                                miss_count = 0
                            else:
                                miss_count += 1
                                
                            # 如果連續 2 天沒碰到且也開始偏離範圍，就停止
                            if miss_count > 2:
                                break
                        else:
                            # 既沒碰到均線，也跑出箱型範圍，停止長大
                            break
                    
                    best_box = {
                        'start': view_df.index[start_idx], 
                        'end': view_df.index[scan_i], 
                        'top': box_high, 
                        'bottom': box_low
                    }
                    idx = scan_i
                idx += 1

            results.append({
                "sid": sid_full, "name": name, "price": float(stock['Close'].iloc[-1]),
                "sign": sign, "df": stock, "box": best_box, "gid": gid
            })
        except Exception: continue
    return results

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    with st.spinner('同步分析 3 分頁即時數據...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-動態容錯箱型")
with col_b:
    if st.button("🔄 刷新"):
        del st.session_state["data"]
        st.rerun()

if not data_list:
    st.info("目前無符合條件之訊號。")
else:
    for i, item in enumerate(data_list):
        df = item['df']
        total_len = len(df)
        header = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}"
        
        with st.expander(header, expanded=True):
            fig = go.Figure()
            if item['box']:
                b = item['box']
                fig.add_shape(
                    type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                    line=dict(width=1, color="rgba(100, 100, 100, 0.4)"), 
                    fillcolor="gray", opacity=0.2, layer="below" 
                )

            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F',
                line=dict(width=1.2)
            ))
            
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#0055CC', width=2.5), name="短均"))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#888888', width=1, dash='dot'), name="長均"))

            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[total_len - 42, total_len - 0.5], showticklabels=False),
                yaxis=dict(side='right', tickfont=dict(size=11)),
                hovermode=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False}, key=f"plot_{item['sid']}_{item['gid']}_{i}")