#!/usr/bin/env python3
"""
v1 vs v2 策略对比回测
策略规则:
  买入: 状态进入 ↑上升 时，以当日收盘价买入
  卖出: 状态为 ↓下降 且 P_down > 50% 时，以当日收盘价卖出
比较 v1(无资金流) 和 v2(含资金流) 的累计收益率
"""

import sys, os
import numpy as np
import tushare as ts
import pandas as pd
from datetime import datetime

TUSHARE_TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
N, M1, M2 = 14, 5, 3
MF_WEIGHTS = {5: 0.50, 10: 0.30, 20: 0.20}
MF_RESONANCE_BOOST = 12
MF_DIVERGENCE_PENALTY = 10

# 测试股票池
TEST_STOCKS = [
    ("300450.SZ", "先导智能"),
    ("920026.BJ", "卓兆点胶"),
    ("600885.SH", "宏发股份"),
    ("300234.SZ", "开尔新材"),
    ("600519.SH", "贵州茅台"),
    ("002594.SZ", "比亚迪"),
]

pro = ts.pro_api(TUSHARE_TOKEN)


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


def compute_mf_signals(net_mf):
    n = len(net_mf)
    mf_cum5 = np.zeros(n); mf_cum10 = np.zeros(n); mf_cum20 = np.zeros(n)
    mf_score = np.zeros(n); mf_direction = np.zeros(n, dtype=int)

    for i in range(n):
        s5 = max(0, i - 4); s10 = max(0, i - 9); s20 = max(0, i - 19)
        mf_cum5[i] = np.sum(net_mf[s5:i + 1])
        mf_cum10[i] = np.sum(net_mf[s10:i + 1])
        mf_cum20[i] = np.sum(net_mf[s20:i + 1])

        sc5 = np.clip(mf_cum5[i] / 1000, -10, 10) * MF_WEIGHTS[5] * 10
        sc10 = np.clip(mf_cum10[i] / 2000, -10, 10) * MF_WEIGHTS[10] * 10
        sc20 = np.clip(mf_cum20[i] / 3000, -10, 10) * MF_WEIGHTS[20] * 10
        mf_score[i] = np.clip(sc5 + sc10 + sc20, -100, 100)
        if mf_score[i] > 15: mf_direction[i] = 1
        elif mf_score[i] < -15: mf_direction[i] = -1
    return mf_score, mf_direction


def run_v1(close, high, low, k, d):
    """v1 概率系统 (无资金流)"""
    n = len(close)
    p_up = np.full(n, 50.0); p_down = np.full(n, 50.0); p_risk = np.full(n, 50.0)
    up_days = down_days = risk_days = 0

    for i in range(N, n):
        prev_up = p_up[i - 1]; prev_down = p_down[i - 1]
        is_golden = k[i - 1] <= d[i - 1] and k[i] > d[i]
        is_death = k[i - 1] >= d[i - 1] and k[i] < d[i]
        high_death = is_death and k[i] >= 85
        in_down_zone = k[i] < 35 and d[i] < 40
        low_golden_bonus = is_golden and k[i] < 30 and d[i] < 30

        up_days = up_days + 1 if k[i] > d[i] else 0
        down_days = down_days + 1 if in_down_zone else 0
        risk_days = risk_days + 1 if (k[i] < d[i] and k[i] >= 85) else 0

        if k[i] > d[i]:
            if low_golden_bonus: pu = 80
            elif is_golden: pu = 60
            else: pu = min(60 + up_days * 5, 92)
        else:
            if is_death: pu = 30
            else: pu = max(prev_up - (down_days * 8 if down_days > 0 else 3), 10)
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
        elif in_down_zone: pr = max(p_risk[i - 1] - 10, 10)
        elif is_golden: pr = max(p_risk[i - 1] - 20, 5)
        else: pr = max(p_risk[i - 1] - 2, 15)
        p_risk[i] = pr

    # 状态
    state = np.full(n, 0, dtype=int)
    for i in range(N, n):
        if p_up[i] > p_risk[i] and p_up[i] > p_down[i]: s = 1
        elif p_risk[i] > p_up[i] and p_risk[i] > p_down[i]: s = 2
        elif p_down[i] > p_up[i] and p_down[i] > p_risk[i]: s = 3
        else: s = 0
        state[i] = s
    return p_up, p_down, p_risk, state


