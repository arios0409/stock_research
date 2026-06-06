#!/usr/bin/env python3
"""
大盘趋势策略回测：↑上升(P_up>55%)买入 → ↓下降卖出
分别计算 2023年、2024年、2025年 收益率
"""
import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime

TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

# ── 取数据 ──
df = pro.index_daily(ts_code="000001.SH", start_date="20220701", end_date="20260526")
df = df.sort_values("trade_date").reset_index(drop=True)
close = df["close"].values
high = df["high"].values
low = df["low"].values
opens = df["open"].values
dates = pd.to_datetime(df["trade_date"]).values
date_strs = df["trade_date"].values

N, M1, M2 = 14, 5, 3

# ── KDJ ──
k = np.full(len(close), np.nan, dtype=float)
d = np.full(len(close), np.nan, dtype=float)
for i in range(N - 1, len(close)):
    hh = np.max(high[i-N+1:i+1]); ll = np.min(low[i-N+1:i+1])
    rsv = 50.0 if hh == ll else (close[i]-ll)/(hh-ll)*100
    if np.isnan(k[i-1]): k[i]=rsv; d[i]=rsv
    else:
        k[i]=(rsv*1+k[i-1]*(M1-1))/M1
        d[i]=(k[i]*1+d[i-1]*(M2-1))/M2

# ── 概率系统 ──
p_up = np.full(len(close), 50.0)
p_down = np.full(len(close), 50.0)
p_risk = np.full(len(close), 50.0)
up_days = down_days = risk_days = 0

for i in range(N, len(close)):
    prev_up = p_up[i-1]; prev_down = p_down[i-1]; prev_risk = p_risk[i-1]
    is_golden = k[i-1] <= d[i-1] and k[i] > d[i]
    is_death = k[i-1] >= d[i-1] and k[i] < d[i]
    high_death = is_death and k[i] >= 85
    in_down_zone = k[i] < 35 and d[i] < 40
    low_golden = is_golden and k[i] < 30 and d[i] < 30

    up_days = up_days+1 if k[i] > d[i] else 0
    down_days = down_days+1 if in_down_zone else 0
    risk_days = risk_days+1 if (k[i] < d[i] and k[i] >= 85) else 0

    if k[i] > d[i]:
        p_up_val = 80 if low_golden else (60 if is_golden else min(60+up_days*5,92))
        if not is_golden and not low_golden and up_days == 0:
            p_up_val = min(prev_up + 3, 70)
    else:
        p_up_val = 30 if is_death else max(prev_up-(down_days*8 if down_days>0 else 3), 10)

    if in_down_zone: p_down_val = min(55+down_days*5, 88)
    elif k[i] < d[i] and k[i] < 50: p_down_val = min(45+(50-k[i])*1.5, 80)
    elif high_death: p_down_val = 50
    elif risk_days >= 1: p_down_val = min(50+risk_days*3, 70)
    elif is_golden: p_down_val = max(prev_down-15, 10)
    else: p_down_val = max(prev_down-2, 20)

    if high_death: p_risk_val = 65
    elif risk_days >= 1 and k[i] < d[i]: p_risk_val = min(65+risk_days*5, 88)
    elif k[i] < d[i] and k[i] >= 75: p_risk_val = min(45+(k[i]-75)*2, 65)
    elif in_down_zone: p_risk_val = max(prev_risk-10, 10)
    elif is_golden: p_risk_val = max(prev_risk-20, 5)
    else: p_risk_val = max(prev_risk-2, 15)

    p_up[i]=p_up_val; p_down[i]=p_down_val; p_risk[i]=p_risk_val

# ── 状态判定 ──
state = np.full(len(close), 0, dtype=int)
for i in range(N, len(close)):
    pu=p_up[i]; pdw=p_down[i]; pr=p_risk[i]
    if pu > pr and pu > pdw: state[i] = 1  # ↑上升
    elif pr > pu and pr > pdw: state[i] = 2  # ⚠风险
    elif pdw > pu and pdw > pr: state[i] = 3  # ↓下降
    else: state[i] = 0  # 震荡

