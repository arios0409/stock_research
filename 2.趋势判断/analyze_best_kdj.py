#!/usr/bin/env python3
"""深度分析最优KDJ参数的死叉效果 + 最终推荐"""

import tushare as ts
import pandas as pd
import numpy as np

TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

df = pro.index_daily(ts_code="000001.SH", start_date="20240801", end_date="20260520")
df = df.sort_values("trade_date").reset_index(drop=True)
df["date"] = pd.to_datetime(df["trade_date"])

close = df["close"].values
high = df["high"].values
low = df["low"].values

def compute_kdj(close, high, low, N, M1, M2):
    n = len(close)
    k = np.full(n, np.nan, dtype=float)
    d = np.full(n, np.nan, dtype=float)
    for i in range(N - 1, n):
        hh = np.max(high[i - N + 1:i + 1])
        ll = np.min(low[i - N + 1:i + 1])
        rsv = 50.0 if hh == ll else (close[i] - ll) / (hh - ll) * 100
        if np.isnan(k[i - 1]):
            k[i] = rsv
            d[i] = rsv
        else:
            k[i] = (rsv * 1 + k[i - 1] * (M1 - 1)) / M1
            d[i] = (k[i] * 1 + d[i - 1] * (M2 - 1)) / M2
    j = 3 * k - 2 * d
    return k, d, j

def find_cross(k, d, direction="up"):
    signals = []
    for i in range(1, len(k)):
        if np.isnan(k[i]) or np.isnan(k[i-1]) or np.isnan(d[i]) or np.isnan(d[i-1]):
            continue
        if direction == "up" and k[i-1] <= d[i-1] and k[i] > d[i]:
            signals.append(i)
        elif direction == "down" and k[i-1] >= d[i-1] and k[i] < d[i]:
            signals.append(i)
    return signals

def eval_signal(idx, close, fd):
    target = idx + fd
    if target < len(close):
        return (close[target] - close[idx]) / close[idx] * 100
    return None

# ============================================================
# 对比：KDJ(60,5,5) vs KDJ(14,5,5) vs KDJ(14,5,3) vs KDJ(5,5,5)
# ============================================================
candidates = [(60, 5, 5), (14, 5, 5), (14, 5, 3), (5, 5, 5)]

for N, M1, M2 in candidates:
    k, d, j = compute_kdj(close, high, low, N, M1, M2)
    golden = find_cross(k, d, "up")
    death = find_cross(k, d, "down")
    
    print(f"\n{'='*80}")
    print(f"KDJ({N},{M1},{M2})  金叉: {len(golden)}次  死叉: {len(death)}次")
    print(f"{'='*80}")
    
    # 金叉 +3d/+5d
    g_w3, g_w5, g_t3, g_t5 = 0, 0, 0, 0
    g_r3, g_r5 = [], []
    for idx in golden:
        r3 = eval_signal(idx, close, 3)
        r5 = eval_signal(idx, close, 5)
        if r3 is not None:
            g_t3 += 1
            g_r3.append(r3)
            if r3 > 0: g_w3 += 1
        if r5 is not None:
            g_t5 += 1
            g_r5.append(r5)
            if r5 > 0: g_w5 += 1
    
    print(f"  金叉 +3d: {g_w3}/{g_t3} = {g_w3/g_t3*100:.1f}%  均收益: {np.mean(g_r3):+.2f}%")
    print(f"  金叉 +5d: {g_w5}/{g_t5} = {g_w5/g_t5*100:.1f}%  均收益: {np.mean(g_r5):+.2f}%")
    
    # 死叉 +3d/+5d（下跌为赢）
    d_w3, d_w5, d_t3, d_t5 = 0, 0, 0, 0
    d_r3, d_r5 = [], []
    for idx in death:
        r3 = eval_signal(idx, close, 3)
        r5 = eval_signal(idx, close, 5)
        if r3 is not None:
            d_t3 += 1
            d_r3.append(r3)
            if r3 < 0: d_w3 += 1
        if r5 is not None:
            d_t5 += 1
            d_r5.append(r5)
            if r5 < 0: d_w5 += 1
    
    print(f"  死叉 +3d: {d_w3}/{d_t3} = {d_w3/d_t3*100:.1f}%  均收益: {np.mean(d_r3):+.2f}%")
    print(f"  死叉 +5d: {d_w5}/{d_t5} = {d_w5/d_t5*100:.1f}%  均收益: {np.mean(d_r5):+.2f}%")
    print(f"  合计信号: {len(golden) + len(death)}次")
    
    # 金叉明细（最近10个）
    print(f"\n  最近10个金叉:")
    for idx in golden[-10:]:
        r3 = eval_signal(idx, close, 3)
        r5 = eval_signal(idx, close, 5)
        r3s = f"{r3:+.2f}%" if r3 is not None else "--"
        r5s = f"{r5:+.2f}%" if r5 is not None else "--"
        print(f"    {df['date'].iloc[idx].strftime('%Y-%m-%d')}  K={k[idx]:.1f}  → +3d:{r3s}  +5d:{r5s}")
    
    # 死叉明细（最近10个）
    print(f"  最近10个死叉:")
    for idx in death[-10:]:
        r3 = eval_signal(idx, close, 3)
        r5 = eval_signal(idx, close, 5)
        r3s = f"{r3:+.2f}%" if r3 is not None else "--"
        r5s = f"{r5:+.2f}%" if r5 is not None else "--"
        print(f"    {df['date'].iloc[idx].strftime('%Y-%m-%d')}  K={k[idx]:.1f}  → +3d:{r3s}  +5d:{r5s}")
