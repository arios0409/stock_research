#!/usr/bin/env python3
"""KDJ(14,5,3) 上升金叉 + 混合策略下降(K<20&D<30) +3d胜率"""

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

N, M1, M2 = 14, 5, 3

# ========== KDJ(14,5,3) ==========
k = np.full(len(close), np.nan, dtype=float)
d = np.full(len(close), np.nan, dtype=float)
for i in range(N - 1, len(close)):
    hh = np.max(high[i - N + 1:i + 1])
    ll = np.min(low[i - N + 1:i + 1])
    rsv = 50.0 if hh == ll else (close[i] - ll) / (hh - ll) * 100
    if np.isnan(k[i - 1]):
        k[i] = rsv
        d[i] = rsv
    else:
        k[i] = (rsv * 1 + k[i - 1] * (M1 - 1)) / M1
        d[i] = (k[i] * 1 + d[i - 1] * (M2 - 1)) / M2

# ========== 1. 上升：KDJ金叉 ==========
golden_signals = []
for i in range(1, len(k)):
    if not np.isnan(k[i]) and not np.isnan(k[i-1]) and not np.isnan(d[i]) and not np.isnan(d[i-1]):
        if k[i-1] <= d[i-1] and k[i] > d[i]:
            golden_signals.append(i)

print("=" * 80)
print("策略1: KDJ(14,5,3) 金叉 → 上升趋势（买入信号）")
print("=" * 80)

g_w3, g_w5, g_t3, g_t5 = 0, 0, 0, 0
for idx in golden_signals:
    r3 = (close[idx+3] - close[idx]) / close[idx] * 100 if idx+3 < len(close) else None
    r5 = (close[idx+5] - close[idx]) / close[idx] * 100 if idx+5 < len(close) else None
    if r3 is not None:
        g_t3 += 1
        if r3 > 0: g_w3 += 1
    if r5 is not None:
        g_t5 += 1
        if r5 > 0: g_w5 += 1
    d_str = df["date"].iloc[idx].strftime("%Y-%m-%d")
    r3s = f"{r3:+.2f}%" if r3 is not None else "--"
    print(f"  {d_str}  K={k[idx]:.1f}  → +3d:{r3s}")

print(f"\n金叉胜率: +3d={g_w3}/{g_t3}={g_w3/g_t3*100:.1f}%  +5d={g_w5}/{g_t5}={g_w5/g_t5*100:.1f}%")
print(f"信号数: {len(golden_signals)}")

# ========== 2. 下降：K<20 & D<30（混合策略）==========
print("\n" + "=" * 80)
print("策略2: KDJ(14,5,3) K<20 & D<30 → 下降趋势信号")
print("=" * 80)

# 检测进入超卖区的日期
down_signals = []
in_down = False
for i in range(len(k)):
    if pd.isna(k[i]) or pd.isna(d[i]):
        continue
    if k[i] < 20 and d[i] < 30:
        if not in_down:
            down_signals.append(i)
            in_down = True
    else:
        in_down = False

# +3d评估：进入超卖区后是否继续跌
d_w3, d_w5, d_t3, d_t5 = 0, 0, 0, 0
for idx in down_signals:
    r3 = (close[idx+3] - close[idx]) / close[idx] * 100 if idx+3 < len(close) else None
    r5 = (close[idx+5] - close[idx]) / close[idx] * 100 if idx+5 < len(close) else None
    if r3 is not None:
        d_t3 += 1
        if r3 < 0: d_w3 += 1  # 继续跌为赢
    if r5 is not None:
        d_t5 += 1
        if r5 < 0: d_w5 += 1
    d_str = df["date"].iloc[idx].strftime("%Y-%m-%d")
    r3s = f"{r3:+.2f}%" if r3 is not None else "--"
    r5s = f"{r5:+.2f}%" if r5 is not None else "--"
    print(f"  {d_str}  K={k[idx]:.1f} D={d[idx]:.1f}  → +3d:{r3s}  +5d:{r5s}")

print(f"\nK<20&D<30下降信号胜率（继续跌为赢）: +3d={d_w3}/{d_t3}={d_w3/d_t3*100:.1f}%  +5d={d_w5}/{d_t5}={d_w5/d_t5*100:.1f}%")
print(f"信号数: {len(down_signals)}")

# ========== 3. 混合策略：金叉做多 + K<20&D<30做空 ==========
print("\n" + "=" * 80)
print("混合策略综合评估：")
print(f"  📈 上升: KDJ(14,5,3) 金叉 → 买入  +3d胜率 {g_w3/g_t3*100:.1f}%")
print(f"  📉 下降: KDJ(14,5,3) K<20&D<30 → 看空  +3d胜率 {d_w3/d_t3*100:.1f}%")
print("=" * 80)

# ========== 4. 额外：各K阈值扫描，找最佳下降判断阈值 ==========
print("\n" + "=" * 80)
print("下降判断阈值扫描 (K < X and D < Y) → +3d胜率")
print("=" * 80)

thresholds = []
for k_thresh in range(5, 46, 5):
    for d_thresh in range(k_thresh, min(k_thresh + 20, 46), 5):
        sigs = []
        in_down = False
        for i in range(len(k)):
            if pd.isna(k[i]) or pd.isna(d[i]):
                continue
            if k[i] < k_thresh and d[i] < d_thresh:
                if not in_down:
                    sigs.append(i)
                    in_down = True
            else:
                in_down = False
        
        if len(sigs) >= 3:
            wins = 0
            for idx in sigs:
                if idx + 3 < len(close):
                    r = (close[idx+3] - close[idx]) / close[idx] * 100
                    if r < 0: wins += 1
            wr = wins / len(sigs) * 100
            thresholds.append((wr, len(sigs), k_thresh, d_thresh, wins))

thresholds.sort(key=lambda x: x[0], reverse=True)

print(f"{'排名':>4} {'K<':>4} {'D<':>4} {'信号数':>6} {'胜+3d':>8} {'赢':>4}")
print("-" * 35)
for rank, (wr, cnt, kt, dt, wins) in enumerate(thresholds[:15], 1):
    print(f"{rank:>4} {kt:>4} {dt:>4} {cnt:>6} {wr:>7.1f}% {wins:>4}")

# ========== 5. 死叉阈值：K在什么位置下穿D最准确 ==========
print("\n" + "=" * 80)
print("死叉过滤优化：只在K值 > X 时死叉才有效（高位死叉）")
print("=" * 80)

for min_k in [50, 60, 70, 80, 85, 90]:
    death_signals = []
    for i in range(1, len(k)):
        if not np.isnan(k[i]) and not np.isnan(k[i-1]) and not np.isnan(d[i]) and not np.isnan(d[i-1]):
            if k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= min_k:
                death_signals.append(i)
    
    if len(death_signals) >= 2:
        wins = 0
        for idx in death_signals:
            r = (close[idx+3] - close[idx]) / close[idx] * 100 if idx+3 < len(close) else None
            if r is not None and r < 0: wins += 1
        wr = wins / len(death_signals) * 100 if death_signals else 0
        print(f"  高位死叉(K>={min_k}): {len(death_signals)}次  +3d下跌胜率={wr:.1f}%")
        if len(death_signals) <= 6:
            for idx in death_signals:
                r = (close[idx+3] - close[idx]) / close[idx] * 100 if idx+3 < len(close) else None
                rs = f"{r:+.2f}%" if r is not None else "--"
                print(f"    {df['date'].iloc[idx].strftime('%Y-%m-%d')}  K={k[idx]:.1f} → +3d:{rs}")
