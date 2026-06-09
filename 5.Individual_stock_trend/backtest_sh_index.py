#!/usr/bin/env python3
"""
上证指数 按年份回测 v1/v2
策略: state→↑买入 / state=↓且P_down>50→卖出
年份: 2023, 2024, 2025 (+ 2026至今)
"""

import numpy as np
import tushare as ts
import pandas as pd

TUSHARE_TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
N, M1, M2 = 14, 5, 3
pro = ts.pro_api(TUSHARE_TOKEN)

YEARS = [2023, 2024, 2025]

def compute_kdj(high, low, close):
    k = np.full(len(close), np.nan)
    d = np.full(len(close), np.nan)
    for i in range(N - 1, len(close)):
        hh = np.max(high[i - N + 1:i + 1])
        ll = np.min(low[i - N + 1:i + 1])
        rsv = 50.0 if hh == ll else (close[i] - ll) / (hh - ll) * 100
        if np.isnan(k[i - 1]):
            k[i] = rsv; d[i] = rsv
        else:
            k[i] = (rsv * 1 + k[i - 1] * (M1 - 1)) / M1
            d[i] = (k[i] * 1 + d[i - 1] * (M2 - 1)) / M2
    return k, d

def run_system(close, high, low, k, d):
    n = len(close)
    p_up = np.full(n, 50.0); p_down = np.full(n, 50.0); p_risk = np.full(n, 50.0)
    state = np.full(n, 0, dtype=int)
    up_days = down_days = risk_days = 0

    for i in range(N, n):
        prev_up = p_up[i - 1]; prev_down = p_down[i - 1]; prev_risk = p_risk[i - 1]
        is_golden = k[i - 1] <= d[i - 1] and k[i] > d[i]
        is_death = k[i - 1] >= d[i - 1] and k[i] < d[i]
        high_death = is_death and k[i] >= 85
        in_down_zone = k[i] < 35 and d[i] < 40
        low_golden_bonus = is_golden and k[i] < 30 and d[i] < 30

        up_days = up_days + 1 if k[i] > d[i] else 0
        down_days = down_days + 1 if in_down_zone else 0
        risk_days = risk_days + 1 if (k[i] < d[i] and k[i] >= 85) else 0

        if k[i] > d[i]:
            pu = 80 if low_golden_bonus else (60 if is_golden else min(60 + up_days * 5, 92))
        else:
            pu = 30 if is_death else max(prev_up - (down_days * 8 if down_days > 0 else 3), 10)
        p_up[i] = pu

        if in_down_zone: pd = min(55 + down_days * 5, 88)
        elif k[i] < d[i] and k[i] < 50: pd = min(45 + (50 - k[i]) * 1.5, 80)
        elif high_death: pd = 50
        elif risk_days >= 1: pd = min(50 + risk_days * 3, 70)
        elif is_golden: pd = max(prev_down - 15, 10)
        else: pd = max(prev_down - 2, 20)
        p_down[i] = pd

        if high_death: pr = 65
        elif risk_days >= 1 and k[i] < d[i]: pr = min(65 + risk_days * 5, 88)
        elif k[i] < d[i] and k[i] >= 75: pr = min(45 + (k[i] - 75) * 2, 65)
        elif in_down_zone: pr = max(prev_risk - 10, 10)
        elif is_golden: pr = max(prev_risk - 20, 5)
        else: pr = max(prev_risk - 2, 15)
        p_risk[i] = pr

        if p_up[i] > p_risk[i] and p_up[i] > p_down[i]: s = 1
        elif p_risk[i] > p_up[i] and p_risk[i] > p_down[i]: s = 2
        elif p_down[i] > p_up[i] and p_down[i] > p_risk[i]: s = 3
        else: s = 0
        state[i] = s

    return p_up, p_down, p_risk, state

def simulate_trades(close, state, p_down, start_idx):
    trades = []
    in_position = False
    buy_idx = None
    for i in range(start_idx, len(close)):
        s = state[i]
        if not in_position:
            if s == 1: buy_idx = i; in_position = True
        else:
            if s == 3 and p_down[i] > 50:
                bp = close[buy_idx]; sp = close[i]
                trades.append((buy_idx, i, bp, sp, (sp - bp) / bp * 100))
                in_position = False
    if in_position:
        bp = close[buy_idx]; sp = close[-1]
        trades.append((buy_idx, len(close) - 1, bp, sp, (sp - bp) / bp * 100))
    return trades

def bh_ret(close):
    """买入持有收益"""
    return (close[-1] - close[0]) / close[0] * 100

# ===== 加载全量数据 =====
print("加载上证指数全量数据...")
df_all = pro.index_daily(ts_code="000001.SH", start_date="20220101", end_date="20260609")
df_all = df_all.sort_values("trade_date").reset_index(drop=True)
df_all['year'] = pd.to_datetime(df_all['trade_date']).dt.year

