import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-精確區間版")

SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
GIDS = ["0", "1241939414", "534437042"]

def run_scan():
    all_targets = []
    
    # 步驟 1: 掃描試算表
    for gid in GIDS:
        csv_url = f"{SHEET_BASE}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code != 200: continue
            raw_df = pd.read_csv(io.StringIO(res.text))
            
            for _, row in raw_df.iterrows():
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue
                sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                if sign == "": continue 
                
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                
                all_targets.append({
                    "sid": sid_full,
                    "name": row.iloc[1] if pd.notna(row.iloc[1]) else "未命名",
                    "s_ma_p": pd.to_numeric(row.iloc[2], errors='coerce'),
                    "l_ma_p": pd.to_numeric(row.iloc[3], errors='coerce'),
                    "sign": sign
                })
        except Exception: continue

    if not all_targets: return []

    # 步驟 2: 批次下載
    tickers = list(set([t['sid'] for t in all_targets]))
    full_data = yf.download(tickers, period="120d", progress=False, group_by='ticker')

    results = []
    for item in all_targets:
        try:
            sid = item['sid']
            stock = full_data[sid].copy() if len(tickers) > 1 else full_data.copy()
            stock.dropna(subset=['Close'], inplace=True)
            
            if not stock.empty:
                s_val = int(item['s_ma_p']) if pd.notna(item['s_ma_p']) else 20
                l_val = int(item['l_ma_p']) if pd.notna(item['l_ma_p']) else 60
                stock['MA_S'] = stock['Close'].rolling(window=s_val).mean()
                stock['MA_L'] = stock['Close'].rolling(window=l_val).mean()
                
                # --- 箱型演算法修正：脫離即停止 ---
                view_df = stock.tail(42)
                best_box = None
                idx = 0
                while idx < len(view_df) - 2:
                    w = view_df.iloc[idx:idx+3]
                    w_max, w_min = w['High'].max(), w['Low'].min()
                    
                    if (w_max - w_min) / w_min <= 0.03:
                        start_i = idx
                        # 檢查點：一旦價格超出範圍，就鎖定 end 位置並跳出
                        current_idx = idx + 1
                        while current_idx < len(view_df):
                            nr = view_df.iloc[current_idx]
                            # 只要有一根 K 棒脫離 1.5% 寬容區，箱型就截止於前一根
                            if nr['Low'] < w_min * 0.985 or nr['High'] > w_max * 1.015:
                                break
                            current_idx += 1
                        
                        box_end_idx = current_idx - 1
                        # 紀錄箱型（僅當區間長度大於等於 3 天時）
                        best_box = {
                            'start': view_df.index[start_i], 
                            'end': view_df.index[box_end_idx], 
                            'top': w_max, 
                            'bottom': w_min
                        }
                        idx = current_idx # 跳過已偵測完的區間
                    else:
                        idx += 1

                item.update({"price": float(stock['Close'].iloc[-1]), "df": stock, "box": best_box})
                results.append(item)
        except Exception: continue
    return results

# --- 2. 呈現介面 ---
if "data" not in st.session_state:
    with st.spinner('掃描分頁中...'):
        st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-訊號監控")
with col_b:
    if st.button("🔄 刷新"):
        del st.session_state["data"]
        st.rerun()

if not data_list:
    st.info("目前無監控訊號。")
else:
    for i, item in enumerate(data_list):
        df = item['df']
        t_len = len(df)
        header = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['sign']}"
        
        with st.expander(header, expanded=True):
            fig = go.Figure()
            if item['box']:
                b = item['box']
                fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                             line=dict(width=0), fillcolor="gray", opacity=0.3)

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
                xaxis=dict(type='category', range=[t_len - 42, t_len - 0.5], showticklabels=False, fixedrange=True),
                yaxis=dict(side='right', tickfont=dict(size=11), fixedrange=True),
                hovermode=False
            )
            # 使用 key 防止 ID 重複報錯
            st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False}, key=f"chart_{item['sid']}_{i}")