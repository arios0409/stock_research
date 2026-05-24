#!/usr/bin/env python3
"""三状态机 V3：信号触发 + 持续确认期"""

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

CONFIRM = 3  # 3天确认期（包括信号当天）

for confirm_days in [0, 2, 3, 5]:
    # 状态: 0=初始, 1=上升, 2=风险, 3=下降
    state = np.full(len(close), 0, dtype=int)
    transitions = []
    
    # 信号的累积计数器
    golden_count = 0      # K > D 持续天数
    death_count = 0       # K < D (高位) 持续天数  
    down_count = 0        # K<35 & D<40 持续天数
    
    for i in range(N, len(close)):
        if np.isnan(k[i]) or np.isnan(d[i]):
            state[i] = state[i-1] if i > 0 else 0
            continue
        
        prev_state = state[i-1]
        
        # 信号检测
        sig_golden = False
        sig_high_death = False
        sig_down_zone = False
        
        # 金叉：K上穿D 或 K>D持续
        if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
            if k[i-1] <= d[i-1] and k[i] > d[i]:
                sig_golden = True
        # 高位死叉
        if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
            if k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= 85:
                sig_high_death = True
        # 下降区域
        if k[i] < 35 and d[i] < 40:
            sig_down_zone = True
        
        # 更新持续计数器
        if k[i] > d[i]:
            golden_count += 1
        else:
            golden_count = 0
        
        if k[i] < d[i] and k[i] >= 85:
            death_count += 1
        else:
            death_count = 0
        
        if k[i] < 35 and d[i] < 40:
            down_count += 1
        else:
            down_count = 0
        
        # 带确认期的状态切换
        new_state = prev_state
        
        if golden_count >= confirm_days if confirm_days > 0 else sig_golden:
            new_state = 1
        elif down_count >= confirm_days if confirm_days > 0 else sig_down_zone:
            new_state = 3
        elif (death_count >= confirm_days if confirm_days > 0 else sig_high_death) and prev_state == 1:
            new_state = 2
        
        state[i] = new_state
        
        if new_state != prev_state and prev_state != 0:
            trigger = ""
            if golden_count >= (confirm_days or 1): trigger = "金叉确认"
            elif down_count >= (confirm_days or 1): trigger = "下降确认"
            elif death_count >= (confirm_days or 1): trigger = "高位死叉确认"
            transitions.append((dates[i], prev_state, new_state, trigger))
    
    # 评估
    sn = {0:"初始", 1:"上升↑", 2:"风险⚠", 3:"下降↓"}
    print(f"\n{'='*80}")
    print(f"确认期 = {confirm_days}天  切换次数: {len(transitions)}")
    print(f"{'='*80}")
    
    if transitions:
        print(f"{'日期':<14} {'从':>8}→{'到':>8} {'触发':<16} K值")
        for dt, p, ns, trig in transitions[-8:]:
            idx = np.where(dates == dt)[0][0]
            print(f"  {pd.Timestamp(dt).strftime('%Y-%m-%d'):<14} {sn[p]:>8}→{sn[ns]:>8} {trig:<16} K={k[idx]:.1f}")
    
    for s, s_label, direction in [(1, "上升↑", "涨"), (2, "风险⚠", "跌"), (3, "下降↓", "跌")]:
        entry_points = [np.where(dates == dt)[0][0] for dt, p, ns, trig in transitions if ns == s]
        if not entry_points:
            print(f"  {s_label}: 无进入")
            continue
        
        parts = [f"  {s_label}: {len(entry_points)}次进入"]
        for days_out in [3, 5]:
            wins, total, rets = 0, 0, []
            for idx in entry_points:
                t = idx + days_out
                if t < len(close):
                    r = (close[t] - close[idx]) / close[idx] * 100
                    rets.append(r); total += 1
                    if (direction == "涨" and r > 0) or (direction == "跌" and r < 0): wins += 1
            if total:
                parts.append(f"+{days_out}d:{wins}/{total}={wins/total*100:.0f}%")
        print("  ".join(parts))
    
    # 占比
    total_days = len(close) - N
    parts = ["  占比:"]
    for s, label in [(1, "↑"), (2, "⚠"), (3, "↓")]:
        cnt = np.sum(state[N:] == s)
        parts.append(f"{label}={cnt/total_days*100:.0f}%")
    print("  ".join(parts))
