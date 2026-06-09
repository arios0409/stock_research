#!/usr/bin/env python3
"""
大盘趋势扫描 v2 — KDJ概率趋势 + 北向资金共振
在 dapan_scan_auto.py 基础上加入：
  1. 北向资金趋势 — 近5/10/20日累计净流入方向
  2. 资金共振加分 — KDJ上升 + 北向流入 → P_up 加权
  3. 资金背离预警 — 指数涨但北向流出 → 风险提示
  4. 图表第五栏 — 北向资金净流入柱状图

用法:
  cd /mnt/d/Hermes_workspace/stock_research
  source .venv/bin/activate
  python 5.Individual_stock_trend/dapan_v2.py
  python 5.Individual_stock_trend/dapan_v2.py --save-chart
  python 5.Individual_stock_trend/dapan_v2.py --backtest 2023,2024,2025
"""

import sys, os, argparse
from datetime import datetime
import tushare as ts
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates

TUSHARE_TOKEN="0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
N, M1, M2 = 14, 5, 3
MF_WEIGHTS = {5: 0.50, 10: 0.30, 20: 0.20}
MF_RESONANCE_BOOST = 10
MF_DIVERGENCE_PENALTY = 8
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

for fp in ['/mnt/c/Windows/Fonts/simhei.ttf', '/mnt/c/Windows/Fonts/msyh.ttc']:
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)
plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
plt.rcParams['axes.unicode_minus'] = False


def fetch_data(start_date, end_date):
    """拉取上证指数 + 北向资金"""
    pro = ts.pro_api(TUSHARE_TOKEN)

    # 指数日线
    df_idx = pro.index_daily(ts_code="000001.SH", start_date=start_date, end_date=end_date)
    df_idx = df_idx.sort_values("trade_date").reset_index(drop=True)

    # 北向资金
    df_north = pro.moneyflow_hsgt(start_date=start_date, end_date=end_date)
    df_north = df_north.sort_values("trade_date").reset_index(drop=True)

    # 计算每日北向净流入
    df_north['north_net'] = pd.to_numeric(df_north['north_money'], errors='coerce').diff().fillna(0)

    # 对齐
    df = df_idx.merge(df_north[['trade_date', 'north_net']], on='trade_date', how='left')
    df['north_net'] = df['north_net'].fillna(0.0)

    return df, len(df_north) > 0


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


def compute_north_signals(north_net):
    """北向资金信号"""
    n = len(north_net)
    cum5 = np.zeros(n); cum10 = np.zeros(n); cum20 = np.zeros(n)
    score = np.zeros(n); direction = np.zeros(n, dtype=int)

    for i in range(n):
        s5 = max(0, i - 4); s10 = max(0, i - 9); s20 = max(0, i - 19)
        cum5[i] = np.sum(north_net[s5:i + 1])
        cum10[i] = np.sum(north_net[s10:i + 1])
        cum20[i] = np.sum(north_net[s20:i + 1])

        # 以亿为单位评分
        sc5 = np.clip(cum5[i] / 50, -10, 10) * MF_WEIGHTS[5] * 10
        sc10 = np.clip(cum10[i] / 100, -10, 10) * MF_WEIGHTS[10] * 10
        sc20 = np.clip(cum20[i] / 200, -10, 10) * MF_WEIGHTS[20] * 10
        score[i] = np.clip(sc5 + sc10 + sc20, -100, 100)
        if score[i] > 15: direction[i] = 1
        elif score[i] < -15: direction[i] = -1
    return cum5, cum10, cum20, score, direction


def run_v1(close, high, low, k, d):
    """纯KDJ (v1)"""
    return run_system(close, high, low, k, d, None, None)


def run_v2(close, high, low, k, d, north_score, north_dir):
    """KDJ + 北向 (v2)"""
    return run_system(close, high, low, k, d, north_score, north_dir)


