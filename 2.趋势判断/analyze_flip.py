
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
dates = df["date"].values

N, M1, M2 = 14, 5, 3

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

# 找出状态快速翻转的区间（<5天就切换）
print("快速翻转区间分析（状态持续<5天就切换）：")
print("=" * 80)

prev_state = 0
state_start = 0
for i in range(N, len(close)):
    if np.isnan(k[i]) or np.isnan(d[i]):
        continue
    # 判断当前状态
    curr_state = prev_state
    is_golden = False
    is_high_death = False
    is_down_zone = False
    
    if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
        if k[i-1] <= d[i-1] and k[i] > d[i]:
            is_golden = True
    if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
        if k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= 85:
            is_high_death = True
    if k[i] < 35 and d[i] < 40:
        is_down_zone = True
    
    if is_golden: curr_state = 1
    elif is_down_zone: curr_state = 3
    elif is_high_death and prev_state == 1: curr_state = 2
    
    if curr_state != prev_state:
        if i - state_start < 5 and prev_state > 0:
            days = i - state_start
            print(f"  {pd.Timestamp(dates[state_start]).strftime('%Y-%m-%d')} → {pd.Timestamp(dates[i]).strftime('%Y-%m-%d')} ({days}天)")
            print(f"    状态: {prev_state} → {curr_state}  K从{k[state_start]:.1f}→{k[i]:.1f}  D从{d[state_start]:.1f}→{d[i]:.1f}")
        state_start = i
        prev_state = curr_state

# 提议：加3天确认期后的效果
print("\n" + "=" * 80)
print("加入3天确认期后的状态机改善效果")
print("=" * 80)
print("(信号出现后等3天再切换，防止毛刺)")
