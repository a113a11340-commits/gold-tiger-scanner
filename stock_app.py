import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-區間監控版")

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
                
                # 儲存資訊，並帶上 gid 標記防止重複 key 問題
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
            
            # 箱型偵測邏輯（優先實體，多點則影線）
            view_df = stock.tail(42)
            best_box = None
            idx = 0
            while idx < len(view_df) - 2:
                w = view_df.iloc[idx:idx+3]
                # 取得實體的高低
                w_body_max = w[['Open', 'Close']].max(axis=1).max()
                w_body_min = w[['Open', 'Close']].min(axis=1).min()
                # 取得影線的高低
                w_shadow_max, w_shadow_min = w['High'].max(), w['Low'].min()
                
                # 判斷共振（如果影線多次觸碰邊界，改採影線）
                top = w_shadow_max if (w['High'] >= w_shadow_max * 0.998).sum() >= 2 else w_body_max
                bottom = w_shadow_min if (w['Low'] <= w_shadow_min * 1.002).sum() >= 2 else w_body_min

                if (top - bottom) / bottom <= 0.035:
                    start_i = idx
                    while idx < len(view_df) - 1:
                        nr = view_df.iloc[idx+1]
                        # 檢查下一根是否仍在區間內
                        if nr['Low'] >= bottom * 0.985 and nr['High'] <= top * 1.015:
                            idx += 1
                        else: break
                    best_box = {'start': view_df.index[start_i], 'end': view_df.index[idx], 'top': top, 'bottom': bottom}
                idx += 1

            results.append({
                "sid": sid_full, "name": name, "price": float(stock['Close'].iloc[-1]),
                "sign": sign, "df": stock, "box": best_box, "gid": gid
            })
        except Exception: continue
    return results

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    with st.spinner('讀取即時訊號中...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-訊號監控")
with col_b:
    if st.button("🔄 刷新"):
        del st.session_state["data"]
        st.rerun()

if not data_list:
    st.info("目前無訊號。")
else:
    for i, item in enumerate(data_list):
        df = item['df']
        total_len = len(df)
        header = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}"
        
        # 修正 DuplicateElementId：加上 unique key
        with st.expander(header, expanded=True):
            fig = go.Figure()
            if item['box']:
                b = item['box']
                fig.add_shape(
                    type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                    line=dict(width=0), fillcolor="gray", opacity=0.3, layer="below" 
                )

            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                increasing_line_color='#E63946', increasing_fillcolor='#E63946',
                decreasing_line_color='#2A9D8F', decreasing_fillcolor='#2A9D8F',
                line=dict(width=1.2)
            ))
            
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#0055CC', width=2.5)))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#888888', width=1, dash='dot')))

            fig.update_layout(
                height=380, showlegend=False, template="plotly_white",
                xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=5, b=5),
                xaxis=dict(type='category', range=[total_len - 42, total_len - 0.5], showticklabels=False),
                yaxis=dict(side='right', tickfont=dict(size=11)),
                hovermode=False
            )
            # 使用 enumerate 的 i 確保每個圖表 key 唯一
            st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False}, key=f"plot_{item['sid']}_{item['gid']}_{i}")