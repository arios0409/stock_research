#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大盘策略状态图：上证指数走势 + 每日策略状态颜色标注
颜色: 持仓=蓝, 追动量=绿, 空仓=红, 做反转=紫
"""
import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from matplotlib import font_manager as fm
for _fp in ['/mnt/c/Windows/Fonts/simhei.ttf', '/mnt/c/Windows/Fonts/msyh.ttc']:
    if os.path.exists(_fp):
        fm.fontManager.addfont(_fp)
plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
plt.rcParams['axes.unicode_minus'] = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')
sys.path.insert(0, SCRIPT_DIR)
import dapan_direction

IC_WINDOW = 10
ROT_THRESHOLD = 0.10
TREND_THRESHOLD = 0.10
SLOPE_WINDOW = 5
PU_LEVEL = 60

# 状态颜色
COLORS = {
    '持仓': '#4472C4',    # 蓝
    '追动量': '#2ecc71',  # 绿
    '空仓': '#e0443a',    # 红
    '做反转': '#9b59b6',  # 紫
}


def rank_ic(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    # ===== 1. 上证 Pu/Pd =====
    sh = pd.read_csv(os.path.join(OUT_DIR, 'sh_index_daily.csv'))
    sh['trade_date'] = sh['trade_date'].astype(str)
    _, p_up, p_down = dapan_direction.compute_direction(
        sh['close'].values, sh['high'].values, sh['low'].values, sh['vol'].values,
        return_probs=True)
    sh['pu'] = p_up

    # ===== 2. 板块 10日IC =====
    ret = pd.read_csv(os.path.join(OUT_DIR, 'sector_ret_cache.csv'), index_col=0)
    ret.index = ret.index.astype(str)
    arr = ret.values
    n = len(arr)
    ic = np.full(n, np.nan)
    for t in range(1, n):
        ic[t] = rank_ic(arr[t], arr[t - 1])
    ic_ma = pd.Series(ic).rolling(IC_WINDOW, min_periods=IC_WINDOW).mean().values
    ic_map = dict(zip(ret.index, ic_ma))

    # ===== 3. 逐日状态 =====
    dates = []
    closes = []
    states = []
    for i in range(len(sh)):
        td = sh['trade_date'].iloc[i]
        if td < '20250101':
            continue
        pu = sh['pu'].iloc[i]
        slope = pu - sh['pu'].iloc[i - SLOPE_WINDOW] if i >= SLOPE_WINDOW else np.nan
        cur_ic = ic_map.get(td, np.nan)
        if np.isnan(cur_ic):
            continue
        is_trend = cur_ic > TREND_THRESHOLD
        is_rot = cur_ic < -ROT_THRESHOLD
        if is_trend:
            st = '追动量'
        elif is_rot:
            rev_pass = (slope > 0) or (pu > PU_LEVEL) if not np.isnan(slope) else False
            st = '做反转' if rev_pass else '空仓'
        else:
            st = '持仓'
        dates.append(pd.to_datetime(td))
        closes.append(sh['close'].iloc[i])
        states.append(st)

    dates = np.array(dates)
    closes = np.array(closes)
    states = np.array(states)

    # ===== 4. 画图 =====
    c_bg = '#0d1117'
    c_txt = '#c9d1d9'
    c_grid = '#21262d'
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 7), sharex=True,
                                   gridspec_kw={'height_ratios': [5, 1]}, facecolor=c_bg)
    fig.subplots_adjust(hspace=0.05)

    # 上面板: 上证走势
    ax1.set_facecolor(c_bg)
    ax1.plot(dates, closes, color='#e6edf3', linewidth=1.3, zorder=3)
    ax1.fill_between(dates, closes.min(), closes, color='#e6edf3', alpha=0.06, zorder=1)
    ax1.set_title('上证指数走势 × 每日策略状态（2025-01 ~ 2026-09）', color=c_txt,
                  fontsize=15, fontweight='bold', pad=12, loc='left')
    ax1.set_ylabel('上证指数', color=c_txt, fontsize=11)
    ax1.tick_params(colors=c_txt, labelsize=10)
    for sp in ['top', 'right']:
        ax1.spines[sp].set_visible(False)
    for sp in ['bottom', 'left']:
        ax1.spines[sp].set_color(c_grid)
    ax1.grid(True, color=c_grid, linewidth=0.5, alpha=0.6)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:,.0f}'))

    # 下面板: 状态颜色条
    ax2.set_facecolor(c_bg)
    state_code = {'持仓': 0, '追动量': 1, '空仓': 2, '做反转': 3}
    codes = np.array([state_code[s] for s in states])
    # 用 pcolormesh 画 1×N 颜色条
    cmap = matplotlib.colors.ListedColormap(
        [COLORS['持仓'], COLORS['追动量'], COLORS['空仓'], COLORS['做反转']])
    # 扩展日期边界
    if len(dates) > 1:
        d_edges = np.concatenate([dates, [dates[-1] + pd.Timedelta(days=1)]])
    else:
        d_edges = dates
    X, Y = np.meshgrid(d_edges, [0, 1])
    Z = codes.reshape(1, -1)
    ax2.pcolormesh(X, Y, Z, cmap=cmap, vmin=0, vmax=3, shading='flat')
    ax2.set_yticks([])
    ax2.set_ylabel('状态', color=c_txt, fontsize=11)
    for sp in ['top', 'right', 'left']:
        ax2.spines[sp].set_visible(False)
    ax2.spines['bottom'].set_color(c_grid)
    ax2.tick_params(colors=c_txt, labelsize=10)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))

    # 图例
    from matplotlib.patches import Patch
    legend_handles = [Patch(facecolor=COLORS[k], label=k) for k in ['持仓', '追动量', '空仓', '做反转']]
    ax1.legend(handles=legend_handles, loc='upper left', facecolor=c_bg, edgecolor=c_grid,
               labelcolor=c_txt, fontsize=10, ncol=4)

    out = os.path.join(OUT_DIR, '大盘策略状态图.png')
    fig.savefig(out, dpi=150, facecolor=c_bg, bbox_inches='tight')
    plt.close(fig)
    print(f'[图表] {out}')

    # 状态统计
    from collections import Counter
    cnt = Counter(states)
    print('状态分布:', dict(cnt))


if __name__ == '__main__':
    main()