# ── 回测 ──
YEARS = {'2023': ('20230101','20231231'),
         '2024': ('20240101','20241231'),
         '2025': ('20250101','20251231')}

for year, (start, end) in YEARS.items():
    mask = (df['trade_date'] >= start) & (df['trade_date'] <= end)
    idxs = np.where(mask)[0]
    if len(idxs) == 0:
        print(f"\n=== {year}年 ===")
        print("  无数据")
        continue

    # 找出该年份内的交易索引（在N之后的）
    valid = [i for i in idxs if i >= N]

    if not valid:
        print(f"\n=== {year}年 ===")
        print("  无有效数据")
        continue

    trades = []  # [(buy_date, buy_price, sell_date, sell_price, return%)]
    in_position = False
    buy_idx = None
    buy_price = None

    for i in valid:
        current_state = state[i]
        current_p_up = p_up[i]

        # 买入：↑上升状态 且 P_up > 55%，未持仓
        if not in_position and current_state == 1 and current_p_up > 55:
            buy_idx = i
            buy_price = close[i]
            in_position = True

        # 卖出：↓下降状态，持仓中
        elif in_position and current_state == 3:
            sell_price = close[i]
            ret = (sell_price - buy_price) / buy_price * 100
            trades.append((date_strs[buy_idx], buy_price, date_strs[i], sell_price, ret))
            in_position = False
            buy_idx = None
            buy_price = None

    # 如果到年底还持仓，按年末收盘平仓
    if in_position:
        last_idx = valid[-1]
        sell_price = close[last_idx]
        ret = (sell_price - buy_price) / buy_price * 100
        trades.append((date_strs[buy_idx], buy_price, date_strs[last_idx] + "(年末)", sell_price, ret))
        in_position = False

    # ── 统计 ──
    print(f"\n{'='*60}")
    print(f"=== {year}年 回测结果 ({start}~{end}) ===")
    print(f"{'='*60}")

    if not trades:
        print("  无交易信号")
        continue

    total_ret = 1.0
    for j, (bd, bp, sd, sp, r) in enumerate(trades, 1):
        total_ret *= (1 + r/100)
        print(f"  第{j}笔: {bd} 买入({bp:.1f}) → {sd} 卖出({sp:.1f}) 收益{r:+.2f}%")

    total_pct = (total_ret - 1) * 100
    wins = sum(1 for _,_,_,_,r in trades if r > 0)
    losses = sum(1 for _,_,_,_,r in trades if r <= 0)
    avg_ret = np.mean([r for _,_,_,_,r in trades])
    max_win = max([r for _,_,_,_,r in trades])
    max_loss = min([r for _,_,_,_,r in trades])
    days_in_market = sum([(pd.Timestamp(sd[:8] if '(' not in sd else sd[:8]) - pd.Timestamp(bd)).days for bd,_,sd,_,_ in trades])

    print(f"\n  📊 汇总:")
    print(f"  交易次数: {len(trades)}次")
    print(f"  胜率: {wins}/{len(trades)} = {wins/len(trades)*100:.1f}%")
    print(f"  累计收益率: {total_pct:+.2f}%")
    print(f"  平均单笔收益: {avg_ret:+.2f}%")
    print(f"  最大单笔盈利: {max_win:+.2f}%")
    print(f"  最大单笔亏损: {max_loss:+.2f}%")
    print(f"  市场持有天数: {days_in_market}天")

    # 对比同期上证涨幅
    first_close = close[valid[0]]
    last_close = close[valid[-1]]
    buy_hold = (last_close - first_close) / first_close * 100
    print(f"  同期上证涨跌幅: {buy_hold:+.2f}%")

    # 年度化收益
    days_total = (pd.Timestamp(end[:4]+'-'+end[4:6]+'-'+end[6:]) if end != '20260526' else datetime.now()) - pd.Timestamp(start[:4]+'-'+start[4:6]+'-'+start[6:])
    days_total = days_total.days
    if days_total > 0:
        annual_ret = ((1+total_pct/100) ** (365/days_total) - 1) * 100
        print(f"  年化收益率: {annual_ret:+.2f}%")
