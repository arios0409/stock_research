#!/usr/bin/env python3
"""KDJ(14,5,3) 概率趋势系统"""

import tushare as ts
import pandas as pd
import numpy as np

TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

df = pro.index_daily(ts_code="000001.SH", start_date="20240801", end_date="20260526")
df = df.sort_values("trade_date").reset_index(drop=True)
df["date"] = pd.to_datetime(df["trade_date"])

close = df["close"].values
high = df["high"].values
low = df["low"].values
dates = df["date"].values

N, M1, M2 = 14, 5, 3

# KDJ
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

# ========== 概率系统 ==========
p_up = np.full(len(close), np.nan, dtype=float)     # 上涨概率
p_down = np.full(len(close), np.nan, dtype=float)   # 下降概率
p_risk = np.full(len(close), np.nan, dtype=float)   # 风险概率

up_days = 0      # 持续上涨天数（K>D持续天数）
down_days = 0    # 持续下降天数（K<35&D<40持续天数）
risk_days = 0    # 持续风险天数（高位死叉K<D且K≥85持续天数）

for i in range(N, len(close)):
    if np.isnan(k[i]) or np.isnan(d[i]):
        p_up[i] = p_up[i-1] if not np.isnan(p_up[i-1]) else 50
        p_down[i] = p_down[i-1] if not np.isnan(p_down[i-1]) else 50
        p_risk[i] = p_risk[i-1] if not np.isnan(p_risk[i-1]) else 50
        continue
    
    prev_up = p_up[i-1] if not np.isnan(p_up[i-1]) else 50
    prev_down = p_down[i-1] if not np.isnan(p_down[i-1]) else 50
    prev_risk = p_risk[i-1] if not np.isnan(p_risk[i-1]) else 50
    
    # === 信号检测 ===
    # 金叉：K上穿D
    is_golden = False
    if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
        if k[i-1] <= d[i-1] and k[i] > d[i]:
            is_golden = True
    
    # 低位金叉额外加分：K<30 AND D<30
    low_golden_bonus = is_golden and k[i] < 30 and d[i] < 30
    
    # 死叉：K下穿D
    is_death = False
    if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
        if k[i-1] >= d[i-1] and k[i] < d[i]:
            is_death = True
    
    # 高位死叉：K≥85时下穿D
    high_death = is_death and k[i] >= 85
    
    # 下降区域：K<35 & D<40
    in_down_zone = k[i] < 35 and d[i] < 40
    
    # === 持续天数更新 ===
    if k[i] > d[i]:
        up_days += 1
    else:
        up_days = 0
    
    if in_down_zone:
        down_days += 1
    else:
        down_days = 0
    
    if k[i] < d[i] and k[i] >= 85:
        risk_days += 1
    else:
        risk_days = 0
    
    # === 上涨概率 P_up ===
    if k[i] > d[i]:
        # K>D: 上涨活跃
        if is_golden and low_golden_bonus:
            p_up_val = 80   # 低位金叉，强力看涨
        elif is_golden:
            p_up_val = 60   # 普通金叉起步60%
        elif up_days >= 1:
            p_up_val = min(60 + up_days * 5, 92)  # 每天+5%
        else:
            p_up_val = min(prev_up + 3, 70)       # K>D但没金叉，缓慢增加
    else:
        # K<D: 下跌活跃，上涨概率快速衰减
        if is_death:
            p_up_val = 30   # 死叉日直接降到30
        elif k[i] < d[i]:
            decay = down_days * 8 if down_days > 0 else 3
            p_up_val = max(prev_up - decay, 10)   # 持续K<D每天-8
        else:
            p_up_val = max(prev_up - 5, 10)
    
    # === 下降概率 P_down ===
    if in_down_zone:
        p_down_val = min(55 + down_days * 5, 88)
    elif k[i] < d[i] and k[i] < 50:
        # K<D且K在低位，有下降倾向
        p_down_val = min(45 + (50 - k[i]) * 1.5, 80)
    elif high_death:
        p_down_val = 50   # 高位死叉起步
    elif risk_days >= 1:
        p_down_val = min(50 + risk_days * 3, 70)  # 高位死叉持续每天+3
    elif is_golden:
        p_down_val = max(prev_down - 15, 10)
    else:
        p_down_val = max(prev_down - 2, 20)  # 缓慢回归
    
    # === 风险概率 P_risk ===
    if high_death:
        p_risk_val = 65   # 高位死叉当天65%
    elif risk_days >= 1 and k[i] < d[i]:
        p_risk_val = min(65 + risk_days * 5, 88)  # 持续高位死叉
    elif k[i] < d[i] and k[i] >= 75:
        # K持续下降但还没死叉，风险上升
        p_risk_val = min(45 + (k[i] - 75) * 2, 65)
    elif in_down_zone:
        p_risk_val = max(prev_risk - 10, 10)  # 已经确认下降，风险降低
    elif is_golden:
        p_risk_val = max(prev_risk - 20, 5)
    else:
        p_risk_val = max(prev_risk - 2, 15)
    
    p_up[i] = round(p_up_val, 1)
    p_down[i] = round(p_down_val, 1)
    p_risk[i] = round(p_risk_val, 1)

