#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轮动市板块分类 (第2步): 已涨 vs 未涨
======================================
在轮动市里, 找出「已经涨过」的板块(资金炒过) 和「还没涨」的板块(下一个轮动目标)。

判定流程:
  1. 10日 IC < -阈值 → 确认轮动市
  2. 按 20日涨幅的 RPS(百分位) 分档:
       RPS ≥ 70 → 已涨 (强势, 资金已炒过)
       RPS ≤ 30 → 未涨 (弱势, 还没轮到)

辅助判断:
  已涨板块里「5日转跌」→ 涨完回落 (第4步对象, 可能重新轮动)
  未涨板块里「5日转涨」→ 低位启动 (第3步对象, 待启动)

数据源: rotation_regime.py 生成的 output/sector_ret_cache.csv
用法: python3 rotation_sector_scan.py
"""

import os
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== 参数 =====
IC_WINDOW = 10        # 轮动判定窗口
ROT_THRESHOLD = 0.10  # 轮动阈值
RPS_TOP = 70          # RPS ≥ 70 = 已涨
RPS_BOTTOM = 30       # RPS ≤ 30 = 未涨
RET_DAYS = 20         # 判断已涨/未涨的涨幅窗口
POS_LOW = 40          # 区间位置 < 40 = 低位(区间下40%)
DD_LOW = -12          # 回撤 < -12% = 明显回调


def rank_ic(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    cache_path = os.path.join(SCRIPT_DIR, 'output', 'sector_ret_cache.csv')
    if not os.path.exists(cache_path):
        print('[FATAL] 未找到缓存, 请先运行 rotation_regime.py 生成')
        return
    ret_df = pd.read_csv(cache_path, index_col=0)
    ret_df.index = ret_df.index.astype(str)

    # 1. 算 10日 IC
    arr = ret_df.values
    ic_daily = np.full(len(ret_df), np.nan)
    for t in range(1, len(ret_df)):
        if not np.isnan(arr[t]).all() and not np.isnan(arr[t - 1]).all():
            ic_daily[t] = rank_ic(arr[t], arr[t - 1])
    ic_ma = pd.Series(ic_daily).rolling(IC_WINDOW, min_periods=IC_WINDOW).mean().values

    last_day = ret_df.index[-1]
    cur_ic = ic_ma[-1]
    is_rot = cur_ic < -ROT_THRESHOLD
    is_trd = cur_ic > ROT_THRESHOLD
    state = '轮动市' if is_rot else ('持续市' if is_trd else '中性')

    # 2. 板块近期涨幅 (简单相加累计)
    ret5 = ret_df.iloc[-5:].sum(axis=0)
    ret10 = ret_df.iloc[-10:].sum(axis=0)
    ret20 = ret_df.iloc[-RET_DAYS:].sum(axis=0)

    # 3. RPS (20日涨幅百分位)
    rps20 = ret20.rank(pct=True) * 100

    # 4. 低位指标 (不用KDJ, 用区间位置 + 回撤)
    cum = (1 + ret_df / 100).cumprod()   # 累计收益曲线(归一化, 起点1.0)
    win = cum.iloc[-250:]                # 近250日(约1年)窗口
    win_min = win.min(axis=0)
    win_max = win.max(axis=0)
    cur = cum.iloc[-1]
    pos = (cur - win_min) / (win_max - win_min) * 100  # 区间位置 0-100
    dd = (cur / win_max - 1) * 100                      # 从高点回撤% (负值)

    df = pd.DataFrame({'ret5': ret5, 'ret10': ret10, 'ret20': ret20, 'rps20': rps20,
                       'pos': pos, 'dd': dd})
    df = df.sort_values('ret20', ascending=False)

    # 4. 输出
    print()
    print('=' * 72)
    print(f'轮动市板块分类  @ {last_day}  (10日IC={cur_ic:+.3f} → {state})')
    print('=' * 72)
    if not is_rot:
        print(f'⚠ 当前不是轮动市({state})，"已涨/未涨"分类只在轮动市有意义')
        print()

    hdr = f"{'排名':<4}{'行业':<10}{'20日涨幅':>10}{'RPS20':>8}{'10日涨幅':>10}{'5日涨幅':>10}"

    top = df[df['rps20'] >= RPS_TOP]
    print()
    print(f'【已涨板块】20日涨幅 RPS ≥ {RPS_TOP} (资金已炒过)')
    print('-' * 72)
    print(hdr)
    for i, (idx, r) in enumerate(top.iterrows(), 1):
        note = '  ← 5日转跌，已开始回落' if r['ret5'] < 0 else ''
        print(f"{i:<4}{idx:<10}{r['ret20']:>+9.1f}%{r['rps20']:>7.1f}{r['ret10']:>+9.1f}%"
              f"{r['ret5']:>+9.1f}%{note}")

    bot = df[df['rps20'] <= RPS_BOTTOM].sort_values('pos')  # 按区间位置升序(低位在前)
    print()
    print(f'【未涨板块】20日涨幅 RPS ≤ {RPS_BOTTOM} (还没轮到, 按区间位置排序)')
    print('-' * 72)
    print(f"{'排名':<4}{'行业':<10}{'20日涨幅':>10}{'区间位置':>10}{'回撤':>10}{'5日涨幅':>10}")
    for i, (idx, r) in enumerate(bot.iterrows(), 1):
        low = '  ⭐低位' if (r['pos'] < POS_LOW and r['dd'] < DD_LOW) else ''
        note = '  5日转涨' if r['ret5'] > 0 else ''
        print(f"{i:<4}{idx:<10}{r['ret20']:>+9.1f}%{r['pos']:>9.0f}{r['dd']:>+9.1f}%"
              f"{r['ret5']:>+9.1f}%{low}{note}")

    print()
    print('说明: 已涨板块里「5日转跌」→ 第4步对象(可能重新轮动)')
    print('      未涨板块里「区间位置低+回撤深」= ⭐低位 → 第3步埋伏对象')
    print('      区间位置=近1年累计收益的百分位(0-100), 回撤=距近1年高点的跌幅')

    # 5. 保存 CSV
    outdir = os.path.join(SCRIPT_DIR, 'output')
    os.makedirs(outdir, exist_ok=True)
    csv = os.path.join(outdir, f'sector_classify_{last_day}.csv')
    df_out = df.copy()
    df_out.insert(0, '方向', df_out['rps20'].map(
        lambda x: '已涨' if x >= RPS_TOP else ('未涨' if x <= RPS_BOTTOM else '中性')))
    df_out.to_csv(csv, encoding='utf-8-sig')
    print(f'[CSV] {csv}')


if __name__ == '__main__':
    main()