def run_v2(close, high, low, k, d, mf_score, mf_direction):
    """v2 概率系统 (含资金流共振/背离)"""
    n = len(close)
    p_up = np.full(n, 50.0); p_down = np.full(n, 50.0); p_risk = np.full(n, 50.0)
    p_up_raw = np.full(n, 50.0)
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

        # 原始 P_up
        if k[i] > d[i]:
            if low_golden_bonus: pu_raw = 80
            elif is_golden: pu_raw = 60
            else: pu_raw = min(60 + up_days * 5, 92)
        else:
            if is_death: pu_raw = 30
            else: pu_raw = max(prev_up - (down_days * 8 if down_days > 0 else 3), 10)
        p_up_raw[i] = pu_raw

        # 资金共振/背离调整
        mf_s = mf_score[i]; mf_dir = mf_direction[i]
        close_5d_ago = close[max(0, i - 5)]
        pct_5d = (close[i] - close_5d_ago) / close_5d_ago * 100 if close_5d_ago > 0 else 0

        if pct_5d > 3 and mf_s < -20:
            pu_adj = max(pu_raw - MF_DIVERGENCE_PENALTY, 5)
        elif pct_5d < -3 and mf_s > 20:
            pu_adj = min(pu_raw + MF_DIVERGENCE_PENALTY, 95)
        elif k[i] > d[i] and mf_dir == 1:
            boost = min(abs(mf_s) / 100 * MF_RESONANCE_BOOST, MF_RESONANCE_BOOST)
            pu_adj = min(pu_raw + boost, 95)
        elif k[i] < d[i] and mf_dir == -1:
            penalty = min(abs(mf_s) / 100 * MF_RESONANCE_BOOST, MF_RESONANCE_BOOST)
            pu_adj = max(pu_raw - penalty, 5)
        else:
            pu_adj = pu_raw
        p_up[i] = pu_adj

        # P_down (same as v1)
        if in_down_zone: pd = min(55 + down_days * 5, 88)
        elif k[i] < d[i] and k[i] < 50: pd = min(45 + (50 - k[i]) * 1.5, 80)
        elif high_death: pd = 50
        elif risk_days >= 1: pd = min(50 + risk_days * 3, 70)
        elif is_golden: pd = max(prev_down - 15, 10)
        else: pd = max(prev_down - 2, 20)
        p_down[i] = pd

        # P_risk (same as v1)
        if high_death: pr = 65
        elif risk_days >= 1 and k[i] < d[i]: pr = min(65 + risk_days * 5, 88)
        elif k[i] < d[i] and k[i] >= 75: pr = min(45 + (k[i] - 75) * 2, 65)
        elif in_down_zone: pr = max(prev_risk - 10, 10)
        elif is_golden: pr = max(prev_risk - 20, 5)
        else: pr = max(prev_risk - 2, 15)
        p_risk[i] = pr

    # 状态
    state = np.full(n, 0, dtype=int)
    for i in range(N, n):
        if p_up[i] > p_risk[i] and p_up[i] > p_down[i]: s = 1
        elif p_risk[i] > p_up[i] and p_risk[i] > p_down[i]: s = 2
        elif p_down[i] > p_up[i] and p_down[i] > p_risk[i]: s = 3
        else: s = 0
        state[i] = s
    return p_up, p_down, p_risk, state


def simulate_trades(close, state, p_down, start_idx):
    """
    模拟交易:
      state 进入 1(↑上升) → 买入
      state == 3(↓下降) AND p_down > 50 → 卖出
    返回: 交易列表 [(buy_idx, sell_idx, buy_price, sell_price, ret%), ...]
    """
    trades = []
    in_position = False
    buy_idx = None

    for i in range(start_idx, len(close)):
        s = state[i]
        if not in_position:
            if s == 1:
                buy_idx = i
                in_position = True
        else:
            if s == 3 and p_down[i] > 50:
                buy_p = close[buy_idx]
                sell_p = close[i]
                ret = (sell_p - buy_p) / buy_p * 100
                trades.append((buy_idx, i, buy_p, sell_p, ret))
                in_position = False

    # 如果回测结束仍持仓，以最后一日收盘价平仓
    if in_position:
        buy_p = close[buy_idx]
        sell_p = close[-1]
        ret = (sell_p - buy_p) / buy_p * 100
        trades.append((buy_idx, len(close) - 1, buy_p, sell_p, ret))

    return trades


