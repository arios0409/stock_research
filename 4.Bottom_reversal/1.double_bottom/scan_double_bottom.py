#!/usr/bin/env python3
"""
HS300 Double Bottom Pattern Scanner
Scans HS300 component stocks for double bottom patterns using Tushare API.
"""

import tushare as ts
import pandas as pd
import numpy as np
import json
import time
from datetime import datetime, timedelta

TUSHARE_TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
API_SLEEP = 0.12

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

def api_call(func, **kwargs):
    """Make API call with sleep between calls."""
    time.sleep(API_SLEEP)
    return func(**kwargs)

def get_hs300_components():
    """Get HS300 component stock list."""
    print("Fetching HS300 components...")
    df = api_call(pro.index_weight, index_code='399300.SZ',
                  start_date='20250601', end_date='20260601')
    if df is None or df.empty:
        # Try alternative: get recent index constituents
        print("Trying alternative date range...")
        df = api_call(pro.index_weight, index_code='399300.SZ',
                      start_date='20250101', end_date='20260531')
    if df is None or df.empty:
        # Try getting index constituents directly
        print("Trying index constituents...")
        df = api_call(pro.index_member, index_code='399300.SZ')
    if df is None or df.empty:
        print("ERROR: Could not fetch HS300 components")
        return []
    
    # Get unique stock codes with names
    components = {}
    for _, row in df.iterrows():
        code = row.get('con_code') or row.get('ts_code')
        if code:
            name = row.get('con_name', '')
            components[code] = name
    
    stocks = list(components.items())
    print(f"Found {len(stocks)} HS300 components")
    return stocks