def run_system(close, high, low, k, d, mf_score, mf_dir):
    n = len(close)
    p_up = np.full(n, 50.0); p_down = np.full(n, 50.0); p_risk = np.full(n, 50.0)
    state = np.full(n, 0, dtype=int)
    up_days = down_days = risk_days = 0
    has_mf = mf_score is not None

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

        # P_up 原始
        if k[i] > d[i]:
            pu_raw = 80 if low_golden_bonus else (60 if is_golden else min(60 + up_days * 5, 92))
        else:
            pu_raw = 30 if is_death else max(prev_up - (down_days * 8 if down_days > 0 else 3), 10)

        # 资金共振调整
        if has_mf:
            close_5d = close[max(0, i - 5)]
            pct_5d = (close[i] - close_5d) / close_5d * 100 if close_5d > 0 else 0
            if pct_5d > 2 and mf_score[i] < -20:
                pu = max(pu_raw - MF_DIVERGENCE_PENALTY, 5)
            elif pct_5d < -2 and mf_score[i] > 20:
                pu = min(pu_raw + MF_DIVERGENCE_PENALTY, 95)
            elif k[i] > d[i] and mf_dir[i] == 1:
                boost = min(abs(mf_score[i]) / 100 * MF_RESONANCE_BOOST, MF_RESONANCE_BOOST)
                pu = min(pu_raw + boost, 95)
            elif k[i] < d[i] and mf_dir[i] == -1:
                penalty = min(abs(mf_score[i]) / 100 * MF_RESONANCE_BOOST, MF_RESONANCE_BOOST)
                pu = max(pu_raw - penalty, 5)
            else:
                pu = pu_raw
        else:
            pu = pu_raw
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


def simulate(close, state, p_down):
    trades = []; in_pos = False; bi = None
    for i in range(N, len(close)):
        s = state[i]
        if not in_pos:
            if s == 1: bi = i; in_pos = True
        else:
            if s == 3 and p_down[i] > 50:
                trades.append((bi, i, close[bi], close[i], (close[i] - close[bi]) / close[bi] * 100))
                in_pos = False
    if in_pos:
        trades.append((bi, len(close) - 1, close[bi], close[-1], (close[-1] - close[bi]) / close[bi] * 100))
    return trades


def bh_ret(close):
    return (close[-1] - close[0]) / close[0] * 100


