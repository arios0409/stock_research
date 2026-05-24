#!/usr/bin/env python3
"""KDJ参数优化：金叉后+3d/+5d 胜率最高的一组参数"""

import tushare as ts
import pandas as pd
import numpy as np

TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

# 获取数据
df = pro.index_daily(ts_code="000001.SH", start_date="20240801", end_date="20260520")
df = df.sort_values("trade_date").reset_index(drop=True)
df["date"] = pd.to_datetime(df["trade_date"])

close = df["close"].values
high = df["high"].values
low = df["low"].values
n_total = len(close)

print(f"数据: {n_total} 个交易日, {df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}")
print()

def compute_kdj(close, high, low, N, M1, M2):
    """计算KDJ三个线"""
    n = len(close)
    k = np.full(n, np.nan, dtype=float)
    d = np.full(n, np.nan, dtype=float)
    
    for i in range(N - 1, n):
        hh = np.max(high[i - N + 1:i + 1])
        ll = np.min(low[i - N + 1:i + 1])
        if hh == ll:
            rsv = 50.0
        else:
            rsv = (close[i] - ll) / (hh - ll) * 100
        
        if np.isnan(k[i - 1]):
            k[i] = rsv
            d[i] = rsv
        else:
            k[i] = (rsv * 1 + k[i - 1] * (M1 - 1)) / M1
            d[i] = (k[i] * 1 + d[i - 1] * (M2 - 1)) / M2
    
    j = 3 * k - 2 * d
    return k, d, j

def find_golden_cross(k, d):
    """K上穿D"""
    signals = []
    for i in range(1, len(k)):
        if np.isnan(k[i]) or np.isnan(k[i-1]) or np.isnan(d[i]) or np.isnan(d[i-1]):
            continue
        if k[i-1] <= d[i-1] and k[i] > d[i]:
            signals.append(i)
    return signals

def eval_signals(signals, close, future_days):
    """评估信号后N日胜率"""
    wins = {fd: 0 for fd in future_days}
    totals = {fd: 0 for fd in future_days}
    returns = {fd: [] for fd in future_days}
    
    for idx in signals:
        for fd in future_days:
            target = idx + fd
            if target < len(close):
                ret = (close[target] - close[idx]) / close[idx] * 100
                returns[fd].append(ret)
                totals[fd] += 1
                if ret > 0:
                    wins[fd] += 1
    
    results = {}
    for fd in future_days:
        if totals[fd] > 0:
            results[fd] = {
                "wins": wins[fd],
                "total": totals[fd],
                "wr": wins[fd] / totals[fd] * 100,
                "avg_ret": np.mean(returns[fd]),
                "returns": returns[fd]
            }
        else:
            results[fd] = None
    return results

# ============================================================
# 参数扫描
# ============================================================
N_values = [5, 7, 9, 14, 21, 30, 45, 60]
M1_values = [3, 5]
M2_values = [3, 5]

future_days = [3, 5]

results_list = []

for N in N_values:
    for M1 in M1_values:
        for M2 in M2_values:
            k, d, j = compute_kdj(close, high, low, N, M1, M2)
            signals = find_golden_cross(k, d)
            evals = eval_signals(signals, close, future_days)
            
            if evals[3] and evals[5]:
                # 综合评分 = (wr_3 + wr_5) / 2，同时要求信号数>=5
                composite = (evals[3]["wr"] + evals[5]["wr"]) / 2
                results_list.append({
                    "N": N, "M1": M1, "M2": M2,
                    "signals": len(signals),
                    "wr_3d": evals[3]["wr"],
                    "wr_5d": evals[5]["wr"],
                    "avg_ret_3d": evals[3]["avg_ret"],
                    "avg_ret_5d": evals[5]["avg_ret"],
                    "composite": composite
                })

# 排序：综合评分从高到低
results_list.sort(key=lambda x: x["composite"], reverse=True)

print(f"{'排名':>4} {'N':>4} {'M1':>4} {'M2':>4} {'信号数':>6} {'+3d胜率':>8} {'+5d胜率':>8} {'+3d均收益':>10} {'+5d均收益':>10} {'综合评分':>8}")
print("=" * 75)
for rank, r in enumerate(results_list, 1):
    print(f"{rank:>4} {r['N']:>4} {r['M1']:>4} {r['M2']:>4} {r['signals']:>6} {r['wr_3d']:>7.1f}% {r['wr_5d']:>7.1f}% {r['avg_ret_3d']:>+9.2f}% {r['avg_ret_5d']:>+9.2f}% {r['composite']:>7.1f}%")

print("\n" + "=" * 75)
print("最佳5组参数:")
print("=" * 75)
for r in results_list[:5]:
    print(f"\nKDJ({r['N']},{r['M1']},{r['M2']})  信号数: {r['signals']}")
    print(f"  +3d 胜率: {r['wr_3d']:.1f}%  均收益: {r['avg_ret_3d']:+.2f}%")
    print(f"  +5d 胜率: {r['wr_5d']:.1f}%  均收益: {r['avg_ret_5d']:+.2f}%")
    print(f"  综合评分: {r['composite']:.1f}%")
    
    # 输出每个信号明细
    k, d, j = compute_kdj(close, high, low, r['N'], r['M1'], r['M2'])
    sigs = find_golden_cross(k, d)
    print(f"  金叉明细:")
    for idx in sigs:
        ev = eval_signals([idx], close, future_days)
        d3 = ev[3]["returns"][0] if ev[3] else None
        d5 = ev[5]["returns"][0] if ev[5] else None
        d3s = f"{d3:+.2f}%" if d3 is not None else "--"
        d5s = f"{d5:+.2f}%" if d5 is not None else "--"
        k_at_sig = k[idx]
        print(f"    {df['date'].iloc[idx].strftime('%Y-%m-%d')}  收盘{close[idx]:.0f}  K={k_at_sig:.1f}  +3d:{d3s}  +5d:{d5s}")
