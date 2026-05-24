#!/usr/bin/env python3
"""三状态机 V2：加2天确认期防止快速翻转"""

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

# ========== 三状态机 V2（2天确认期）==========
# 状态: 0=初始, 1=上升↑, 2=风险⚠, 3=下降↓
state = np.full(len(close), 0, dtype=int)
transitions = []

# 信号积累：连续N天触发后才切换
CONFIRM_DAYS = 2

for i in range(N, len(close)):
    if np.isnan(k[i]) or np.isnan(d[i]):
        state[i] = state[i-1] if i > 0 else 0
        continue
    
    prev_state = state[i-1]
    
    # 检测今天的信号
    sig_golden = False
    sig_high_death = False  # 高位死叉 K≥85
    sig_down_zone = False   # K<35 & D<40
    
    if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
        if k[i-1] <= d[i-1] and k[i] > d[i]:
            sig_golden = True
    if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
        if k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= 85:
            sig_high_death = True
    if k[i] < 35 and d[i] < 40:
        sig_down_zone = True
    
    # 确认期逻辑：往前看CONFIRM_DAYS天，如果信号持续出现则切换
    # 金叉确认
    golden_confirmed = sig_golden
    if golden_confirmed and CONFIRM_DAYS > 1:
        for j in range(1, CONFIRM_DAYS):
            if i - j < N: break
            if np.isnan(k[i-j]) or np.isnan(d[i-j]) or np.isnan(k[i-j-1]) or np.isnan(d[i-j-1]):
                golden_confirmed = False
                break
            if not (k[i-j-1] <= d[i-j-1] and k[i-j] > d[i-j]):
                if not (k[i-j] > d[i-j]):  # 持续处于K>D也算
                    golden_confirmed = False
                    break
    
    # 下降区域确认
    down_confirmed = sig_down_zone
    if down_confirmed and CONFIRM_DAYS > 1:
        for j in range(1, CONFIRM_DAYS):
            if i - j < N: break
            if np.isnan(k[i-j]) or np.isnan(d[i-j]):
                down_confirmed = False
                break
            if not (k[i-j] < 35 and d[i-j] < 40):
                down_confirmed = False
                break
    
    # 高位死叉确认
    death_confirmed = sig_high_death
    if death_confirmed and CONFIRM_DAYS > 1:
        for j in range(1, CONFIRM_DAYS):
            if i - j < N: break
            if np.isnan(k[i-j]) or np.isnan(k[i-j-1]) or np.isnan(d[i-j]) or np.isnan(d[i-j-1]):
                death_confirmed = False
                break
            was_death = (k[i-j-1] >= d[i-j-1] and k[i-j] < d[i-j] and k[i-j] >= 85)
            if not was_death and not (k[i-j] < d[i-j]):  # 持续处于K<D也算
                death_confirmed = False
                break
    
    new_state = prev_state
    
    if golden_confirmed:
        new_state = 1
    elif down_confirmed:
        new_state = 3
    elif death_confirmed and prev_state == 1:
        new_state = 2
    
    state[i] = new_state
    
    if new_state != prev_state and prev_state != 0:
        trigger = "金叉" if golden_confirmed else ("K<35&D<40" if down_confirmed else "高位死叉")
        transitions.append((dates[i], prev_state, new_state, trigger))

print("=" * 100)
print(f"三状态机 V2（{CONFIRM_DAYS}天确认期）切换记录")
print("=" * 100)
print(f"{'日期':<14} {'从':>8} → {'到':>8} {'触发':<16} {'K值':>8} {'D值':>8}")
print("-" * 100)
for dt, p, ns, trig in transitions:
    idx = np.where(dates == dt)[0][0]
    state_name = {0:"初始", 1:"上升↑", 2:"风险⚠", 3:"下降↓"}
    print(f"{pd.Timestamp(dt).strftime('%Y-%m-%d'):<14} {state_name[p]:>8} → {state_name[ns]:>8} {trig:<16} {k[idx]:>7.1f} {d[idx]:>7.1f}")

# 评估
print("\n" + "=" * 100)
print("各状态进入后表现评估")
print("=" * 100)

for s, s_label, direction in [(1, "上升↑", "涨"), (2, "风险⚠", "跌"), (3, "下降↓", "跌")]:
    entry_points = []
    for dt, p, ns, trig in transitions:
        if ns == s:
            idx = np.where(dates == dt)[0][0]
            entry_points.append(idx)
    
    if not entry_points:
        print(f"\n{s_label}: 无进入记录")
        continue
    
    print(f"\n{s_label}: {len(entry_points)}次进入")
    
    for days_out in [3, 5, 10, 20]:
        wins, total, rets = 0, 0, []
        for idx in entry_points:
            t = idx + days_out
            if t < len(close):
                r = (close[t] - close[idx]) / close[idx] * 100
                rets.append(r)
                total += 1
                if (direction == "涨" and r > 0) or (direction == "跌" and r < 0):
                    wins += 1
        if total > 0:
            wr = wins / total * 100
            print(f"  +{days_out}d: {wins}/{total}={wr:.1f}%  均收益={np.mean(rets):+.2f}%")

# 各状态占比
print("\n" + "=" * 100)
print("各状态在总交易日占比")
print("=" * 100)
total = len(close) - N
for s, label in [(1, "上升↑"), (2, "风险⚠"), (3, "下降↓"), (0, "未定义")]:
    cnt = np.sum(state[N:] == s)
    pct = cnt / total * 100
    print(f"  {label}: {cnt}天 ({pct:.1f}%)")

print(f"\n总交易日（有KDJ): {total}天")
print(f"状态切换次数: {len(transitions)}次")

# 最后状态明细
print(f"\n最后15天状态:")
print(f"{'日期':<14} {'状态':>10} {'K值':>8} {'D值':>8}")
for i in range(len(close)-15, len(close)):
    sn = {0:"初始", 1:"上升↑", 2:"风险⚠", 3:"下降↓"}
    print(f"{pd.Timestamp(dates[i]).strftime('%Y-%m-%d'):<14} {sn[state[i]]:>10} {k[i]:>7.1f} {d[i]:>7.1f}")