close_all = df_all['close'].values
high_all = df_all['high'].values
low_all = df_all['low'].values
years_all = df_all['year'].values
total = len(close_all)
print(f"{len(df_all)} 条, {df_all['trade_date'].iloc[0]} ~ {df_all['trade_date'].iloc[-1]}")

# KDJ
k_all, d_all = compute_kdj(high_all, low_all, close_all)

# ===== 逐年回测 =====
print("\n" + "=" * 80)
print(f"  上证指数 年度回测: state→↑买入 / state=↓且P_down>50→卖出")
print("=" * 80)
print(f"{'年份':<8} {'买入持有':>10} {'策略收益':>10} {'交易笔数':>8} {'胜率':>8} {'跑赢持有':>10}")
print("-" * 80)

all_trades_2023 = []; all_trades_2024 = []; all_trades_2025 = []

for year in YEARS:
    start_i = None
    for i in range(total):
        if years_all[i] == year:
            start_i = i
            break
    if start_i is None:
        continue

    end_i = total - 1
    for i in range(total - 1, -1, -1):
        if years_all[i] == year:
            end_i = i
            break

    c = close_all[start_i:end_i + 1]
    h = high_all[start_i:end_i + 1]
    l = low_all[start_i:end_i + 1]
    k = k_all[start_i:end_i + 1]
    d = d_all[start_i:end_i + 1]

    pu, pd, pr, st = run_system(c, h, l, k, d)
    trades = simulate_trades(c, st, pd, N)
    bh = bh_ret(c)

    wins = sum(1 for t in trades if t[4] > 0)
    wr = wins / len(trades) * 100 if trades else 0
    cum = np.prod([1 + t[4] / 100 for t in trades]) - 1 if trades else 0
    cum_pct = cum * 100

    beat = "✅" if cum_pct > bh else "❌"
    print(f"  {year}   {bh:>9.1f}%  {cum_pct:>9.1f}%  {len(trades):>8}  "
          f"{wr:>7.1f}%    {beat} {cum_pct-bh:+.1f}%")

    # 存交易明细
    if year == 2023: all_trades_2023 = trades
    elif year == 2024: all_trades_2024 = trades
    elif year == 2025: all_trades_2025 = trades

print("-" * 80)

# ===== 2026 至今 =====
start_2026 = None
for i in range(total):
    if years_all[i] == 2026:
        start_2026 = i; break
if start_2026:
    end_2026 = total - 1
    c6 = close_all[start_2026:end_2026 + 1]
    h6 = high_all[start_2026:end_2026 + 1]
    l6 = low_all[start_2026:end_2026 + 1]
    k6 = k_all[start_2026:end_2026 + 1]
    d6 = d_all[start_2026:end_2026 + 1]
    pu6, pd6, pr6, st6 = run_system(c6, h6, l6, k6, d6)
    tr6 = simulate_trades(c6, st6, pd6, N)
    bh6 = bh_ret(c6)
    cum6 = np.prod([1 + t[4] / 100 for t in tr6]) - 1 if tr6 else 0
    w6 = sum(1 for t in tr6 if t[4] > 0)
    wr6 = w6 / len(tr6) * 100 if tr6 else 0
    beat6 = "✅" if cum6 * 100 > bh6 else "❌"
    print(f"  2026至今  {bh6:>7.1f}%  {cum6*100:>9.1f}%  {len(tr6):>8}  "
          f"{wr6:>7.1f}%    {beat6} {cum6*100-bh6:+.1f}%")

# 汇总
all_years_trades = len(all_trades_2023) + len(all_trades_2024) + len(all_trades_2025)
all_years_wins = (sum(1 for t in all_trades_2023 if t[4] > 0) +
                  sum(1 for t in all_trades_2024 if t[4] > 0) +
                  sum(1 for t in all_trades_2025 if t[4] > 0))
print("-" * 80)
print(f"  三年合计  {'':>10} {'':>10} {all_years_trades:>8}  "
      f"{all_years_wins/all_years_trades*100:>7.1f}%")

# ===== 逐笔交易明细 =====
print("\n" + "=" * 80)
print("  逐笔交易明细")
print("=" * 80)

for year, trades in [(2023, all_trades_2023), (2024, all_trades_2024),
                      (2025, all_trades_2025)]:
    if not trades:
        continue
    print(f"\n  {year}年 ({len(trades)}笔):")
    cum = 1.0
    for i, t in enumerate(trades):
        cum *= (1 + t[4] / 100)
        print(f"    {i+1:>2}. 买入 {t[2]:.2f} → 卖出 {t[3]:.2f}  "
              f"收益 {t[4]:+.2f}%  累计 {((cum-1)*100):+.1f}%")

# ===== 资金流说明 =====
print("\n" + "=" * 80)
print("  ⚠ 上证指数无 moneyflow 数据，v1=v2（资金流仅个股级别可用）")
print("  本回测结果为纯 KDJ 概率策略表现")
print("=" * 80)