def main():
    parser = argparse.ArgumentParser(description='大盘趋势 v2 (KDJ+北向)')
    parser.add_argument('--save-chart', action='store_true')
    parser.add_argument('--backtest', type=str, default='',
                        help='回测年份, 逗号分隔, 如 2023,2024,2025')
    parser.add_argument('--no-chart', action='store_true')
    args = parser.parse_args()

    end_date = datetime.now().strftime('%Y%m%d')
    start_date = '20220101'
    if args.backtest:
        years = [int(y.strip()) for y in args.backtest.split(',')]
        # 回测期需要覆盖最早年份的前一年(KDJ预热)
        min_year = min(years)
        start_date = f'{min_year - 1}0101'

    print(f"拉取数据 ({start_date} ~ {end_date}) ...")
    df, has_north = fetch_data(start_date, end_date)
    print(f"  指数 {len(df)} 条  北向 {'有数据' if has_north else '无数据'}")

    close = df['close'].values; high = df['high'].values
    low = df['low'].values; north_net = df['north_net'].values
    dates = pd.to_datetime(df['trade_date']).values

    k, d = compute_kdj(high, low, close)

    if has_north:
        nc5, nc10, nc20, ns, nd = compute_north_signals(north_net)
    else:
        nc5 = nc10 = nc20 = ns = nd = None

    # 如果指定了回测
    if args.backtest:
        df['year'] = pd.to_datetime(df['trade_date']).dt.year
        years = [int(y.strip()) for y in args.backtest.split(',')]

        print(f"\n{'='*80}")
        print(f"  上证指数 v1 vs v2 年度回测对比")
        print(f"  策略: state→↑买入 / state=↓且P_down>50→卖出")
        print(f"{'='*80}")
        print(f"{'年份':<8} {'持有':>8} {'v1收益':>9} {'v2收益':>9} {'v1胜率':>7} {'v2胜率':>7} {'判定':>10}")
        print(f"{'-'*80}")

        all_v1 = []; all_v2 = []
        for year in years:
            mask = df['year'] == year
            idxs = np.where(mask.values)[0]
            if len(idxs) == 0: continue
            s, e = idxs[0], idxs[-1]
            c = close[s:e + 1]; h = high[s:e + 1]; l = low[s:e + 1]
            kk = k[s:e + 1]; dd = d[s:e + 1]

            _, _, _, st1 = run_v1(c, h, l, kk, dd)
            tr1 = simulate(c, st1, run_v1(c, h, l, kk, dd)[1])

            if has_north:
                nss = ns[s:e + 1] if ns is not None else None
                ndd = nd[s:e + 1] if nd is not None else None
                _, _, _, st2 = run_v2(c, h, l, kk, dd, nss, ndd)
                tr2 = simulate(c, st2, run_v2(c, h, l, kk, dd, nss, ndd)[1])
            else:
                st2 = st1; tr2 = tr1

            bh = bh_ret(c)
            cum1 = np.prod([1 + t[4] / 100 for t in tr1]) - 1 if tr1 else 0
            cum2 = np.prod([1 + t[4] / 100 for t in tr2]) - 1 if tr2 else 0
            w1 = sum(1 for t in tr1 if t[4] > 0)
            w2 = sum(1 for t in tr2 if t[4] > 0)
            wr1 = w1 / len(tr1) * 100 if tr1 else 0
            wr2 = w2 / len(tr2) * 100 if tr2 else 0

            delta = cum2 * 100 - cum1 * 100
            judge = "✅ v2更优" if delta > 0.5 else ("❌ v1更优" if delta < -0.5 else "⚖持平")
            print(f"  {year}   {bh:>7.1f}%  {cum1*100:>8.1f}%  {cum2*100:>8.1f}%  "
                  f"{wr1:>6.1f}%  {wr2:>6.1f}%  {judge}")

            all_v1.extend(tr1); all_v2.extend(tr2)

        print(f"{'-'*80}")
        wr1_all = sum(1 for t in all_v1 if t[4] > 0) / len(all_v1) * 100 if all_v1 else 0
        wr2_all = sum(1 for t in all_v2 if t[4] > 0) / len(all_v2) * 100 if all_v2 else 0
        print(f"  合计  {'':>8} {'':>9} {'':>9} {wr1_all:>6.1f}%  {wr2_all:>6.1f}%  "
              f"v1={len(all_v1)}笔 v2={len(all_v2)}笔")

        # 交易明细对比
        print(f"\n{'='*80}")
        print(f"  逐笔交易对比 (有差异的年份)")
        for year in years:
            mask = df['year'] == year
            idxs = np.where(mask.values)[0]
            if len(idxs) == 0: continue
            s, e = idxs[0], idxs[-1]
            c = close[s:e + 1]; h = high[s:e + 1]; l = low[s:e + 1]
            kk = k[s:e + 1]; dd = d[s:e + 1]
            _, _, _, st1 = run_v1(c, h, l, kk, dd)
            tr1 = simulate(c, st1, run_v1(c, h, l, kk, dd)[1])
            _, _, _, st2 = run_v2(c, h, l, kk, dd, ns[s:e + 1], nd[s:e + 1])
            tr2 = simulate(c, st2, run_v2(c, h, l, kk, dd, ns[s:e + 1], nd[s:e + 1])[1])

            rets1 = [f'{t[4]:+.2f}%' for t in tr1]
            rets2 = [f'{t[4]:+.2f}%' for t in tr2]
            if rets1 != rets2:
                print(f"\n  {year}年:")
                print(f"    v1({len(tr1)}笔): {rets1}")
                print(f"    v2({len(tr2)}笔): {rets2}")

        print(f"\n  ⚠ 北向资金数据从 2023-11 左右开始有完整记录")

    # 当前分析 (非回测模式时)
    if not args.backtest:
        pu1, pd1, pr1, st1 = run_v1(close, high, low, k, d)
        pu2, pd2, pr2, st2 = run_v2(close, high, low, k, d, ns, nd)

        last = len(close) - 1
        sn = {0: "—", 1: "↑上升", 2: "△风险", 3: "↓下降"}
        cur_north = north_net[last] / 1e4 if has_north else 0
        nc5_val = nc5[last] / 1e4 if has_north else 0
        nc20_val = nc20[last] / 1e4 if has_north else 0
        ns_val = ns[last] if has_north else 0

        print(f"\n{'='*70}")
        print(f"  上证指数 KDJ概率趋势 v2 (含北向资金)")
        print(f"  {pd.Timestamp(dates[-1]).strftime('%Y-%m-%d')}  收盘 {close[-1]:.2f}")
        print(f"{'='*70}")
        print(f"  v1: 状态 {sn[st1[last]]}  P_up={pu1[last]:.0f}%  P_down={pd1[last]:.0f}%  P_risk={pr1[last]:.0f}%")
        print(f"  v2: 状态 {sn[st2[last]]}  P_up={pu2[last]:.0f}%  P_down={pd2[last]:.0f}%  P_risk={pr2[last]:.0f}%")
        if has_north:
            print(f"  北向: 今日 {cur_north:+.2f}亿  近5日 {nc5_val:+.2f}亿  近20日 {nc20_val:+.2f}亿  评分 {ns_val:+.0f}")
            if nd[last] == 1: print(f"  方向: 🔴 北向持续流入")
            elif nd[last] == -1: print(f"  方向: 🟢 北向持续流出")
            else: print(f"  方向: ⚪ 中性")
            # 共振/背离
            if st2[last] == 1 and nd[last] == 1:
                boost = pu2[last] - pu1[last]
                print(f"  🔥 共振: KDJ上升 + 北向流入 (P_up +{boost:.0f})")
            elif st2[last] == 3 and nd[last] == -1:
                penalty = pu1[last] - pu2[last]
                print(f"  ❄ 双杀: KDJ下降 + 北向流出 (P_up -{penalty:.0f})")
            elif st2[last] == 1 and nd[last] == -1:
                print(f"  ⚠ 背离: KDJ看多但北向在出")
            elif st2[last] == 3 and nd[last] == 1:
                print(f"  💎 底背离: KDJ看空但北向在吸筹")
        print(f"{'='*70}")

        if not args.no_chart and has_north:
            generate_chart(dates, close, high, low, k, d,
                          pu1, pd1, pr1, st1,
                          pu2, st2, north_net, ns, nd, nc5)

    return 0


