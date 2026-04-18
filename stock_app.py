import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import io

# --- 1. 網頁基本設定 ---
st.set_page_config(layout="wide", page_title="金虎南-突破跌破預警版")

MY_SHEET_BASE = "https://docs.google.com/spreadsheets/d/1b7AQGkcqK-kWhy9rYHe8Jm813K9i6UZDygjHPYg4BZ4"
SHEET_GIDS = ["0", "534437042", "1241939414"] 

def get_dynamic_levels(df_slice):
    """ 動態計算箱型上下限：紅K收盤頂 & 綠K收盤底 """
    red_candles = df_slice[df_slice['Close'] >= df_slice['Open']]
    green_candles = df_slice[df_slice['Close'] < df_slice['Open']]
    top = red_candles['Close'].max() if not red_candles.empty else df_slice['High'].max()
    bottom = green_candles['Close'].min() if not green_candles.empty else df_slice['Low'].min()
    
    # 價格共振檢查 (3次觸碰)
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
                raw_sign = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                if raw_sign == "": continue 
                sid_raw = str(row.iloc[0]).split('.')[0].strip()
                sid_full = f"{sid_raw}.TW" if len(sid_raw) == 4 else sid_raw
                sids_to_download.add(sid_full)
                all_sids_info.append({
                    "sid_full": sid_full, "name": row.iloc[1], "raw_sign": raw_sign,
                    "s_ma_val": pd.to_numeric(row.iloc[2], errors='coerce'),
                    "l_ma_val": pd.to_numeric(row.iloc[3], errors='coerce')
                })
        except Exception: continue

    if not sids_to_download: return []
    all_data = yf.download(list(sids_to_download), period="180d", progress=False, group_by='ticker')

    results = []
    for item in all_sids_info:
        try:
            sid_full = item['sid_full']
            stock = all_data[sid_full].copy() if len(sids_to_download) > 1 else all_data.copy()
            if isinstance(stock.columns, pd.MultiIndex): stock.columns = stock.columns.get_level_values(0)
            stock = stock.dropna(subset=['Close', 'High', 'Low', 'Open'])
            
            if pd.notna(item['s_ma_val']): stock['MA_S'] = stock['Close'].rolling(window=int(item['s_ma_val'])).mean()
            if pd.notna(item['l_ma_val']): stock['MA_L'] = stock['Close'].rolling(window=int(item['l_ma_val'])).mean()
            
            view_df = stock.tail(42)
            best_box = None
            tag = ""
            
            if 'MA_S' in stock.columns:
                # 尋找最近的箱型起點
                for idx in range(len(view_df) - 3, -1, -1):
                    w_init = view_df.iloc[idx:idx+3]
                    if all(w_init['Low'].iloc[j] <= w_init['MA_S'].iloc[j] <= w_init['High'].iloc[j] for j in range(3)):
                        start_idx = idx
                        end_idx = idx + 2
                        
                        # 向後生長並檢查突破/跌破
                        for k in range(idx + 3, len(view_df)):
                            current_k = view_df.iloc[k]
                            temp_top, temp_bottom = get_dynamic_levels(view_df.iloc[start_idx : k])
                            
                            # 檢查目前 K 棒收盤是否還在箱型內
                            if current_k['Close'] > temp_top or current_k['Close'] < temp_bottom:
                                break
                            
                            # 且需滿足觸碰均線才延伸
                            if current_k['Low'] <= current_k['MA_S'] <= current_k['High']:
                                end_idx = k
                            else:
                                break
                        
                        final_box_df = view_df.iloc[start_idx : end_idx + 1]
                        top, bottom = get_dynamic_levels(final_box_df)
                        height_pct = (top - bottom) / bottom * 100
                        
                        # --- 突破/跌破 提示判斷 ---
                        latest_close = float(stock['Close'].iloc[-1])
                        if latest_close > top:
                            tag = f" 🚩[突破箱型! 頂:{top:.1f}]"
                        elif latest_close < bottom:
                            tag = f" ⚠️[跌破警告! 底:{bottom:.1f}]"
                        else:
                            # 還在箱型內，顯示壓縮狀態
                            if height_pct <= 2.5: tag = f" ⚡[極壓:{height_pct:.1f}%]"
                            elif height_pct <= 4.5: tag = f" 🎯[黃金:{height_pct:.1f}%]"
                            else: tag = f" 📦[盤整:{height_pct:.1f}%]"
                        
                        best_box = {'start': view_df.index[start_idx], 'end': view_df.index[end_idx], 'top': top, 'bottom': bottom}
                        break 

            results.append({
                "sid": sid_full, "name": item['name'], "price": float(stock['Close'].iloc[-1]),
                "display_sign": item['raw_sign'] + tag, "df": stock, "box": best_box,
                "has_ma_s": 'MA_S' in stock.columns, "has_ma_l": 'MA_L' in stock.columns
            })
        except Exception: continue
    return results

# --- UI ---
if "data" not in st.session_state:
    with st.spinner('計算箱型動態訊號中...'): st.session_state["data"] = run_scan()

for i, item in enumerate(st.session_state.get("data", [])):
    df = item['df']
    # 如果是突破或跌破，標題顏色或文字會更明顯
    header_text = f"{item['sid']} {item['name']} ({item['price']:.2f}) ➔ {item['display_sign']}"
    
    with st.expander(header_text, expanded=True):
        fig = go.Figure()
        if item['box']:
            b = item['box']
            fig.add_shape(type="rect", x0=b['start'], x1=b['end'], y0=b['bottom'], y1=b['top'],
                          line=dict(width=0), fillcolor="gray", opacity=0.3)

        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            increasing_line_color='#8B0000', increasing_fillcolor='#8B0000', 
            decreasing_line_color='#004400', decreasing_fillcolor='#004400', name="K線"
        ))
        if item['has_ma_s']: fig.add_trace(go.Scatter(x=df.index, y=df['MA_S'], line=dict(color='#0044BB', width=2)))
        if item['has_ma_l']: fig.add_trace(go.Scatter(x=df.index, y=df['MA_L'], line=dict(color='#777777', width=1.5, dash='dot'), connectgaps=True))

        fig.update_layout(height=380, showlegend=False, template="plotly_white", xaxis_rangeslider_visible=False,
                          margin=dict(l=5, r=5, t=5, b=5), xaxis=dict(type='category', range=[len(df)-42, len(df)-0.5], showticklabels=False),
                          yaxis=dict(side='right', fixedrange=True))
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}, key=f"v_alert_{item['sid']}_{i}")