#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块策略回测 (6年 2020-09 ~ 2026-09) —— 状态切换版
=====================================================
6年数据结论修正: 反转只在震荡市(23-25)有效, 趋势/熊市(21-22)大亏。
本回测验证「状态切换」: 持续市(IC>0)追动量, 轮动市(IC<0)做反转, 中性市等权。

策略:
  A 基准        = 全板块等权 buy&hold
  B 纯反转      = 40日跌幅 top5, 一直满仓
  C 纯动量      = 20日涨幅 top5, 一直满仓
  D 状态切换    = 持续市(10日IC>+0.1)持动量 / 轮动市(IC<-0.1)持反转 / 中性等权

用法: python3 backtest_rotation.py
"""

import os
import sys
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import dapan_direction

IC_WINDOW = 10
ROT_THRESHOLD = 0.10
TREND_THRESHOLD = 0.10
TOPN = 5
MOM_WINDOW = 20     # 动量窗口
REV_WINDOW = 40     # 反转窗口


def rank_ic(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    cache = os.path.join(SCRIPT_DIR, 'output', 'sector_ret_cache.csv')
    df = pd.read_csv(cache, index_col=0)
    df.index = df.index.astype(str)
    n_days, n_sec = df.shape
    arr = df.values
    r = arr / 100.0

    # 上证指数 Pu(上涨概率), 用于轮动市反转的斜率过滤
    # 过滤规则: Pu 5日斜率回升(恐慌缓解) 或 Pu 已强势(>60) 才做反转
    sh_path = os.path.join(SCRIPT_DIR, 'output', 'sh_index_daily.csv')
    if os.path.exists(sh_path):
        sh = pd.read_csv(sh_path)
        _, p_up, p_down = dapan_direction.compute_direction(
            sh['close'].values, sh['high'].values, sh['low'].values, sh['vol'].values,
            return_probs=True)
        pu_map = dict(zip(sh['trade_date'].astype(str), p_up))
        pd_map = dict(zip(sh['trade_date'].astype(str), p_down))
        pu = np.array([pu_map.get(td, 50.0) for td in df.index])
        pd_ = np.array([pd_map.get(td, 50.0) for td in df.index])
        slope5 = pu - np.roll(pu, 5)
        slope5[:5] = 0
        rev_filter = (slope5 > 0) | (pu > 60)
        pd_danger = pd_ > 70    # 下降概率>70% → 强制空仓
    else:
        rev_filter = np.ones(n_days, dtype=bool)
        pd_danger = np.zeros(n_days, dtype=bool)
        print('[WARN] 未找到 sh_index_daily.csv, 轮动反转不做过过滤', file=sys.stderr)

    # 轮动/持续状态
    ic_daily = np.full(n_days, np.nan)
    for t in range(1, n_days):
        ic_daily[t] = rank_ic(arr[t], arr[t - 1])
    ic_ma = pd.Series(ic_daily).rolling(IC_WINDOW, min_periods=IC_WINDOW).mean().values
    is_trend = ic_ma > TREND_THRESHOLD      # 持续市(强者恒强)
    is_rot = ic_ma < -ROT_THRESHOLD         # 轮动市(快速切换)
    is_neutral = ~(is_trend | is_rot)       # 中性市

    ret_mom = df.rolling(MOM_WINDOW, min_periods=MOM_WINDOW).sum()
    ret_rev = df.rolling(REV_WINDOW, min_periods=REV_WINDOW).sum()

    full = pd.DataFrame(True, index=df.index, columns=df.columns)

    def pick(mask, sort_col, ascending, topn=TOPN):
        w = np.zeros_like(arr)
        for t in range(n_days):
            row = mask.iloc[t]
            if not row.any():
                continue
            idx = row[row].index
            sel = sort_col.iloc[t].loc[idx].sort_values(ascending=ascending).head(topn).index
            w[t, [df.columns.get_loc(s) for s in sel]] = 1.0 / len(sel)
        return w

    def daily_ret(w):
        # T日尾盘定信号 → T+1日尾盘以收盘价买入 → T+2日享受收益
        # (延迟2天, 规避 T+1 早盘高开低开; shift 2 = 信号生效前空仓1天)
        wp = np.roll(w, 2, axis=0)
        wp[0] = 0.0
        wp[1] = 0.0
        return (wp * r).sum(axis=1)

    w_equal = np.full_like(arr, 1.0 / n_sec)
    w_mom = pick(full, ret_mom, ascending=False)   # 动量: 涨幅 top5
    w_rev = pick(full, ret_rev, ascending=True)    # 反转: 跌幅 top5
    # 状态切换: 持续市动量 + 轮动市反转 + 中性等权
    w_switch = (w_mom * is_trend[:, None] + w_rev * is_rot[:, None]
                + w_equal * is_neutral[:, None])
    # 状态切换(轮动反转加斜率过滤)
    w_switch_f = (w_mom * is_trend[:, None]
                  + w_rev * (is_rot & rev_filter)[:, None]
                  + w_equal * is_neutral[:, None])
    # F: E 策略 + Pd(下降概率)>70% 强制空仓
    w_switch_f2 = w_switch_f * (~pd_danger)[:, None]
    # G: 状态切换 + 斜率过滤 + 中性市0.3pp阈值等权(最优)
    def equal_thresh_daily(th):
        bw = 1.0 / n_sec
        w = np.full(n_sec, bw)
        d = np.zeros(n_days)
        for t in range(n_days):
            d[t] = (w * r[t]).sum()
            w = w * (1 + r[t])
            dp = (bw - w) * 100
            sig = np.where(np.abs(dp) > th)[0]
            w[sig] = bw
        return d
    ret_mom_d = daily_ret(w_mom)
    ret_rev_d = daily_ret(w_rev)
    ret_equal_th = equal_thresh_daily(0.3)
    ret_G = np.zeros(n_days)
    ret_G[is_trend] = ret_mom_d[is_trend]
    ret_G[is_rot & rev_filter] = ret_rev_d[is_rot & rev_filter]
    ret_G[is_neutral] = ret_equal_th[is_neutral]

    strategies = {
        'A 基准·全板块等权buy&hold': (w_equal * r).sum(axis=1),  # 始终满仓, 无信号延迟
        'B 纯反转·40日跌幅top5': daily_ret(w_rev),
        'C 纯动量·20日涨幅top5': daily_ret(w_mom),
        'D 状态切换·持续动量/轮动反转/中性等权': daily_ret(w_switch),
        'E 状态切换·轮动反转加斜率过滤': daily_ret(w_switch_f),
        'F 状态切换·斜率过滤+Pd>70空仓': daily_ret(w_switch_f2),
        'G 状态切换·斜率过滤+中性0.3pp阈值等权': ret_G,
    }

    def perf(name, rr):
        rr = np.asarray(rr)
        nav = np.cumprod(1 + rr)
        total = nav[-1] - 1
        ann = nav[-1] ** (1 / (len(rr) / 244)) - 1
        mdd = (nav / np.maximum.accumulate(nav) - 1).min()
        sharpe = rr.mean() / (rr.std() + 1e-12) * np.sqrt(244)
        posd = int((np.abs(rr) > 1e-12).sum())
        return name, total, ann, mdd, sharpe, posd, nav

    print('=' * 84)
    print(f'板块策略回测(状态切换)  {df.index[0]} → {df.index[-1]}   {n_days}交易日 ≈ {n_days/244:.2f}年')
    print(f'参数: 10日IC>+{TREND_THRESHOLD}=持续市  IC<-{ROT_THRESHOLD}=轮动市  '
          f'动量{MOM_WINDOW}日/反转{REV_WINDOW}日  top{TOPN}')
    print('=' * 84)
    print(f"{'策略':<36}{'总收益':>10}{'年化':>10}{'最大回撤':>10}{'夏普':>8}{'持仓日':>8}")
    print('-' * 84)
    results = {}
    for name, rr in strategies.items():
        res = perf(name, rr)
        results[name] = res
        print(f"{res[0]:<36}{res[1]*100:>+9.1f}%{res[2]*100:>+9.1f}%{res[3]*100:>+9.1f}%{res[4]:>8.2f}{res[5]:>8d}")

    print()
    print(f'状态天数: 持续市 {int(is_trend.sum())} 天 / 轮动市 {int(is_rot.sum())} 天 / '
          f'中性市 {int(is_neutral.sum())} 天')

    # 分年收益
    print()
    print('分年收益对比 (各年复利):')
    years = pd.Series(df.index).str[:4]

    def yearly(rr):
        rr = np.asarray(rr)
        nav = np.cumprod(1 + rr)
        out = {}
        for y in sorted(set(years.values)):
            idx = np.where(years.values == y)[0]
            if len(idx) == 0:
                continue
            s = nav[idx[0] - 1] if idx[0] > 0 else 1.0
            out[y] = nav[idx[-1]] / s - 1
        return out

    yA = yearly(strategies['A 基准·全板块等权buy&hold'])
    yD = yearly(strategies['D 状态切换·持续动量/轮动反转/中性等权'])
    yE = yearly(strategies['E 状态切换·轮动反转加斜率过滤'])
    yG = yearly(strategies['G 状态切换·斜率过滤+中性0.3pp阈值等权'])
    ylist = sorted(set(yA) | set(yD))
    print(f"{'年份':<8}{'A等权':>10}{'E过滤':>10}{'G最优':>10}{'G-A':>10}{'G-E':>10}")
    print('-' * 60)
    for y in ylist:
        a = yA.get(y, 0.0); e = yE.get(y, 0.0); g = yG.get(y, 0.0)
        print(f'{y:<8}{a*100:>+9.1f}%{e*100:>+9.1f}%{g*100:>+9.1f}%{(g-a)*100:>+9.1f}%{(g-e)*100:>+9.1f}%')

    out = pd.DataFrame({'date': df.index,
                        'A_equal_hold': results['A 基准·全板块等权buy&hold'][6],
                        'D_switch': results['D 状态切换·持续动量/轮动反转/中性等权'][6],
                        'E_switch_f': results['E 状态切换·轮动反转加斜率过滤'][6],
                        'G_best': results['G 状态切换·斜率过滤+中性0.3pp阈值等权'][6]})
    out.to_csv(os.path.join(SCRIPT_DIR, 'output', 'backtest_rotation_nav.csv'),
               index=False, encoding='utf-8-sig')
    print(f"\n[CSV] 净值曲线 → output/backtest_rotation_nav.csv")

    # ===== 画净值曲线对比图 =====
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib import font_manager as fm
        for fp in ['/mnt/c/Windows/Fonts/simhei.ttf', '/mnt/c/Windows/Fonts/msyh.ttc']:
            if os.path.exists(fp):
                fm.fontManager.addfont(fp)
        plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
        plt.rcParams['axes.unicode_minus'] = False

        c_bg = '#0d1117'; c_txt = '#e8eaed'; c_sub = '#8b949e'
        dates = pd.to_datetime(out['date'])

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(16, 9), facecolor=c_bg, sharex=True,
            gridspec_kw={'height_ratios': [3, 1], 'hspace': 0.08})

        # 上: 三条净值曲线
        ax1.set_facecolor(c_bg)
        series = [
            ('A_equal_hold', 'A 等权基准(持仓)', '#8b949e', 1.4, ':'),
            ('D_switch', 'D 状态切换', '#e0443a', 1.6, '-'),
            ('E_switch_f', 'E 状态切换+斜率过滤(最优)', '#ffd166', 2.4, '-'),
        ]
        for col, label, color, lw, ls in series:
            ax1.plot(dates, out[col], label=label, color=color, linewidth=lw,
                     linestyle=ls, alpha=0.95)
        ax1.set_ylabel('净值 (1.0 = 本金)', color=c_txt, fontsize=12)
        ax1.legend(loc='upper left', fontsize=11, facecolor='#161b22',
                   edgecolor='#3d444d', labelcolor=c_txt)
        ax1.grid(True, alpha=0.15, color='#333333')
        ax1.tick_params(colors=c_sub, labelsize=10)
        for sp in ax1.spines.values():
            sp.set_color('#3d444d')
        ax1.set_title('板块策略净值对比 (2020-09 ~ 2026-09)', color=c_txt,
                      fontsize=15, fontweight='bold', loc='left', pad=10)

        # 下: E 相对 A 的超额累计
        ax2.set_facecolor(c_bg)
        excess = (out['E_switch_f'] / out['A_equal_hold'] - 1) * 100
        ax2.plot(dates, excess, color='#ffd166', linewidth=1.6)
        ax2.axhline(0, color='#8b949e', linewidth=0.8, alpha=0.6)
        ax2.fill_between(dates, excess, 0, where=(excess >= 0),
                         color='#ffd166', alpha=0.15)
        ax2.fill_between(dates, excess, 0, where=(excess < 0),
                         color='#21a05f', alpha=0.15)
        ax2.set_ylabel('超额 E/A-1 (%)', color=c_txt, fontsize=12)
        ax2.grid(True, alpha=0.15, color='#333333')
        ax2.tick_params(colors=c_sub, labelsize=10)
        for sp in ax2.spines.values():
            sp.set_color('#3d444d')
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

        png = os.path.join(SCRIPT_DIR, 'output', 'backtest_rotation_curve.png')
        fig.savefig(png, dpi=150, facecolor=c_bg, bbox_inches='tight')
        plt.close(fig)
        print(f'[图表] {png}')
    except Exception as e:
        print(f'[图表] 画图失败: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
