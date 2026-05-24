#!/usr/bin/env python3
"""三状态机：上升(金叉) → 风险(高位死叉K≥85) → 下降(K<35&D<40)"""

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

# KDJ计算
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

# ========== 三状态机 ==========
# 状态: 0=初始/未定义, 1=上升, 2=风险, 3=下降

state = np.full(len(close), 0, dtype=int)
state_name = {0: "初始", 1: "上升↑", 2: "风险⚠", 3: "下降↓"}

# 状态变更记录
transitions = []  # (日期, 旧状态, 新状态, 触发条件)

for i in range(N, len(close)):
    if np.isnan(k[i]) or np.isnan(d[i]):
        continue
    
    prev_state = state[i-1]
    
    # 检测信号
    is_golden = False  # 金叉
    is_high_death = False  # 高位死叉 K≥85
    is_down_zone = False  # K<35 & D<40
    
    if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
        if k[i-1] <= d[i-1] and k[i] > d[i]:
            is_golden = True
    
    if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
        if k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= 85:
            is_high_death = True
    
    if k[i] < 35 and d[i] < 40:
        is_down_zone = True
    
    # 状态转移逻辑
    new_state = prev_state
    
    # 金叉 → 上升（最高优先级）
    if is_golden:
        new_state = 1
    # K<35&D<40 → 下降
    elif is_down_zone:
        new_state = 3
    # 高位死叉上升→风险（仅从上升进入风险）
    elif is_high_death and prev_state == 1:
        new_state = 2
    # 从初始状态：如果没有信号，保持0
    
    state[i] = new_state
    
    if new_state != prev_state and prev_state != 0:
        trigger = ""
        if is_golden: trigger = "金叉"
        elif is_down_zone: trigger = "K<35&D<40"
        elif is_high_death: trigger = "高位死叉"
        transitions.append((dates[i], prev_state, new_state, trigger))

# ========== 输出状态切换记录 ==========
print("=" * 100)
print("三状态机切换记录")
print("=" * 100)
print(f"{'日期':<14} {'从':>8} → {'到':>8} {'触发':<16} {'K值':>8} {'D值':>8}")
print("-" * 100)
for dt, p, ns, trig in transitions:
    idx = np.where(dates == dt)[0][0]
    print(f"{pd.Timestamp(dt).strftime('%Y-%m-%d'):<14} {state_name[p]:>8} → {state_name[ns]:>8} {trig:<16} {k[idx]:>7.1f} {d[idx]:>7.1f}")

# ========== 评估每个状态的后续表现 ==========
print("\n" + "=" * 100)
print("各状态进入后的表现评估")
print("=" * 100)

for s, s_label in [(1, "上升↑"), (2, "风险⚠"), (3, "下降↓")]:
    # 找到进入该状态的点（从别的状态切换进来）
    entry_points = []
    for dt, p, ns, trig in transitions:
        if ns == s:
            idx = np.where(dates == dt)[0][0]
            entry_points.append(idx)
    
    if not entry_points:
        print(f"\n{s_label}: 无状态切换进入（仅初始状态延续）")
        continue
    
    print(f"\n{s_label}: {len(entry_points)}次进入")
    
    for days_out in [3, 5, 10, 20]:
        wins, total = 0, 0
        returns = []
        for idx in entry_points:
            target = idx + days_out
            if target < len(close):
                ret = (close[target] - close[idx]) / close[idx] * 100
                returns.append(ret)
                total += 1
                if s == 1 and ret > 0: wins += 1      # 上升→涨为赢
                elif s in [2, 3] and ret < 0: wins += 1  # 风险/下降→跌为赢
        if total > 0:
            wr = wins / total * 100
            avg_ret = np.mean(returns)
            print(f"  +{days_out}d: {wins}/{total}={wr:.1f}%  均收益={avg_ret:+.2f}%")

# ========== 每天的状态明细（最后30天） ==========
print("\n" + "=" * 100)
print("最后30个交易日状态明细")
print("=" * 100)
print(f"{'日期':<14} {'状态':>10} {'K值':>8} {'D值':>8}")
print("-" * 50)
for i in range(len(close)-30, len(close)):
    if state[i] > 0:
        print(f"{pd.Timestamp(dates[i]).strftime('%Y-%m-%d'):<14} {state_name[state[i]]:>10} {k[i]:>7.1f} {d[i]:>7.1f}")

# ========== 统计各状态占比 ==========
print("\n" + "=" * 100)
print("各状态在总交易日的占比")
print("=" * 100)
total_days = np.sum(state > 0)
for s, label in [(1, "上升↑"), (2, "风险⚠"), (3, "下降↓")]:
    cnt = np.sum(state == s)
    pct = cnt / (len(close) - N) * 100
    # 期间收益：从进入该状态到退出/结束的累计收益
    print(f"  {label}: {cnt}天 ({pct:.1f}%)")
