#!/usr/bin/env python3
"""评估KDJ金叉死叉 vs MA10/20金叉死叉的预测效果"""

import tushare as ts
import pandas as pd
import numpy as np

TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

df = pro.index_daily(ts_code="000001.SH", start_date="20240801", end_date="20260520")
df = df.sort_values("trade_date").reset_index(drop=True)
df["date"] = pd.to_datetime(df["trade_date"])

N, M1, M2 = 14, 5, 3

# --- KDJ ---
low_n = df["low"].rolling(N).min()
high_n = df["high"].rolling(N).max()
rsv = ((df["close"] - low_n) / (high_n - low_n) * 100).clip(0, 100)

k_vals, d_vals = [], []
for i, r in enumerate(rsv):
    if pd.isna(r):
        k_vals.append(np.nan)
        d_vals.append(np.nan)
    elif i == 0 or pd.isna(k_vals[-1]):
        k_vals.append(r)
        d_vals.append(r)
    else:
        kv = (r * 1 + k_vals[-1] * (M1 - 1)) / M1
        dv = (kv * 1 + d_vals[-1] * (M2 - 1)) / M2
        k_vals.append(kv)
        d_vals.append(dv)

df["K"] = k_vals
df["D"] = d_vals
df["J"] = 3 * df["K"] - 2 * df["D"]

# --- MA ---
df["MA10"] = df["close"].rolling(10).mean()
df["MA20"] = df["close"].rolling(20).mean()

# --- 找信号 ---
def find_crossovers(series1, series2, direction="up"):
    """direction='up': series1 crosses above series2; 'down': series1 crosses below series2"""
    signals = []
    for i in range(1, len(df)):
        v1_prev = series1.iloc[i-1]
        v1_curr = series1.iloc[i]
        v2_prev = series2.iloc[i-1]
        v2_curr = series2.iloc[i]
        if pd.isna(v1_prev) or pd.isna(v1_curr) or pd.isna(v2_prev) or pd.isna(v2_curr):
            continue
        if direction == "up" and v1_prev <= v2_prev and v1_curr > v2_curr:
            signals.append(i)
        elif direction == "down" and v1_prev >= v2_prev and v1_curr < v2_curr:
            signals.append(i)
    return signals

kdj_golden = find_crossovers(df["K"], df["D"], "up")
kdj_death = find_crossovers(df["K"], df["D"], "down")
ma_golden = find_crossovers(df["MA10"], df["MA20"], "up")
ma_death = find_crossovers(df["MA10"], df["MA20"], "down")

def eval_signal(idx, df, future_days):
    """信号后N日涨跌幅"""
    close_now = df["close"].iloc[idx]
    results = {}
    for fd in future_days:
        target = idx + fd
        if target < len(df):
            ret = (df["close"].iloc[target] - close_now) / close_now * 100
            results[fd] = round(ret, 2)
        else:
            results[fd] = None
    return results

def print_signal_eval(signals, df, label, buy_signal=True, future_days=[5, 10, 20]):
    """buy_signal=True: 涨为赢; False: 跌为赢"""
    print("=" * 100)
    print(label)
    print("=" * 100)
    wins = {fd: 0 for fd in future_days}
    totals = {fd: 0 for fd in future_days}
    for idx in signals:
        r = eval_signal(idx, df, future_days)
        d = df["date"].iloc[idx].strftime("%Y-%m-%d")
        c = df["close"].iloc[idx]
        parts = [f"{d}  收盘{c:.0f}"]
        for fd in future_days:
            v = r[fd]
            if v is not None:
                parts.append(f"+{fd}d:{v:+.2f}%")
                totals[fd] += 1
                if buy_signal and v > 0:
                    wins[fd] += 1
                elif not buy_signal and v < 0:
                    wins[fd] += 1
            else:
                parts.append(f"+{fd}d:--")
        print("  ".join(parts))
    
    print(f"\n胜率汇总:")
    for fd in future_days:
        if totals[fd] > 0:
            wr = wins[fd] / totals[fd] * 100
            print(f"  +{fd}d: {wins[fd]}/{totals[fd]} = {wr:.1f}%")
    print()

print_signal_eval(kdj_golden, df, "KDJ(14,5,3) 金叉 → 买入信号评估", buy_signal=True)
print_signal_eval(kdj_death, df, "KDJ(14,5,3) 死叉 → 卖出信号评估（下跌为赢）", buy_signal=False)
print_signal_eval(ma_golden, df, "MA10/MA20 金叉 → 买入信号评估", buy_signal=True)
print_signal_eval(ma_death, df, "MA10/MA20 死叉 → 卖出信号评估（下跌为赢）", buy_signal=False)