def backtest_stock(code, name):
    """对单只股票跑 v1 和 v2 回测"""
    end_date = datetime.now().strftime('%Y%m%d')

    # 获取日线
    df_daily = pro.daily(ts_code=code, start_date='20240801', end_date=end_date)
    if df_daily.empty:
        return None
    df_daily = df_daily.sort_values("trade_date").reset_index(drop=True)

    # 获取资金流
    df_mf = pro.moneyflow(ts_code=code, start_date='20240801', end_date=end_date)
    has_mf = not df_mf.empty
    if has_mf:
        df_mf = df_mf.sort_values("trade_date").reset_index(drop=True)
        df = df_daily.merge(df_mf[['trade_date', 'net_mf_amount']], on='trade_date', how='left')
        df['net_mf_amount'] = df['net_mf_amount'].fillna(0.0)
    else:
        df = df_daily
        df['net_mf_amount'] = 0.0

    close = df['close'].values; high = df['high'].values
    low = df['low'].values; net_mf = df['net_mf_amount'].values
    dates = df['trade_date'].values

    k, d = compute_kdj(high, low, close)

    # v1
    pu1, pd1, pr1, st1 = run_v1(close, high, low, k, d)
    trades1 = simulate_trades(close, st1, pd1, N)

    # v2
    mf_score, mf_dir = compute_mf_signals(net_mf)
    pu2, pd2, pr2, st2 = run_v2(close, high, low, k, d, mf_score, mf_dir)
    trades2 = simulate_trades(close, st2, pd2, N)

    # 计算指标
    def calc_metrics(trades, total_days):
        if not trades:
            return 0, 0, 0, 0, 0, 0
        wins = sum(1 for t in trades if t[4] > 0)
        total = len(trades)
        win_rate = wins / total * 100
        cum_ret = np.prod([1 + t[4] / 100 for t in trades]) - 1
        cum_ret_pct = cum_ret * 100
        avg_ret = np.mean([t[4] for t in trades])
        # 年化 (假设 ~2 年回测期)
        holding_days = total_days
        annual_ret = ((1 + cum_ret) ** (365 / max(holding_days, 1)) - 1) * 100
        return win_rate, cum_ret_pct, avg_ret, annual_ret, wins, total

    total_days = len(close) - N
    m1 = calc_metrics(trades1, total_days)
    m2 = calc_metrics(trades2, total_days)

    # 信号数变化
    buy_sigs_v1 = sum(1 for i in range(N, len(st1)) if st1[i] == 1 and st1[i - 1] != 1)
    buy_sigs_v2 = sum(1 for i in range(N, len(st2)) if st2[i] == 1 and st2[i - 1] != 1)
    sell_sigs_v1 = sum(1 for i in range(N, len(st1))
                       if st1[i] == 3 and pd1[i] > 50 and st1[i - 1] != 3)
    sell_sigs_v2 = sum(1 for i in range(N, len(st2))
                       if st2[i] == 3 and pd2[i] > 50 and st2[i - 1] != 3)

    return {
        'code': code, 'name': name,
        'has_mf': has_mf,
        'trades_v1': len(trades1), 'trades_v2': len(trades2),
        'win_rate_v1': m1[0], 'win_rate_v2': m2[0],
        'cum_ret_v1': m1[1], 'cum_ret_v2': m2[1],
        'avg_ret_v1': m1[2], 'avg_ret_v2': m2[2],
        'annual_v1': m1[3], 'annual_v2': m2[3],
        'wins_v1': m1[4], 'wins_v2': m2[4],
        'buy_sigs_v1': buy_sigs_v1, 'buy_sigs_v2': buy_sigs_v2,
        'sell_sigs_v1': sell_sigs_v1, 'sell_sigs_v2': sell_sigs_v2,
        'prices': close, 'dates': dates,
        'state_v1': st1, 'state_v2': st2,
    }


