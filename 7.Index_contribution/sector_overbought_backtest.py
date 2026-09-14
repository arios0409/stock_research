#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
超买超卖(20日反转连续版) 完整6年回测
对每个板块: 权重 ∝ (1 - k * 20日累计涨幅), 涨多降权/跌多加权, 归一化后持有。
k=0 即纯等权; k 越大逆向越激进。shift2 (T日信号→T+1尾盘买入→T+2享收益)。
"""
import os
import sys
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')


def yearly(rr, dates):
    nav = np.cumprod(1 + rr)
    years = pd.Series(dates).str[:4].values
    out = {}
    for y in sorted(set(years)):
        idx = np.where(years == y)[0]
        s = nav[idx[0] - 1] if idx[0] > 0 else 1.0
        out[y] = nav[idx[-1]] / s - 1
    return out


def main():
    df = pd.read_csv(os.path.join(OUT_DIR, 'sector_ret_cache.csv'), index_col=0)
    df.index = df.index.astype(str)
    arr = df.values
    r = arr / 100.0
    n_days, n_sec = r.shape
    r20 = np.nan_to_num(df.rolling(20, min_periods=20).sum().values, nan=0.0)

    def run(k, shift=2):
        raw = 1.0 - k * r20 / 100.0
        raw = np.clip(raw, 0.0, None)
        w = raw / raw.sum(axis=1, keepdims=True)
        wp = np.roll(w, shift, axis=0)
        wp[:shift] = 0
        return (wp * r).sum(axis=1)

    print(f'超买超卖(20日反转连续版)  {df.index[0]}~{df.index[-1]}  {n_days}天  shift2')
    print()
    hdr = f"{'k':<6}{'累计':>10}{'年化':>9}{'回撤':>9}{'夏普':>8}"
    print(hdr + '   ' + '  '.join(f'{y[2:]:>6}' for y in sorted(set(pd.Series(df.index).str[:4]))))
    print('-' * 100)
    results = {}
    for k in [0, 0.5, 1, 2, 3]:
        rr = run(k)
        nav = np.cumprod(1 + rr)
        tot = nav[-1] - 1
        ann = nav[-1] ** (1 / (len(rr) / 244)) - 1
        mdd = (nav / np.maximum.accumulate(nav) - 1).min()
        sh = rr.mean() / (rr.std() + 1e-12) * np.sqrt(244)
        y = yearly(rr, df.index)
        ys = '  '.join(f'{y.get(ky, 0)*100:>+6.1f}%' for ky in sorted(set(pd.Series(df.index).str[:4])))
        print(f'k={k:<5}{tot*100:>+9.1f}%{ann*100:>+8.1f}%{mdd*100:>+8.1f}%{sh:>8.2f}   {ys}')
        results[k] = (tot, ann, mdd, sh)
    print()
    print('结论参考: k=0 纯等权, k 越大逆向越激进。看 2021(趋势) 2022(熊) 是否回吐。')


if __name__ == '__main__':
    main()