# 判定：取概率最高的状态
final_state = np.full(len(close), "", dtype=object)
for i in range(N, len(close)):
    if p_up[i] > p_risk[i] and p_up[i] > p_down[i]:
        final_state[i] = "↑上升"
    elif p_risk[i] > p_up[i] and p_risk[i] > p_down[i]:
        final_state[i] = "⚠风险"
    elif p_down[i] > p_up[i] and p_down[i] > p_risk[i]:
        final_state[i] = "↓下降"
    else:
        final_state[i] = "—震荡"

# ========== 输出 ==========
print("=" * 120)
print("KDJ(14,5,3) 概率趋势系统 — 最近30天")
print("=" * 120)
print(f"{'日期':<14} {'K值':>8} {'D值':>8} {'P_up':>8} {'P_down':>8} {'P_risk':>8} {'状态':>8}")
print("-" * 70)
for i in range(len(close)-30, len(close)):
    if np.isnan(p_up[i]): continue
    print(f"{pd.Timestamp(dates[i]).strftime('%Y-%m-%d'):<14} {k[i]:>7.1f} {d[i]:>7.1f} {p_up[i]:>7.0f}% {p_down[i]:>7.0f}% {p_risk[i]:>7.0f}% {final_state[i]:>8}")

# 评估：当P_up > 60时买入，+3d/+5d胜率
print("\n" + "=" * 80)
print("策略评估: P_up > 60时买入")
print("=" * 80)

buy_signals = []
in_trade = False
for i in range(N, len(close)):
    if p_up[i] >= 60 and not in_trade:
        buy_signals.append(i)
        in_trade = True
    if p_up[i] < 50:
        in_trade = False

w3, w5, t3, t5 = 0, 0, 0, 0
for idx in buy_signals:
    r3 = (close[idx+3] - close[idx]) / close[idx] * 100 if idx+3 < len(close) else None
    r5 = (close[idx+5] - close[idx]) / close[idx] * 100 if idx+5 < len(close) else None
    if r3 is not None: t3 += 1
    if r5 is not None: t5 += 1
    if r3 is not None and r3 > 0: w3 += 1
    if r5 is not None and r5 > 0: w5 += 1

print(f"买入信号(P_up≥60): {len(buy_signals)}次  +3d={w3}/{t3}={w3/t3*100:.1f}%  +5d={w5}/{t5}={w5/t5*100:.1f}%")

# 按阈值分段评估
print(f"\n买入概率阈值扫描:")
for thresh in [55, 60, 65, 70, 75, 80]:
    buys = []
    in_trade = False
    for i in range(N, len(close)):
        if p_up[i] >= thresh and not in_trade:
            buys.append(i)
            in_trade = True
        if p_up[i] < 50:
            in_trade = False
    if buys:
        w3 = sum(1 for idx in buys if idx+3 < len(close) and (close[idx+3]-close[idx])/close[idx]*100 > 0)
        t3 = sum(1 for idx in buys if idx+3 < len(close))
        print(f"  P_up≥{thresh}: {len(buys)}次买入  +3d={w3}/{t3}={w3/t3*100:.0f}%")

# 下降信号评估
print(f"\n下降信号(P_down≥55):")
sell_signals = []
in_sell = False
for i in range(N, len(close)):
    if p_down[i] >= 55 and not in_sell:
        sell_signals.append(i)
        in_sell = True
    if p_down[i] < 45:
        in_sell = False

w3, t3 = 0, 0
for idx in sell_signals:
    r = (close[idx+3] - close[idx]) / close[idx] * 100 if idx+3 < len(close) else None
    if r is not None: t3 += 1
    if r is not None and r < 0: w3 += 1

print(f"  P_down≥55: {len(sell_signals)}次卖出  +3d下跌胜率={w3}/{t3}={w3/t3*100:.0f}%")