def generate_chart(dates, close, high, low, k, d,
                   pu1, pd1, pr1, st1,
                   pu2, st2, north_net, ns, nd, nc5):
    c_bg = '#0d1117'; c_ax = '#161b22'
    c_up = '#00ff00'; c_risk = '#ffff00'; c_down = '#ff0000'
    c_price = '#ffffff'; c_k = '#ff9900'; c_d = '#33ddff'; c_j = '#dd88ff'
    c_grid = '#333333'; c_label = '#dddddd'
    c_mf_in = '#ff4444'; c_mf_out = '#00ff88'
    sn = {0: "—", 1: "↑上升", 2: "△风险", 3: "↓下降"}
    sc = {0: c_label, 1: c_up, 2: c_risk, 3: c_down}

    M4 = 80; m4 = max(N, len(close) - M4)
    d4 = dates[m4:]; c4 = close[m4:]; st4 = st2[m4:]

    fig = plt.figure(figsize=(20, 18), facecolor=c_bg)
    ax1 = fig.add_axes([0.07, 0.63, 0.90, 0.35], facecolor=c_ax)
    ax2 = fig.add_axes([0.07, 0.48, 0.90, 0.13], facecolor=c_ax)
    ax3 = fig.add_axes([0.07, 0.35, 0.90, 0.11], facecolor=c_ax)
    ax5 = fig.add_axes([0.07, 0.22, 0.90, 0.11], facecolor=c_ax)  # 北向
    ax4 = fig.add_axes([0.07, 0.02, 0.90, 0.18], facecolor=c_ax)

    FMT = lambda: mdates.DateFormatter('Y%yM%m')

    def draw_spans(ax, da, ca, sa, pua, pda, pra, show_label=True, yt=0):
        ax.plot(da, ca, color=c_price, linewidth=1.6, alpha=0.95)
        i = 0
        while i < len(ca):
            if sa[i] == 0: i += 1; continue
            s = sa[i]; j = i
            while j < len(ca) and sa[j] == s: j += 1
            for idx in range(i, j):
                pv = (pua[idx] if s == 1 else (pra[idx] if s == 2 else pda[idx]))
                alpha = 0.10 + (pv - 50) / 40 * 0.38 if pv > 50 else 0.06
                alpha = max(0.06, min(0.55, alpha))
                if idx < len(ca) - 1:
                    ax.axvspan(da[idx], da[idx + 1], alpha=alpha, color=sc[s], linewidth=0, zorder=0)
            if show_label and yt:
                avg = np.mean(pua[i:j] if s == 1 else (pra[i:j] if s == 2 else pda[i:j]))
                mid = i + (j - i) // 2
                if mid < len(ca):
                    ax.text(da[mid], yt, f"{sn[s]} {avg:.0f}%", color=sc[s], fontsize=8,
                            fontweight='bold', ha='center', va='top',
                            bbox=dict(boxstyle='round,pad=0.15', facecolor=c_bg, edgecolor=sc[s], alpha=0.8))
            i = j

    # 面板1
    y1r = np.max(close) - np.min(close)
    yt1 = np.max(close) + y1r * 0.065
    draw_spans(ax1, dates, close, st2, pu2, pr1, pr1, True, yt1)
    ax1.set_ylim(np.min(close) - y1r * 0.10, np.max(close) + y1r * 0.15)
    ax1.set_ylabel('上证指数 v2', color=c_label, fontsize=18)
    ax1.tick_params(colors=c_label, labelsize=13)
    ax1.grid(True, alpha=0.08, color=c_grid)
    ax1.set_xlim(dates[0], dates[-1]); ax1.set_xticklabels([])

    # 面板2: KDJ
    ax2.plot(dates, k, color=c_k, linewidth=1.5, alpha=0.9)
    ax2.plot(dates, d, color=c_d, linewidth=1.5, alpha=0.9)
    ax2.plot(dates, 3*k-2*d, color=c_j, linewidth=0.8, alpha=0.5)
    ax2.axhline(y=85, color=c_risk, linestyle='--', alpha=0.4)
    ax2.axhline(y=35, color=c_down, linestyle='--', alpha=0.4)
    ax2.text(dates[-1], 86, '超买85', color='#ffee00', fontsize=8, alpha=0.6)
    ax2.text(dates[-1], 33, '危险35', color=c_down, fontsize=8, alpha=0.6)
    ax2.set_ylabel('KDJ', color=c_label, fontsize=14)
    ax2.tick_params(colors=c_label, labelsize=11)
    ax2.grid(True, alpha=0.12, color=c_grid)
    ax2.set_ylim(-10, 115); ax2.set_xlim(dates[0], dates[-1])
    ax2.set_xticklabels([])

    # 面板3: 成交量
    vol = df['vol'].values if 'vol' in dir() else np.ones(len(close))
    ax3.bar(dates, vol / 1e8, color=[c_up if close[i] >= opens[i] else c_down for i in range(len(close))],
            alpha=0.5, width=0.7)
    ax3.set_ylabel('成交量(亿手)', color=c_label, fontsize=13)
    ax3.tick_params(colors=c_label, labelsize=10)
    ax3.grid(True, alpha=0.1, color=c_grid)
    ax3.set_xlim(dates[0], dates[-1]); ax3.set_xticklabels([])

    # 面板4: 北向资金
    nc = [c_mf_in if north_net[i] >= 0 else c_mf_out for i in range(len(north_net))]
    ax5.bar(dates, north_net / 1e4, color=nc, alpha=0.7, width=0.7)
    ax5.axhline(y=0, color=c_label, linewidth=0.8, alpha=0.4)
    ax5.set_ylabel('北向净流入(亿)', color=c_label, fontsize=13)
    ax5.tick_params(colors=c_label, labelsize=10)
    ax5.grid(True, alpha=0.1, color=c_grid)
    ax5.set_xlim(dates[0], dates[-1])
    ax5.text(dates[0], ax5.get_ylim()[1] * 0.05, '红=流入  绿=流出', color=c_label, fontsize=8, alpha=0.4)
    ax5.xaxis.set_major_formatter(FMT()); ax5.xaxis.set_major_locator(mdates.MonthLocator(interval=1))

    for ax in [ax1, ax2, ax3]:
        ax.set_xlim(dates[0], dates[-1])
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        ax.xaxis.set_major_formatter(FMT())

    # 面板5: 近4月
    draw_spans(ax4, d4, c4, st4, pu2[m4:], pr1[m4:], pr1[m4:], True,
               np.max(c4) + (np.max(c4) - np.min(c4)) * 0.06)
    yr = np.max(c4) - np.min(c4)
    ax4.set_ylim(np.min(c4) - yr * 0.10, np.max(c4) + yr * 0.10)
    ax4.set_ylabel('近4月', color=c_label, fontsize=13)
    ax4.tick_params(colors=c_label, labelsize=10)
    ax4.grid(True, alpha=0.08, color=c_grid)
    ax4.set_xlim(d4[0], d4[-1])
    ax4.xaxis.set_major_formatter(FMT()); ax4.xaxis.set_major_locator(mdates.MonthLocator(interval=1))

    end_date = datetime.now().strftime('%Y%m%d')
    path = os.path.join(OUTPUT_DIR, f'v2_dapan_{end_date}.png')
    fig.savefig(path, dpi=150, facecolor=c_bg)
    plt.close(fig)
    print(f"  图表: {path}")


if __name__ == '__main__':
    main()