def get_daily_data(ts_code, start_date='20251101', end_date='20260517'):
    """Get daily K-line data for a stock."""
    try:
        df = api_call(pro.daily, ts_code=ts_code,
                      start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
            return df
    except Exception as e:
        pass
    
    # Try daily_hfq for adjusted prices
    try:
        df = api_call(pro.daily_hfq, ts_code=ts_code,
                      start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
            return df
    except Exception as e:
        pass
    
    return None

def find_local_extrema(df, lookback=8):
    """Find local minima and maxima using lookback window."""
    closes = df['close'].values
    n = len(closes)
    
    local_mins = []
    local_maxs = []
    
    for i in range(lookback, n - lookback):
        # Check if local minimum
        window_before = closes[i-lookback:i]
        window_after = closes[i+1:i+lookback+1]
        if closes[i] <= window_before.min() and closes[i] <= window_after.min():
            local_mins.append(i)
        
        # Check if local maximum
        if closes[i] >= window_before.max() and closes[i] >= window_after.max():
            local_maxs.append(i)
    
    return local_mins, local_maxs

def compute_macd(df, fast=12, slow=26, signal=9):
    """Compute MACD for the dataframe."""
    close = df['close']
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = 2 * (dif - dea)
    return dif, dea, macd_hist

def compute_rsi(df, period=14):
    """Compute RSI."""
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_avg_volume(df, window=20):
    """Compute rolling average volume."""
    return df['vol'].rolling(window=window, min_periods=1).mean()

def scan_double_bottom(df, ts_code='', stock_name=''):
    """Scan for double bottom pattern in a stock's daily data."""
    if df is None or len(df) < 50:
        return []
    
    results = []
    local_mins, local_maxs = find_local_extrema(df, lookback=8)
    
    if len(local_mins) < 2 or len(local_maxs) < 1:
        return results
    
    # MACD and RSI
    dif, dea, macd_hist = compute_macd(df)
    rsi = compute_rsi(df)
    avg_vol = compute_avg_volume(df)
    
    closes = df['close'].values
    lows = df['low'].values
    highs = df['high'].values
    volumes = df['vol'].values
    dates = df['trade_date'].values
    
    # Find all possible double bottom combinations
    for i in range(len(local_mins)):
        left_idx = local_mins[i]
        
        for j in range(i+1, len(local_mins)):
            right_idx = local_mins[j]
            
            # Rule: 15-150 candles between two lows
            span = right_idx - left_idx
            if span < 15 or span > 150:
                continue
            
            # Rule: Left bottom must be after 2025-12-01
            left_date_str = str(dates[left_idx])
            if left_date_str < '20251201':
                continue
            
            # Rule: Price similarity - two lows within 5%
            left_price = lows[left_idx]
            right_price = lows[right_idx]
            price_diff_pct = abs(left_price - right_price) / min(left_price, right_price)
            if price_diff_pct > 0.05:
                continue
            
            # Find neckline (highest high between the two bottoms)
            between_highs = highs[left_idx:right_idx+1]
            neckline_idx = left_idx + np.argmax(between_highs)
            neckline_price = highs[neckline_idx]
            
            # Rule: Neckline >= 5% above the lows
            min_bottom = min(left_price, right_price)
            neckline_pct = (neckline_price - min_bottom) / min_bottom
            if neckline_pct < 0.05:
                continue
            
            # Find breakout: close > neckline * 1.01
            breakout_idx = None
            for k in range(right_idx + 1, len(df)):
                if closes[k] > neckline_price * 1.01:
                    breakout_idx = k
                    break
            
            if breakout_idx is None:
                continue
            
            # Rule: Current price must be within 5% above neckline
            current_idx = len(df) - 1
            current_price = closes[current_idx]
            if current_price <= neckline_price * 1.01 or current_price > neckline_price * 1.05:
                continue
            
            # Target calculation
            target_price = neckline_price + (neckline_price - min_bottom)
            
            # Rule: Min space to target >= 8%
            space_to_target = (target_price - current_price) / current_price
            if space_to_target < 0.08:
                continue
            
            breakout_date_str = str(dates[breakout_idx])
            left_date_str = str(dates[left_idx])
            right_date_str = str(dates[right_idx])
            current_date_str = str(dates[current_idx])
            
            # Calculate days since breakout
            try:
                bd = datetime.strptime(breakout_date_str, '%Y%m%d')
                cd = datetime.strptime(current_date_str, '%Y%m%d')
                days_since_breakout = (cd - bd).days
            except:
                days_since_breakout = current_idx - breakout_idx
            
            # ===== SCORING =====
            score = 0
            
            # 1. Breakout freshness (0-25)
            if days_since_breakout <= 3:
                score += 25
            elif days_since_breakout <= 5:
                score += 20
            elif days_since_breakout <= 10:
                score += 15
            
            # 2. Right-bottom volume contraction (0-20)
            rb_vol = volumes[right_idx]
            rb_avg_vol = avg_vol[right_idx]
            if rb_avg_vol > 0:
                vol_ratio = rb_vol / rb_avg_vol
                if vol_ratio < 0.30:
                    score += 20
                elif vol_ratio < 0.50:
                    score += 18
                elif vol_ratio < 0.70:
                    score += 12
            
            # 3. Pattern span (0-15)
            if span >= 30:
                score += 15
            elif span >= 20:
                score += 10
            
            # 4. MACD bullish divergence (0-15)
            try:
                left_macd = float(macd_hist[left_idx])
                right_macd = float(macd_hist[right_idx])
                left_dif = float(dif[left_idx])
                right_dif = float(dif[right_idx])
                
                if right_macd > left_macd and left_dif < 0 and right_dif < 0:
                    score += 15  # Full divergence
                elif right_dif > left_dif:
                    score += 10  # Partial divergence
            except:
                pass
            
            # 5. Right bottom higher (0-10)
            if right_price > left_price * 1.01:
                score += 10
            elif abs(right_price - left_price) / left_price < 0.01:
                score += 8
            
            # 6. Amplitude range (0-10)
            amp = neckline_pct * 100
            if 10 <= amp <= 25:
                score += 10
            elif 8 <= amp < 10:
                score += 7
            
            # 7. RSI bullish divergence (0-5)
            try:
                left_rsi = float(rsi[left_idx])
                right_rsi = float(rsi[right_idx])
                if right_rsi > left_rsi:
                    score += 5
            except:
                pass
            
            upside_pct = (target_price - current_price) / current_price * 100
            
            if score >= 40:
                results.append({
                    'ts_code': ts_code,
                    'stock_name': stock_name,
                    'left_bottom_date': left_date_str,
                    'left_bottom_price': round(float(left_price), 3),
                    'right_bottom_date': right_date_str,
                    'right_bottom_price': round(float(right_price), 3),
                    'neckline_price': round(float(neckline_price), 3),
                    'breakout_date': breakout_date_str,
                    'current_price': round(float(current_price), 3),
                    'target_price': round(float(target_price), 3),
                    'upside_pct': round(upside_pct, 2),
                    'score': score,
                    'days_since_breakout': days_since_breakout,
                    'span': span,
                    'neckline_pct': round(neckline_pct * 100, 2),
                    'space_to_target_pct': round(space_to_target * 100, 2),
                    'vol_ratio': round(vol_ratio, 3) if 'vol_ratio' in dir() else None,
                })
    
    return results

def main():
    print("=" * 60)
    print("HS300 Double Bottom Pattern Scanner")
    print("=" * 60)
    
    # Step 1: Get HS300 components
    stocks = get_hs300_components()
    if not stocks:
        print("No HS300 components found. Exiting.")
        return
    
    all_results = []
    total = len(stocks)
    
    for idx, (ts_code, stock_name) in enumerate(stocks):
        if (idx + 1) % 20 == 0:
            print(f"Progress: {idx+1}/{total}")
        
        df = get_daily_data(ts_code, start_date='20251001', end_date='20260517')
        if df is None or len(df) < 50:
            continue
        
        patterns = scan_double_bottom(df, ts_code, stock_name)
        all_results.extend(patterns)
    
    print(f"\nScanned {total} stocks, found {len(all_results)} pattern matches (score >= 40)")
    
    # Deduplicate by stock code: keep highest score
    deduped = {}
    for r in all_results:
        code = r['ts_code']
        if code not in deduped or r['score'] > deduped[code]['score']:
            deduped[code] = r
    
    deduped_list = list(deduped.values())
    print(f"After deduplication: {len(deduped_list)} unique stocks")
    
    # Sort by breakout recency (primary), score (secondary)
    deduped_list.sort(key=lambda x: (x['days_since_breakout'], -x['score']))
    
    # Top 5
    top5 = deduped_list[:5]
    
    print(f"\nTop 5 Double Bottom Patterns:")
    print("=" * 80)
    for i, r in enumerate(top5, 1):
        print(f"\n#{i}: {r['ts_code']} {r['stock_name']}")
        print(f"  Left Bottom: {r['left_bottom_date']} @ {r['left_bottom_price']}")
        print(f"  Right Bottom: {r['right_bottom_date']} @ {r['right_bottom_price']}")
        print(f"  Neckline: {r['neckline_price']}")
        print(f"  Breakout: {r['breakout_date']} ({r['days_since_breakout']} days ago)")
        print(f"  Current Price: {r['current_price']}")
        print(f"  Target Price: {r['target_price']}")
        print(f"  Upside: {r['upside_pct']}%")
        print(f"  Score: {r['score']}")
    
    # Save results
    output_path = '/mnt/e/Hermes_workspace/Project/double_bottom_results.json'
    output_data = {
        'scan_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_scanned': total,
        'total_matches': len(deduped_list),
        'top5': top5
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\nResults saved to {output_path}")
    print("Done!")

if __name__ == '__main__':
    main()