def main():
    print("=" * 95)
    print("  v1 (纯KDJ) vs v2 (KDJ+资金流) 策略回测对比")
    print("  策略: state→↑买入 / state=↓且P_down>50→卖出")
    print("=" * 95)

    results = []
    for code, name in TEST_STOCKS:
        print(f"\n>> 回测 {name}({code}) ...", end=' ', flush=True)
        r = backtest_stock(code, name)
        if r is None:
            print("数据获取失败")
            continue
        results.append(r)
        mf_tag = "有资金流" if r['has_mf'] else "无资金流"
        print(f"v1={r['trades_v1']}笔 v2={r['trades_v2']}笔 [{mf_tag}]")

    # 汇总表格
    print("\n" + "=" * 95)
    print(f"{'股票':<12} {'资金':<6} {'v1交易':>6} {'v2交易':>6} {'v1胜率':>8} {'v2胜率':>8} {'v1累计':>9} {'v2累计':>9} {'v1年化':>8} {'v2年化':>8}")
    print("-" * 95)

    for r in results:
        mf = "有" if r['has_mf'] else "无"
        print(f"{r['name']:<12} {mf:<6} {r['trades_v1']:>6} {r['trades_v2']:>6} "
              f"{r['win_rate_v1']:>7.1f}% {r['win_rate_v2']:>7.1f}% "
              f"{r['cum_ret_v1']:>8.1f}% {r['cum_ret_v2']:>8.1f}% "
              f"{r['annual_v1']:>7.1f}% {r['annual_v2']:>7.1f}%")

    print("-" * 95)

    # 汇总
    total_t1 = sum(r['trades_v1'] for r in results)
    total_t2 = sum(r['trades_v2'] for r in results)
    avg_wr1 = np.mean([r['win_rate_v1'] for r in results])
    avg_wr2 = np.mean([r['win_rate_v2'] for r in results])

    # 等权组合累计收益
    cum1_all = np.mean([r['cum_ret_v1'] for r in results])
    cum2_all = np.mean([r['cum_ret_v2'] for r in results])

    print(f"{'汇总(等权)':<12} {'':<6} {total_t1:>6} {total_t2:>6} "
          f"{avg_wr1:>7.1f}% {avg_wr2:>7.1f}% "
          f"{cum1_all:>8.1f}% {cum2_all:>8.1f}%")
    print("=" * 95)

    # 有资金流股票 vs 无资金流股票分组
    mf_stocks = [r for r in results if r['has_mf']]
    no_mf_stocks = [r for r in results if not r['has_mf']]

    if mf_stocks:
        cum1_mf = np.mean([r['cum_ret_v1'] for r in mf_stocks])
        cum2_mf = np.mean([r['cum_ret_v2'] for r in mf_stocks])
        wr1_mf = np.mean([r['win_rate_v1'] for r in mf_stocks])
        wr2_mf = np.mean([r['win_rate_v2'] for r in mf_stocks])
        print(f"\n  有资金流股票({len(mf_stocks)}只):")
        print(f"    v1 均累计={cum1_mf:.1f}%  均胜率={wr1_mf:.1f}%")
        print(f"    v2 均累计={cum2_mf:.1f}%  均胜率={wr2_mf:.1f}%")
        delta = cum2_mf - cum1_mf
        print(f"    v2-v1 差值: {delta:+.1f}%  {'✅ v2更优' if delta > 0 else '❌ v1更优' if delta < 0 else '⚖ 持平'}")

    if no_mf_stocks:
        cum1_nm = np.mean([r['cum_ret_v1'] for r in no_mf_stocks])
        cum2_nm = np.mean([r['cum_ret_v2'] for r in no_mf_stocks])
        print(f"\n  无资金流股票({len(no_mf_stocks)}只):")
        print(f"    v1 均累计={cum1_nm:.1f}%  v2 均累计={cum2_nm:.1f}% (应相同)")

    # 逐笔交易明细 (有资金流股票)
    print("\n" + "=" * 95)
    print("  逐笔交易明细 (有资金流股票)")
    print("=" * 95)
    for r in mf_stocks:
        print(f"\n  {r['name']}({r['code']}):")
        # v1 vs v2 状态变化统计
        buy_v1 = r['buy_sigs_v1']; sell_v1 = r['sell_sigs_v1']
        buy_v2 = r['buy_sigs_v2']; sell_v2 = r['sell_sigs_v2']
        print(f"    v1: 买入信号{buy_v1}次  卖出信号{sell_v1}次  → {r['trades_v1']}笔交易")
        print(f"    v2: 买入信号{buy_v2}次  卖出信号{sell_v2}次  → {r['trades_v2']}笔交易")
        # 信号变化
        d_buy = buy_v2 - buy_v1
        d_sell = sell_v2 - sell_v1
        if d_buy != 0 or d_sell != 0:
            print(f"    变化: 买入{'多' if d_buy > 0 else '少'}{abs(d_buy)}次  "
                  f"卖出{'多' if d_sell > 0 else '少'}{abs(d_sell)}次")
        # 交易明细
        print(f"    v1 收益: {[f'{t[4]:+.1f}%' for t in r.get('trades_v1_detail', [])]}")

    print("\n  注: 回测期 2024-08 ~ 2026-06, 约2年")


if __name__ == '__main__':
    main()
