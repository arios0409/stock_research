#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块级别 V6 斜率信号回测
对 29 个申万一级行业, 用大盘扫描 V6 斜率信号 (Pu 5日斜率>0 或 Pu>60 = 持有, 否则空仓) 做择时,
对比 2020-2026 Buy&Hold, 验证方法是否在板块上通用。
"""
import os
import sys
import pickle
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')
sys.path.insert(0, SCRIPT_DIR)
import dapan_direction

SLOPE_WINDOW = 5
PU_LEVEL = 60


def main():
    with open(os.path.join(OUT_DIR, 'sector_ohlcv.pkl'), 'rb') as f:
        sector_ohlcv = pickle.load(f)

    print(f'板块数: {len(sector_ohlcv)}')
    # 取公共日期 (以第一个行业为准)
    any_sec = list(sector_ohlcv.keys())[0]
    dates = list(sector_ohlcv[any_sec].index)
    print(f'日期: {dates[0]} ~ {dates[-1]} 共 {len(dates)} 天')

    results = []
    for sec in sorted(sector_ohlcv.keys()):
        df = sector_ohlcv[sec].dropna()
        if len(df) < 60:
            continue
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        vol = df['vol'].values
        _, p_up, p_down = dapan_direction.compute_direction(close, high, low, vol, return_probs=True)
        pu = np.asarray(p_up, dtype=float)
        # 斜率
        slope = np.full(len(pu), 0.0)
        if len(pu) > SLOPE_WINDOW:
            slope[SLOPE_WINDOW:] = pu[SLOPE_WINDOW:] - pu[:-SLOPE_WINDOW]
        # V6 信号
        signal = (slope > 0) | (pu > PU_LEVEL)   # True = 持有
        # 日收益
        ret = np.diff(close) / close[:-1]          # ret[t] 对应 t -> t+1
        # 持仓: 前一日信号决定今日 (shift 1)
        pos = signal[:-1].astype(float)            # pos[t] = signal[t-1], 对应 ret[t]
        strat_ret = np.prod(1 + ret * pos) - 1
        # Buy&Hold
        bh_ret = close[-1] / close[0] - 1
        # 当前 Pu
        cur_pu = pu[-1]
        cur_slope = slope[-1]
        results.append({
            '行业': sec,
            'BuyHold%': round(bh_ret * 100, 1),
            'V6择时%': round(strat_ret * 100, 1),
            '超额%': round((strat_ret - bh_ret) * 100, 1),
            '当前Pu': round(cur_pu, 1),
            '当前Pd': round(p_down[-1], 1),
            '当前斜率': round(cur_slope, 1),
            '持仓天数': int(signal.sum()),
        })

    df = pd.DataFrame(results).sort_values('V6择时%', ascending=False)
    pd.set_option('display.max_rows', 50)
    pd.set_option('display.width', 200)
    print()
    print(df.to_string(index=False))

    n = len(df)
    n_beat = int((df['超额%'] > 0).sum())
    print()
    print(f'=== 汇总: {n} 个行业, 跑赢 Buy&Hold {n_beat} 个 ({n_beat/n*100:.0f}%) ===')
    print(f'  Buy&Hold 中位: {df["BuyHold%"].median():.1f}% | V6择时中位: {df["V6择时%"].median():.1f}%')
    print(f'  超额中位: {df["超额%"].median():.1f}% | 超额均值: {df["超额%"].mean():.1f}%')

    # 当前 Pu top5
    print()
    print('=== 当前上升概率 Pu 最大 5 个板块 ===')
    top5 = df.sort_values('当前Pu', ascending=False).head(5)
    print(top5[['行业', '当前Pu', '当前Pd', '当前斜率', 'V6择时%', 'BuyHold%']].to_string(index=False))


if __name__ == '__main__':
    main()
