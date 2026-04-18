import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-全功能訊號監控")

MY_SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
SHEET_GIDS = ["0", "534437042", "1241939414"] 

def get_dynamic_levels(df_slice):
    """ 動態計算箱型上下限：紅K收盤頂 & 綠K收盤底 """
    red_candles = df_slice[df_slice['Close'] >= df_slice['Open']]
    green_candles = df_slice[df_slice['Close'] < df_slice['Open']]
    
    # 頂部優先以紅K收盤，底部優先以綠K收盤
    top = red_candles['Close'].max() if not red_candles.empty else df_slice['High'].max()
    bottom = green_candles['Close'].min() if not green_candles.empty else df_slice['Low'].min()
    
    # 共振校準 (3次觸碰)
    all_prices = pd.concat([df_slice['High'], df_slice['Low'], df_slice['Close']])
    counts = all_prices.value_counts()
    for price, count in counts.items():
        if count >= 3:
            if price > top: top = price
            if price < bottom: bottom = price
    return float(top), float(bottom)

def run_scan():
    all_sids_info = [] 
    sids_to_download = set() 
    clean_base = MY_SHEET_BASE.split('/edit')[0]

    for gid in SHEET_GIDS:
        csv_url = f"{clean_base}/export?format=csv&gid={gid}"
        try:
            res = requests.get(csv_url, timeout=15)
            res.encoding = 'utf-8'
            if res.status_code != 200: continue
            raw_df = pd.read_csv(io.StringIO(res.text))
            for i, row in raw_df.iterrows():
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "": continue 
                
                # 這裡保留試算表原本的所有訊號文字
                raw_sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                if raw_sign == "": continue 
                
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                sids_to_download.add(sid_full)
                
                # 讀取均線設定 (C欄與D欄)
                s_ma_param = pd.to_numeric(row.iloc[2], errors='coerce')
                l_ma_param = pd.to_numeric(row.iloc[3], errors='coerce')

                all_sids_info.append({
                    "sid_full": sid_full, 
                    "name": row.iloc[1],
                    "raw_sign": raw_sign, # 存儲原始訊號文字
                    "s_ma_val": s_ma_param if pd.notna(s_ma_param) else None,
                    "l_ma_val": l_ma_param if pd.notna(l_ma_param) else None
                })
        except Exception: continue

    if not sids_to_download: return []

    # 擴大範圍至 180d 確保長波段均線正確
    all_data = yf.download(list(sids_to_download), period="180d", progress=False, group_by='ticker')

    results = []
    for item in all_sids_info:
        try:
            sid_full = item['sid_full']
            stock = all_data[sid_full].copy() if len(sids_to_download) > 1 else all_data.copy()
            if isinstance(stock.columns, pd.MultiIndex): stock.columns = stock.columns.get_level_values(0)
            stock = stock.dropna(subset=['Close', 'High', 'Low', 'Open'])
            
            # 建立均線
            if item['s_ma_val']:
                stock['MA_S'] = stock['Close'].rolling(window=int(item['s_ma_val'])).mean()
            if item['l_ma_val']:
                stock['MA_L'] = stock['Close'].rolling(window=int(item['l_ma_val'])).mean()
            
            view_df = stock.tail(42)
            best_box = None
            compression_tag = ""
            
            # 如果有設定短均，才進行箱型掃描
            if 'MA_S' in stock.columns:
                for idx in range(len(view_df) - 3, -1, -1):
                    w_init = view_df.iloc[idx:idx+3]
                    # 連續3日觸及短均
                    if all(w_init['Low'].iloc[j] <= w_init['MA_S'].iloc[j] <= w_init['High'].iloc[j] for j in range(3)):
                        end_idx = idx + 2
                        for k in range(idx + 3, len(view_df)):
                            if view_df['Low'].iloc[k] <= view_df['MA_S'].iloc[k] <= view_df['High'].iloc[k]:
                                end_idx = k
                            else: break
                        
                        full_box_df = view_df.iloc[idx : end_idx + 1]
                        top, bottom = get_dynamic_levels(full_box_df)
                        height_pct = (top - bottom) / bottom * 100
                        
                        if height_pct <= 2.5: compression_tag = f" ⚡[極度壓縮:{height_pct:.1f}%]"
                        elif height_pct <= 4.5: compression_tag = f" 🎯[黃金壓縮:{height_pct:.1f}%]"
                        else: compression_tag = f" 📦[寬幅盤整:{height_pct:.1f}%]"
                        
                        best_box = {'start': view_df.index[idx], 'end': view_df.index[end_idx], 'top': top, 'bottom': bottom}
                        break 

            results.append({
                "sid": sid_full, "name": item['name'], "price": float(stock['Close'].iloc[-1]),
                "display_sign": item['raw_sign'] + compression_tag, # 原始訊號 + 新標籤
                "df": stock, "box": best_box,
                "has_ma_s": 'MA_S' in stock.columns, "has_ma_l": 'MA_L' in stock.columns
            })
        except Exception: continue
    return results

# --- 介面呈現 ---
if "data" not in st.session_state:
    with st.spinner('掃描雲端訊號中...'): st.session_state["data"] = run_scan()

data_list = st.session_state.get("data", [])

col_t, col_b = st.columns([8, 2])
with col_t: st.subheader("🐯 金虎南-訊號完整顯示版")
with col_b:
    if st.button("🔄 刷新"):
        del st.session_state["data"]
        st.rerun()

for i, item in enumerate(data_list):
    df = item['df']
    with st.expander(f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['display_sign']}", expanded=True):
        fig = go.Figure()
        if item['box']:
            b = item['box']
            fig.add_shape(type="rect", x0=b['start'], x1=df.index[-1], y0=b['bottom'], y1=b['top'],
                          line=dict(width=0), fillcolor="gray", opacity=0.3)

        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            increasing_line_color='#8B0000', increasing_fillcolor='#8B0000', 
            decreasing_line_color='#004400', decreasing_fillcolor='#004400', name="K線"
        ))
        
        if item['has_ma_s']:
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#0044BB', width=2), name="短均"))
        if item['has_ma_l']:
            fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#777777', width=1.5, dash='dot'), 
                                     name="長均", connectgaps=True))

        fig.update_layout(
            height=380, showlegend=False, template="plotly_white", xaxis_rangeslider_visible=False,
            margin=dict(l=5, r=5, t=5, b=5), xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
            yaxis=dict(side='right', fixedrange=True)
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}, key=f"v_full_{item['sid']}_{i}")